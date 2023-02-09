import argparse
from collections import namedtuple
import os
import sys
import json
from typing import Dict, List
import git
from distutils.version import StrictVersion
import yaml

from git import Repo

Config = namedtuple('Config', ['helm_charts_dir', 'repo_url'])


def _get_all_releases(repo_url: str) -> Dict[str, List[str]]:
    """_summary_

    Args:
        repo_url (_type_): _description_

    Returns:
         Dict[str, List[str]]:: key, values pairs of applications
         and all their releases, unsorted
    """
    all_releases = [v for v in filter(lambda x: len(x) == 2,
                                      map(lambda x: x.split('refs/tags/')[1].rsplit('-', 1),
                                          git.cmd.Git().ls_remote('--tags',
                                                                  '--refs',
                                                                  repo_url).split('\n')))]

    releases_dict = {}
    for r in all_releases:
        if not StrictVersion.version_re.match(r[1]):
            continue

        if r[0] not in releases_dict:
            releases_dict[r[0]] = [r[1]]
            continue

        releases_dict[r[0]].append(r[1])

    return releases_dict


def get_latest_releases(repo_url: str) -> Dict[str, str]:
    """ Get all the latest releases

    Args:
        repo_url: The url of the github repository

    Returns:
        Dict[str, str]: key, value pairs of the latest releases
    """
    last_release = {}
    for k, v in _get_all_releases(repo_url).items():
        last_release[k] = max(v, key=StrictVersion)

    return last_release


def get_all_charts(config: Config) -> List[str]:
    all_chart_dirs = filter(
        lambda x: os.path.isdir(os.path.join(x, 'helm-charts')),
        [f.path for f in os.scandir(config.helm_charts_dir) if f.is_dir()])
    return list(all_chart_dirs)


def check_new_chart_release(latest_releases: Dict[str, str],
                            all_charts_dirs: List[str]) -> Dict[str, str]:
    charts_need_to_release: Dict(str, str) = {}
    for chart_dir in all_charts_dirs:
        chart_file = os.path.join(chart_dir, 'helm-charts', 'Chart.yaml')
        with open(chart_file, 'r') as chart_yaml_file:
            chart_yaml_spec = yaml.load(chart_yaml_file,
                                        Loader=yaml.FullLoader)

            if ('type' in chart_yaml_spec and
                    chart_yaml_spec['type'] == 'library'):
                continue

            app_name = chart_yaml_spec['name']
            if (app_name not in latest_releases or
               chart_yaml_spec['version'] != latest_releases[app_name]):
                charts_need_to_release[app_name] = chart_yaml_spec['version']

    return charts_need_to_release


def build_the_charts(charts: Dict[str, str]):
    for chart, version in charts.items():
        print(chart, version)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('helm_charts_dir',
                        help='directory contains all the charts')
    parser.add_argument('repo_url', help='url to repository on github')
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    #repo = Repo.clone_from('git@github.com:mobitroll/service-containers.git', 'service-containers')
    # repo.git.fetch('--tags')
    # git@github.com:mobitroll/service-containers.git'

    args = parse_args()
    config = Config(args.helm_charts_dir, args.repo_url)

    latest_releases = get_latest_releases(config.repo_url)
    all_charts = get_all_charts(config)

    # find the version to release
    new_charts_to_release = check_new_chart_release(
        latest_releases, all_charts)

    # build the chart
    build_the_charts(new_charts_to_release)

    # update the index file.
