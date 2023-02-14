""" Helm releasing script"""
import argparse
from collections import namedtuple
from datetime import datetime
import os
import shutil
import time
from typing import Dict, List
from distutils.version import StrictVersion
import subprocess
import hashlib
import yaml
import requests
import git

LOCK_FILE = '.lock'
GO_ICON = 'https://raw.githubusercontent.com/jenkins-x/jenkins-x-platform/d273e09/images/go.png'

Config = namedtuple(
    'Config', ['helm_charts_dir', 'chart_urlbase', 'chart_binary_dir'])


def get_all_releases() -> Dict[str, List[str]]:
    """ Get all releases so far

    Returns:
         Dict[str, List[str]]: name, version pairs of all releases
         and all their releases, unsorted
    """
    all_releases = filter(lambda x: len(x) == 2,
                          map(lambda x: x.split('refs/tags/')[1].rsplit('-', 1),
                              git.cmd.Git().ls_remote('--tags',
                                                      '--refs',
                                                      'origin').split('\n')))

    releases_dict = {}
    for release in all_releases:
        if not StrictVersion.version_re.match(release[1]):
            continue

        if release[0] not in releases_dict:
            releases_dict[release[0]] = [release[1]]
            continue

        releases_dict[release[0]].append(release[1])

    return releases_dict


def get_latest_releases() -> Dict[str, str]:
    """ Get all the latest releases

    Args:
        repo_url: The url of the github repository

    Returns:
        Dict[str, str]: name, version pairs of the latest releases
    """
    last_release = {}
    for key, value in get_all_releases().items():
        last_release[key] = max(value, key=StrictVersion)

    return last_release


def get_chart_spec(chart_dir: str) -> Dict:
    """_summary_

    Args:
        chart_dir (_type_): _description_

    Returns:
        _type_: _description_
    """
    chart_file = os.path.join(chart_dir, 'helm-charts', 'Chart.yaml')
    with open(chart_file, 'r') as chart_yaml_file:
        return yaml.load(chart_yaml_file,
                         Loader=yaml.FullLoader)


def is_it_library(chart_dir: str) -> bool:
    """_summary_

    Args:
        chart_dir (str): _description_

    Returns:
        bool: _description_
    """
    chart_yaml_spec = get_chart_spec(chart_dir)
    return ('type' in chart_yaml_spec and
            chart_yaml_spec['type'] == 'library')


def get_all_charts(config: Config) -> Dict[str, str]:
    """_summary_

    Args:
        config (Config): _description_

    Returns:
        Dict[str, str]: _description_
    """
    return {os.path.basename(chart_dir).strip(): get_chart_spec(chart_dir)['version']
            for chart_dir in filter(
                lambda x: os.path.isdir(os.path.join(x, 'helm-charts')) and
                not is_it_library(x),
                [f.path for f in os.scandir(config.helm_charts_dir) if f.is_dir()])}


def check_new_chart_release(latest_releases: Dict[str, str],
                            all_charts_dirs: List[str]) -> Dict[str, str]:
    """_summary_

    Args:
        latest_releases (Dict[str, str]): _description_
        all_charts_dirs (List[str]): _description_

    Returns:
        Dict[str, str]: _description_
    """
    charts_need_to_release: Dict(str, str) = {}
    for chart_dir, _ in all_charts_dirs.items():
        chart_yaml_spec = get_chart_spec(chart_dir)
        app_name = chart_yaml_spec['name']
        if app_name not in latest_releases:
            continue

        if chart_yaml_spec['version'] != latest_releases[app_name]:
            charts_need_to_release[app_name] = latest_releases[app_name]
            continue

    return charts_need_to_release


def update_version_number(chart_dir: str, version: str):
    """_summary_

    Args:
        chart_dir (str): _description_
        version (str): _description_
    """
    chart_yaml_spec = get_chart_spec(chart_dir)
    if chart_yaml_spec['version'] == version:
        return

    chart_file = os.path.join(chart_dir, 'helm-charts', 'Chart.yaml')
    with open(chart_file, 'w') as chart_yaml_file:
        yaml.dump(chart_yaml_spec, chart_yaml_file,
                  default_flow_style=False)


def build_the_charts(config: Config, charts: Dict[str, str]):
    """_summary_

    Args:
        config (Config): _description_
        charts (Dict[str, str]): _description_

    Raises:
        Exception: _description_
    """
    for chart, version in charts.items():
        update_version_number(chart, version)
        print(f'Building {chart}, {version}')
        chart_pacakge = get_chart_pacakage(chart, version)
        return_code = subprocess.call(
            f'cd {chart}&&helm package -u helm-charts/'
            f'&&mv {chart_pacakge} ../{config.chart_binary_dir}/',
            shell=True)

        if return_code != 0:
            raise Exception('can not package helm chart,'
                            'helm package helm-charts/'
                            f'returns {return_code}')


def sha256_of(filename: str) -> str:
    """_summary_

    Args:
        filename (str): _description_

    Returns:
        str: _description_
    """
    sha256_hash = hashlib.sha256()
    with open(filename, "rb") as file_to_read:
        for byte_block in iter(lambda: file_to_read.read(4096), b""):
            sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()


def get_chart_pacakage(chart: str, version: str) -> str:
    """_summary_

    Args:
        chart (_type_): _description_
        version (_type_): _description_

    Returns:
        _type_: _description_
    """
    return f'{chart}-{version}.tgz'


def existed_index_file(config: Config) -> Dict:
    """_summary_

    Args:
        config (Config): _description_

    Returns:
        Dict: _description_
    """
    # download the yaml index file
    response = requests.get(os.path.join(
        config.chart_urlbase, 'index.yaml'), timeout=10)
    if response is None or response.status_code != 200:
        print(f'Can not get the index yaml file {config.chart_urlbase}')
        return None

    return yaml.safe_load(response.text)


def build_index_file(config: Config, charts: Dict[str, str], index_yaml: Dict):
    """_summary_

    Args:
        config (Config): _description_
        charts (Dict[str, str]): _description_
        index_yaml (Dict): _description_
    """
    index_file = {
        'apiVersion': 'v1',
        'entries': {},
        'generated': '2022-12-19T18:30:21.074071309Z'
    }

    for chart_dir, _ in charts.items():
        chart_file = os.path.join(chart_dir, 'helm-charts', 'Chart.yaml')
        with open(chart_file, 'r') as chart_yaml_file:
            chart_yaml_spec = yaml.load(chart_yaml_file,
                                        Loader=yaml.FullLoader)
            chart_package = get_chart_pacakage(chart_yaml_spec["name"],
                                               chart_yaml_spec["version"])
            chart_item = {
                'apiVersion': chart_yaml_spec['apiVersion'],
                'appVersion': chart_yaml_spec['appVersion'],
                'created': datetime.now().isoformat(),
                'description': chart_yaml_spec['description'],
                'digest': sha256_of(os.path.join(config.chart_binary_dir, chart_package)),
                'icon': GO_ICON,
                'name': chart_yaml_spec['name'],
                'urls': [f'{config.chart_urlbase}/{chart_package}'],
                'version': chart_yaml_spec['version']
            }

            index_file['entries'][chart_yaml_spec['name']] = chart_item

    if index_yaml is not None:
        index_yaml['entries'].update(index_file['entries'])
    else:
        index_yaml = index_file

    with open(os.path.join(config.chart_binary_dir, 'index.yaml'), 'w') as index_yaml_file:
        yaml.dump(index_yaml, index_yaml_file,
                  default_flow_style=False)


def parse_args():
    """_summary_

    Returns:
        _type_: _description_
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('helm_charts_dir',
                        help='directory contains all the charts')
    parser.add_argument(
        'chart_urlbase', help='chart urlbase, e.g. https://fredrikluo.github.io/boilerplate')
    args = parser.parse_args()
    return args


def log_charts(prefix, charts: Dict[str, str]):
    """_summary_

    Args:
        prefix (_type_): _description_
        charts (Dict[str, str]): _description_
    """
    print(f'{prefix}:')
    print('\n'.join([f'  {k}:{v}' for k, v in charts.items()]))


def lock_and_clean(config: Config) -> bool:
    """_summary_

    Args:
        config (Config): _description_

    Returns:
        _type_: _description_
    """
    lockfilename = os.path.join(config.chart_binary_dir, LOCK_FILE)
    if (os.path.isfile(lockfilename) and
            time.time() - os.path.getmtime(lockfilename) < 120):
        print('The lock file exists')
        return False

    if os.path.isdir(config.chart_binary_dir):
        shutil.rmtree(config.chart_binary_dir)

    os.mkdir(config.chart_binary_dir)

    # write our pid to the file
    with open(lockfilename, 'w') as lock_file_towrite:
        lock_file_towrite.write(f'{os.getpid()}')

    return True


def unlock(config: Config):
    """_summary_

    Args:
        config (Config): _description_
    """
    # check if we own the file:
    lockfilename = os.path.join(config.chart_binary_dir, LOCK_FILE)
    with open(lockfilename, 'r') as local_file_read:
        pid = local_file_read.readline().strip()
        if os.getpid() != int(pid):
            print('we do not own the lock file,'
                  f' another process is running {pid} {os.getpid()}')
            return

    # delete the file
    os.remove(lockfilename)


def build_charts(config: Config,
                 all_charts: Dict[str, str],
                 latest_releases: Dict[str, str],
                 index_yaml: Dict):
    """_summary_

    Args:
        config (Config): _description_
        all_charts (Dict[str, str]): _description_
        latest_releases (Dict[str, str]): _description_
        index_yaml (Dict): _description_
    """
    if not lock_and_clean(config):
        print('can not lock the file, another process is running')
        return

    try:
        # see if we need to build everything
        if index_yaml is None:
            new_charts_to_release = latest_releases
        else:
            new_charts_to_release = check_new_chart_release(
                latest_releases, all_charts)

        log_charts('Found charts', all_charts)
        log_charts('Charts to build', new_charts_to_release)

        if not new_charts_to_release:
            print('Nothing to build')
            return

        # build the chart
        build_the_charts(config, new_charts_to_release)

        # update the index file.
        build_index_file(config, new_charts_to_release, index_yaml)
    finally:
        unlock(config)


if __name__ == '__main__':
    ARGS = parse_args()
    CFG = Config(ARGS.helm_charts_dir,
                 ARGS.chart_urlbase,
                 '.build')

    build_charts(CFG,
                 get_all_charts(CFG),
                 get_latest_releases(),
                 existed_index_file(CFG))
