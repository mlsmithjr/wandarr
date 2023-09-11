#!/usr/bin/python3
import glob
import os
import sys
from typing import List, Optional

import crayons

import dtt

from dtt import __version__
from dtt.agent import Agent
from dtt.cluster import manage_cluster
from dtt.config import ConfigFile
from dtt.utils import files_from_file, dump_stats

DEFAULT_CONFIG = os.path.expanduser('~/.transcode.yml')


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

    if len(sys.argv) == 2 and sys.argv[1] == '-h':
        print(f'dtt (ver {__version__})')
        print('usage: dtt [OPTIONS] [--host <name>] [--from-file <filename>] [file ...]')
        print('  or   dtt --agent')
        print('  --agent    Start in agent mode on a host and listen for transcode requests from other dtt.')
        print(
            'The --from-file filename is a file containing a list of full paths to files for transcoding. ')
        print('OPTIONS:')
        print('  --host <name>  Name of a specific host in your cluster configuration to target, otherwise load-balanced')
        print('  -s         Process files sequentially even if configured for multiple concurrent jobs')
        print('  --dry-run  Run without actually transcoding or modifying anything, useful to test rules and profiles')
        print('  -v         Verbose output, helpful in debugging profiles and rules')
        print(
            '  -k         Keep source files after transcoding. If used, the transcoded file will have the same '
            'name and .tmp extension')
        print('  -y <file>  Full path to configuration file.  Default is ~/.transcode.yml')
        print('  -p         profile to use. If used with --from-file, applies to all listed media in <filename>')
        print('\n** PyPi Repo: https://pypi.org/project/dtt/')
        print('** Read the docs at https://dtt.readthedocs.io/en/latest/')
        sys.exit(0)

    install_sigint_handler()

    files = list()
    template = None
    agent_mode = False
    configfile: Optional[ConfigFile] = None
    host_override = None
    if len(sys.argv) > 1:
        files = []
        arg = 1
        while arg < len(sys.argv):
            if sys.argv[arg] == '--from-file':          # load filenames to encode from given file
                if not template:
                    print("-t must be specified before --from-file")
                    sys.exit(1)
                queue_path = sys.argv[arg + 1]
                arg += 1
                tmpfiles = files_from_file(queue_path)
                files.extend([(f, template) for f in tmpfiles])
            elif sys.argv[arg] == '-t':                 # specific template
                template = sys.argv[arg + 1]
                arg += 1
            elif sys.argv[arg] == '-y':                 # specify yaml config file
                arg += 1
                configfile = ConfigFile(sys.argv[arg])
            elif sys.argv[arg] == '-k':                 # keep original
                dtt.keep_source = True
            elif sys.argv[arg] == '--dry-run':
                dtt.dry_run = True
            elif sys.argv[arg] == '--host':             # run all cluster encodes on specific host
                host_override = sys.argv[arg + 1]
                arg += 1
            elif sys.argv[arg] == '-v':                 # verbose
                dtt.verbose = True
            elif sys.argv[arg] == "--agent":            # agent/server mode
                agent_mode = True
                arg += 1
            else:
                if not template:
                    print("-t must be specified before file(s)")
                    sys.exit(1)

                if os.name == "nt":
                    expanded_files: List = glob.glob(sys.argv[arg])     # handle wildcards in Windows
                else:
                    expanded_files = [sys.argv[arg]]
                for f in expanded_files:
                    files.append((f, template))
            arg += 1

    if agent_mode:
        agent = Agent()
        agent.run()
        sys.exit(0)

    if configfile is None:
        configfile = ConfigFile(DEFAULT_CONFIG)

    if not configfile.colorize:
        crayons.disable()
    else:
        crayons.enable()

    if len(files) == 0:
        print(crayons.yellow(f'No files - nothing to do'))
        sys.exit(0)

    if host_override is not None:
        # disable all other hosts in-memory only - to force encodes to the designated host
        for name, this_config in configfile.hosts.items():
            if name != host_override:
                this_config['status'] = 'disabled'
    completed: List = manage_cluster(files, configfile)
    if len(completed) > 0:
        dump_stats(completed)
    sys.exit(0)


if __name__ == '__main__':
    start()
