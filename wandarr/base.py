import subprocess
import sys
from pathlib import PureWindowsPath, PosixPath
from threading import Thread
from typing import Dict, List
import os

import wandarr
from wandarr.ffmpeg import FFmpeg
from wandarr.media import MediaInfo
from wandarr.template import Template
from wandarr.utils import get_local_os_type, calculate_progress

if wandarr.console:
    from rich import print


class RemoteHostProperties:
    name: str
    props: Dict

    def __init__(self, name: str, props: Dict):
        self.props = props
        self.name = name

    @property
    def user(self):
        return self.props['user']

    @property
    def ip(self):
        return self.props['ip']

    @property
    def os(self):
        return self.props['os']

    @property
    def templates(self) -> List[str]:
        return self.props.get('templates', None)

    @property
    def working_dir(self):
        return self.props.get('working_dir', None)

    @property
    def host_type(self):
        return self.props['type']

    @property
    def ffmpeg_path(self):
        return self.props.get('ffmpeg', None)

    @property
    def is_enabled(self):
        return self.props.get('status', 'enabled') == 'enabled'

    @property
    def has_path_subst(self):
        return 'path-substitutions' in self.props

    @property
    def engines(self) -> Dict:
        return self.props.get('engines')

    def substitute_paths(self, in_path, out_path):
        lst = self.props['path-substitutions']
        for item in lst:
            src, dest = item.split(r' ')
            if in_path.startswith(src):
                in_path = in_path.replace(src, dest)
                out_path = out_path.replace(src, dest)
                break
        return in_path, out_path

    def is_windows(self):
        if self.props['type'] == 'local':
            return get_local_os_type() == 'windows'
        return self.props.get('os', None) in ['windows', 'win10']

    def is_linux(self):
        if self.props['type'] == 'local':
            return get_local_os_type() == 'linux'
        return self.props.get('os', None) == 'linux'

    def validate_settings(self):
        """Validate required settings"""
        msg = []
        if 'type' not in self.props:
            msg.append('Missing "type"')
        if 'status' not in self.props:
            msg.append('Missing "status"')
        if self.props['type'] in ['mounted', 'streaming']:
            if 'ip' not in self.props:
                msg.append('Missing "ip"')
            if 'user' not in self.props:
                msg.append('Missing "user"')
            if 'os' not in self.props:
                msg.append('Missing "os"')
            else:
                _os = self.props['os']
                if _os not in ['macos', 'linux', 'windows', 'win10']:
                    msg.append(f'Unsupported "os" type {_os}')
        if self.props['type'] == 'streaming':
            if 'working_dir' not in self.props:
                msg.append('Missing "working_dir"')
        if len(msg) > 0:
            print(f'Validation error(s) for host {self.name}:')
            print('\n'.join(msg))
            return False
        return True


class EncodeJob:
    """One file to be encoded"""
    in_path: str
    media_info: MediaInfo
    template_name: str

    def __init__(self, in_path: str, info: MediaInfo, template: Template):
        self.in_path = os.path.abspath(in_path)
        self.media_info = info
        self.template = template

    def should_abort(self, pct_done, pct_comp) -> bool:
        if self.template.threshold_check() < 100:
            return pct_done >= self.template.threshold_check() and pct_comp < self.template.threshold()
        return False


class ManagedHost(Thread):
    """
        Base thread class for all remote host types.
    """

    def __init__(self, hostname, props, queue):
        """
        :param hostname:    name of host from cluster
        :param props:       dictionary of properties from cluster
        :param queue:       Work queue assigned to this thread, could be many-to-one in the future.
        """
        super().__init__(name=hostname, group=None, daemon=True)
        self.hostname = hostname
        self.props = props
        self.queue = queue
        self._complete = []
        self.ffmpeg = FFmpeg(props.ffmpeg_path)
        self.video_cli = None
        self.qname = None  # assigned queue
        self.engine_name = None

    def validate_settings(self):
        return self.props.validate_settings()

    def complete(self, source, elapsed=0):
        self._complete.append((source, elapsed))

    @property
    def completed(self) -> List:
        return self._complete

    def log(self, message: str, style: str = None):
        msg = f"{self.hostname:20}: {message}"
        if wandarr.console:
            wandarr.console.print(":warning: " + msg, style=style)
        else:
            print(message)
        sys.stdout.flush()

    def testrun(self):
        pass

    def converted_path(self, path):
        if " " in path:
            path = '"' + path + '"'
        if self.props.is_windows():
            path = path.replace(' ', '\ ')
            return str(PureWindowsPath(path))
        return str(PosixPath(path))

    def ssh_cmd(self):
        return [wandarr.SSH, self.props.user + '@' + self.props.ip]

    def ping_test_ok(self):
        addr = self.props.ip
        if os.name == "nt":
            ping = [r'C:\WINDOWS\system32\ping.exe', '-n', '1', '-w', '5', addr]
        else:
            ping = ['ping', '-c', '1', '-W', '5', addr]
        with subprocess.Popen(ping, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False) as p:
            p.communicate()
            if p.returncode != 0:
                self.log(f"Host at address {addr} cannot be reached - skipped", style="magenta")
                return False
            return True

    def ssh_test_ok(self):
        try:
            remote_cmd = 'dir' if self.props.is_windows() else 'ls'
            # remote_cmd = 'ls'
            ssh_test = subprocess.run([*self.ssh_cmd(), remote_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      shell=False, timeout=10, check=False)
            if ssh_test.returncode != 0:
                self.log('ssh test failed with the following output: ' + str(ssh_test.stderr), style="magenta")
                return False
            return True
        except subprocess.TimeoutExpired:
            return False

    def host_ok(self):
        return self.ping_test_ok() and self.ssh_test_ok()

    def run_process(self, *args):
        p = subprocess.run(*args, check=False)
        if wandarr.VERBOSE:
            self.log(' '.join(*args))
            if p.returncode != 0:
                self.log(p.stderr.decode("utf-8"))
        return p

    def terminate(self):
        pass

    def map_streams(self, job: EncodeJob):
        if job.media_info.is_multistream():
            stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                                                 job.media_info.subtitle)
            return stream_map
        return []

    def callback_wrapper(self, job: EncodeJob):
        def log_callback(stats):
            if not stats:
                return False

            pct_done, pct_comp = calculate_progress(job.media_info, stats)
            wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                      'file': os.path.basename(job.in_path),
                                      'speed': "---" if stats['speed'] == "N/A" else f"{stats['speed']}x",
                                      'comp': f"{pct_comp}%",
                                      'completed': pct_done})

            if job.should_abort(pct_done, pct_comp):
                wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                          'file': os.path.basename(job.in_path),
                                          'speed': "---" if stats['speed'] == "N/A" else f"{stats['speed']}x",
                                          'comp': f"{pct_comp}%",
                                          'completed': 100,
                                          'status': "Skipped (threshold)"})
                return True
            return False

        return log_callback

    def dump_job_info(self, job: EncodeJob, cli):
        if wandarr.DRY_RUN:
            #
            # display useful information
            #
            print('-' * 40)
            print(f'Host     : {self.hostname}')
            print('Filename : ' + os.path.basename(job.in_path))
            print(f'Template : {job.template.name()}')
            print('ffmpeg   : ' + ' '.join(cli) + '\n')
            return True
        return False
