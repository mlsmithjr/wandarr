#!/usr/bin/python3
import glob
import os
import sys
import signal
from typing import List
import argparse

import wandarr

from wandarr import __version__
from wandarr.agent import Agent
from wandarr.cluster import manage_cluster
from wandarr.config import ConfigFile
from wandarr.ffmpeg import FFmpeg
from wandarr.media import MediaInfo
from wandarr.utils import files_from_file, dump_stats

DEFAULT_CONFIG = os.path.expanduser('~/.wandarr.yml')


def install_sigint_handler():

    def signal_handler(sig, frame):
        print('Process terminated')
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)


def init_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"wandarr (ver {__version__})")
    parser.add_argument(dest='files', metavar='filename', nargs='*')
    parser.add_argument('-v', dest='verbose',
                        action='store_true', help='verbose mode')
    parser.add_argument("-i", help="show technical info on files and stop",
                        action="store_true", dest="show_info")
    parser.add_argument('-k', dest='keep_source',
                        action='store_true', help='keep source (do not replace)')
    parser.add_argument('--dry-run', dest='dry_run',
                        action='store_true', help="Test run, show steps but don't change anything")
    parser.add_argument('-y', dest='configfile_name', default=DEFAULT_CONFIG,
                        action='store', help='Full path to configuration file.  Default is ~/.wandarr.yml')
    parser.add_argument('--agent', dest='agent_mode',
                        action='store_true',
                        help="Start in agent mode on a host and listen for transcode requests from other wandarr.")
    parser.add_argument('-t', dest='template', required=False,
                        action='store', help="Template name to use for transcode jobs")
    parser.add_argument('--hosts', dest='host_override',
                        action='store', help="Only run transcode on given host(s), comma-separated")
    parser.add_argument('--from-file', dest='from_file',
                        action='store', help='Filename that contains list of full paths of files to transcode')
    return parser


def finalize_files(files: list, from_file: str):
    if len(files) == 0:
        print('No files - nothing to do')
        sys.exit(0)

    enriched_files = []
    for f in files:
        expanded_files: List = glob.glob(f)  # support wildcards in Windows
        for ef in expanded_files:
            enriched_files.append(ef)
    files = enriched_files

    # if os.name == "nt":
    #     expanded_files: List = glob.glob(files[0])     # handle wildcards in Windows
    #     for f in expanded_files:
    #         files.append(f)

    if from_file:
        tmpfiles = files_from_file(from_file)
        files.extend(tmpfiles)
    return files

def setup_host_override(host_override: str, configfile: ConfigFile):
    if host_override is not None:
        # disable all other hosts in-memory only - to force encodes to the designated host
        host_list = host_override.split(",")
        for name, this_config in configfile.hosts.items():
            if name not in host_list:
                this_config['status'] = 'disabled'

def main():
    start()


def start():
    install_sigint_handler()

    parser = init_argparse()
    args = parser.parse_args()

    configfile_name = args.configfile_name
    files: List = args.files
    template = args.template
    agent_mode = args.agent_mode
    from_file = args.from_file
    host_override = args.host_override
    wandarr.VERBOSE = args.verbose
    wandarr.KEEP_SOURCE = args.keep_source
    wandarr.DRY_RUN = args.dry_run
    wandarr.SHOW_INFO = args.show_info
    if wandarr.SHOW_INFO:
        wandarr.DRY_RUN = True
        agent_mode = False

    if agent_mode:
        agent = Agent()
        agent.run()
        sys.exit(0)

    configfile = ConfigFile(configfile_name)

    files = finalize_files(files, from_file)
    setup_host_override(host_override, configfile)

    if wandarr.SHOW_INFO:
        MediaInfo.show_info(configfile.rich, files, FFmpeg(configfile.ffmpeg_path))
        sys.exit(0)

    if not template:
        print("A template is required")
        sys.exit(1)

    completed: List = manage_cluster(files, configfile, template)
    if len(completed) > 0:
        dump_stats(completed)
    sys.exit(0)


if __name__ == '__main__':
    start()
