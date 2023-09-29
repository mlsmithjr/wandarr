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

    # if len(sys.argv) == 2 and sys.argv[1] == '-h':
    #     print(f'dtt (ver {__version__})')
    #     print('usage: dtt -t <template> [OPTIONS] [--host <name>] [--from-file <filename>] [file ...]')
    #     print('  or   dtt --agent')
    #     print('  --agent    Start in agent mode on a host and listen for transcode requests from other dtt.')
    #     print(
    #         'The --from-file filename is a file containing a list of full paths to files for transcoding. ')
    #     print('OPTIONS:')
    #     print('  --host <name>  Name of a specific host in your cluster configuration to target, otherwise load-balanced')
    #     print('  --dry-run  Run without actually transcoding or modifying anything, useful to test rules and profiles')
    #     print('  -v         Verbose output, helpful in debugging profiles and rules')
    #     print(
    #         '  -k         Keep source files after transcoding. If used, the transcoded file will have the same '
    #         'name and .tmp extension')
    #     print('  -y <file>  Full path to configuration file.  Default is ~/.dtt.yml')
    #     print('  -p         profile to use. If used with --from-file, applies to all listed media in <filename>')
    #     print('\n** PyPi Repo: https://pypi.org/project/dtt/')
    #     print('** Read the docs at https://dtt.readthedocs.io/en/latest/')
    #     sys.exit(0)

    install_sigint_handler()

    # configfile_name = DEFAULT_CONFIG
    # files = list()
    # template = None
    # agent_mode = False
    # host_override = None
    # from_file = None

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
    parser.add_argument('--host', dest='host_override',
                        action='store', help="Only run transcode on given host (from cluster definition)")
    parser.add_argument('--from-file', dest='from_file',
                        action='store', help='Filename that contains list of full paths of files to transcode')

    # configfile: Optional[ConfigFile] = None

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

    # if len(sys.argv) > 1:
    #     files = []
    #     arg = 1
    #     while arg < len(sys.argv):
    #         if sys.argv[arg] == '--from-file':          # load filenames to encode from given file
    #             if not template:
    #                 print("-t must be specified before --from-file")
    #                 sys.exit(1)
    #             queue_path = sys.argv[arg + 1]
    #             arg += 1
    #             tmpfiles = files_from_file(queue_path)
    #             files.extend([(f, template) for f in tmpfiles])
    #         elif sys.argv[arg] == '-t':                 # specific template
    #             template = sys.argv[arg + 1]
    #             arg += 1
    #         elif sys.argv[arg] == '-y':                 # specify yaml config file
    #             arg += 1
    #             configfile = ConfigFile(sys.argv[arg])
    #         elif sys.argv[arg] == '-k':                 # keep original
    #             dtt.keep_source = True
    #         elif sys.argv[arg] == '--dry-run':
    #             dtt.dry_run = True
    #         elif sys.argv[arg] == '--host':             # run all cluster encodes on specific host
    #             host_override = sys.argv[arg + 1]
    #             arg += 1
    #         elif sys.argv[arg] == '-v':                 # verbose
    #             dtt.verbose = True
    #         elif sys.argv[arg] == "--agent":            # agent/server mode
    #             agent_mode = True
    #             arg += 1
    #         else:
    #             if not template:
    #                 print("-t must be specified before file(s)")
    #                 sys.exit(1)
    #
    #             if os.name == "nt":
    #                 expanded_files: List = glob.glob(sys.argv[arg])     # handle wildcards in Windows
    #             else:
    #                 expanded_files = [sys.argv[arg]]
    #             for f in expanded_files:
    #                 files.append((f, template))
    #         arg += 1

    configfile = ConfigFile(configfile_name)

    if agent_mode:
        agent = Agent()
        agent.run()
        sys.exit(0)

    if len(files) == 0:
        print(crayons.yellow(f'No files - nothing to do'))
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
        for name, this_config in configfile.hosts.items():
            if name != host_override:
                this_config['status'] = 'disabled'

    completed: List = manage_cluster(files, configfile)
    if len(completed) > 0:
        dump_stats(completed)
    sys.exit(0)


if __name__ == '__main__':
    start()
