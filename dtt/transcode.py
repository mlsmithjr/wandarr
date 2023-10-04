#!/usr/bin/python3
import glob
import os
import sys
from typing import List
import argparse

import dtt

from dtt import __version__
from dtt.agent import Agent
from dtt.cluster import manage_cluster
from dtt.config import ConfigFile
from dtt.utils import files_from_file, dump_stats

DEFAULT_CONFIG = os.path.expanduser('~/.dtt.yml')


def install_sigint_handler():
    import signal
    import sys

    def signal_handler(signal, frame):
        print('Process terminated')
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)


def main():
    start()


def start():

    install_sigint_handler()

    parser = argparse.ArgumentParser(description=f"dtt (ver {__version__})")
    parser.add_argument(dest='files', metavar='filename', nargs='*')
    parser.add_argument('-v', dest='verbose',
                        action='store_true', help='verbose mode')
    parser.add_argument('-k', dest='keep_source',
                        action='store_true', help='keep source (do not replace)')
    parser.add_argument('--dry-run', dest='dry_run',
                        action='store_true', help="Test run, output steps but don't change anything")
    parser.add_argument('-y', dest='configfile_name', default=DEFAULT_CONFIG,
                        action='store', help='Full path to configuration file.  Default is ~/.dtt.yml')
    parser.add_argument('--agent', dest='agent_mode',
                        action='store_true', help="Start in agent mode on a host and listen for transcode requests from other dtt.")
    parser.add_argument('-t', dest='template', required=True,
                        action='store', help="Template name to use for transcode jobs")
    parser.add_argument('--hosts', dest='host_override',
                        action='store', help="Only run transcode on given host(s), comma-separated")
    parser.add_argument('--from-file', dest='from_file',
                        action='store', help='Filename that contains list of full paths of files to transcode')

    args = parser.parse_args()

    configfile_name = args.configfile_name
    files: List = args.files
    template = args.template
    agent_mode = args.agent_mode
    from_file = args.from_file
    host_override = args.host_override
    dtt.verbose = args.verbose
    dtt.keep_source = args.keep_source
    dtt.dry_run = args.dry_run

    if agent_mode:
        agent = Agent()
        agent.run()
        sys.exit(0)

    configfile = ConfigFile(configfile_name)

    if len(files) == 0:
        print(f'No files - nothing to do')
        sys.exit(0)

    # add template to each file
    enriched_files = []
    for f in files:
        expanded_files: List = glob.glob(f)     # support wildcards in Windows
        for ef in expanded_files:
            enriched_files.append((ef, template))
    files = enriched_files

    # if os.name == "nt":
    #     expanded_files: List = glob.glob(files[0])     # handle wildcards in Windows
    #     for f in expanded_files:
    #         files.append((f, template))

    if from_file:
        tmpfiles = files_from_file(from_file)
        files.extend([(f, template) for f in tmpfiles])

    if host_override is not None:
        # disable all other hosts in-memory only - to force encodes to the designated host
        host_list = host_override.split(",")
        for name, this_config in configfile.hosts.items():
            if name not in host_list:
                this_config['status'] = 'disabled'

    completed: List = manage_cluster(files, configfile)
    if len(completed) > 0:
        dump_stats(completed)
    sys.exit(0)


if __name__ == '__main__':
    start()
