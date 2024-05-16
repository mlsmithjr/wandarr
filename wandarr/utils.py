
import math
import os
import re
import platform
import subprocess
import urllib.request
from threading import Thread
from typing import Dict

import wandarr
from wandarr.media import MediaInfo
from wandarr.template import Template


class VersionFetcher(Thread):
    def __init__(self):
        super().__init__(daemon=True, name="VersionFetcher")
        self.version = None

    def run(self):
        try:
            with urllib.request.urlopen(
                    "https://raw.githubusercontent.com/mlsmithjr/wandarr/master/wandarr/__init__.py") as response:
                page = response.read().decode("utf-8")
                match = re.search(r'^__version__.=.[\'\"](\w\.\w\.\w)[\'\"]', page)
                if match:
                    self.version = match.group(1)
        except Exception as ex:
            # nothing we can do about this anyhow
            pass


def filter_threshold(template: Template, in_path: str, out_path: str):
    if template.threshold() > 0:
        orig_size = os.path.getsize(in_path)
        new_size = os.path.getsize(out_path)
        return is_exceeded_threshold(template.threshold(), orig_size, new_size)
    return True


def is_exceeded_threshold(pct_threshold: int, orig_size: int, new_size: int) -> bool:
    pct_savings = 100 - math.floor((new_size * 100) / orig_size)
    if pct_savings < pct_threshold:
        return False
    return True


def files_from_file(queue_path) -> list:
    if not os.path.exists(queue_path):
        print('Nothing to do.')
        return []
    with open(queue_path, 'r', encoding="utf8") as qf:
        _files = [fn.rstrip() for fn in qf.readlines()]
        return _files


def get_local_os_type():
    return {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'macos'}.get(platform.system(), 'unknown')


def calculate_progress(info: MediaInfo, stats: Dict) -> (int, int):

    #
    # Due to some recent changes in ffmpeg (post 7.0) the encoding output sometimes
    # shows N/A instead of needed information for current video timeframe. And even
    # when it isn't N/A it sometimes shows the same time value across multiple updates.
    # This causes the progress calculation to be inaccurate.
    # So now we also collect the number of frames to use to calculate percentage done in case
    # the times are presented as N/A
    #

    # default to using frames as it now seems to be the most accurate metric, at least until the
    # ffmpeg bug is fixed.
    if info.frames and stats['frame']:
        pct_done = int((stats['frame'] / info.frames) * 100)
    elif info.runtime > 0 and stats['time'] != 'N/A':
        pct_done = int((stats['time'] / info.runtime) * 100)
    else:
        pct_done = 0

    # extrapolate current compression %

    filesize = info.filesize_mb * 1024000
    pct_source = int(filesize * (pct_done / 100.0))
    if pct_source <= 0:
        return 0, 0
    pct_dest = int((stats['size'] / pct_source) * 100)
    pct_comp = 100 - pct_dest

    return pct_done, pct_comp


def run(cmd):
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False) as p:
        output = p.communicate()[0].decode('utf-8')
        return p.returncode, output


def dump_stats(completed):

    if wandarr.DRY_RUN:
        return

    paths = [p for p, _ in completed]
    max_width = len(max(paths, key=len))
    print("-" * (max_width + 9))
    for path, elapsed in completed:
        pathname = path.rjust(max_width)
        _min = int(elapsed / 60)
        _sec = int(elapsed % 60)
        print(f"{pathname}  ({_min:3}m {_sec:2}s)")
    print()
