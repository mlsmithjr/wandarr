import datetime
import os
import re
import subprocess
import sys
import threading
from pathlib import PurePath
from random import randint
import socket
from tempfile import gettempdir
from typing import Dict, Any, Optional
import json

import wandarr
from wandarr.media import MediaInfo

status_re = re.compile(
    r'^.*frame=\s*(?P<frame>\d+?) fps=\s*(?P<fps>.+?) q=(?P<q>.+\.\d) size=\s*(?P<size>\d+?)(?:(kB)|(KiB)) time=(?P<time>(\d\d:\d\d:\d\d\.\d\d)|(N/A)) .*speed=(?P<speed>(N/A)|(.*x))')

_CHARSET: str = sys.getdefaultencoding()


class FFmpeg:

    def __init__(self, ffmpeg_path: str):
        self.path = ffmpeg_path
        self.log_path: PurePath = None
        self.last_command = ''
        self.monitor_interval = 10

    def execute_and_monitor(self, params, event_callback, monitor) -> Optional[int]:
        self.last_command = ' '.join([self.path, *params])
        with subprocess.Popen([self.path,
                               *params],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              universal_newlines=True,
                              shell=False) as p:

            for stats in monitor(p):
                if event_callback is not None:
                    veto = event_callback(stats)
                    if veto:
                        p.kill()
                        return None
            return p.returncode

    def monitor_agent_ffmpeg(self, sock, event_callback, monitor):
        stats = None
        for stats in monitor(sock):
            if isinstance(stats, str):
                break
            if event_callback is not None:
                veto = event_callback(stats)
                if veto:
                    sock.send(bytes("VETO".encode()))
                    return False, stats
        return True, stats

    def remote_execute_and_monitor(self, sshcli: str, user: str, ip: str, params: list, event_callback, monitor) -> Optional[int]:
        cli = [sshcli, '-v', user + '@' + ip, self.path, *params]
        self.last_command = ' '.join(cli)
        with subprocess.Popen(cli,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              universal_newlines=True,
                              shell=False) as p:
            try:
                for stats in monitor(p):
                    if event_callback is not None:
                        veto = event_callback(stats)
                        if veto:
                            p.kill()
                            return None
                return p.returncode
            except KeyboardInterrupt:
                p.kill()
        return None

    def fetch_details(self, _path: str) -> MediaInfo:
        """Use ffmpeg to get media information

        :param _path:   Absolute path to media file
        :return:        Instance of MediaInfo
        """

        #
        # try ffprobe first since it's json output just better. ffprobe is typically installed in the same
        # location as ffmpeg
        #
        try:
            mi = self.fetch_details_ffprobe(_path)
            if mi:
                if mi.frames == 0:
                    print(f"Notice: 'frames' runtime metadata missing from {_path} - progress indicator will be inaccurate")
                return mi
        except Exception as ex:
            pass

        #
        # fall back to using ffmpeg itself and parsing out details with regex
        #
        with subprocess.Popen([self.path, '-i', _path], stderr=subprocess.PIPE) as proc:
            output = proc.stderr.read().decode(encoding='utf8')
            mi = MediaInfo.parse_ffmpeg_details(_path, output)
            if mi.valid:
                if mi.runtime == 0:
                    print(f"Notice: runtime metadata missing from {_path} - progress indicator will be inaccurate")
                return mi

        return MediaInfo(None)

    def fetch_details_ffprobe(self, _path: str) -> MediaInfo:
        ffprobe_path = str(PurePath(self.path).parent.joinpath('ffprobe'))
        if not os.path.exists(ffprobe_path):
            return MediaInfo(None)

        args = [ffprobe_path, '-v', '1', '-show_streams', '-print_format', 'json', '-i', _path]
        with subprocess.Popen(args, stdout=subprocess.PIPE) as proc:
            output = proc.stdout.read().decode(encoding='utf8')
            info = json.loads(output)
            return MediaInfo.parse_ffprobe_details_json(_path, info)

    def monitor_ffmpeg(self, proc: subprocess.Popen):
        diff = datetime.timedelta(seconds=self.monitor_interval)
        event = datetime.datetime.now() + diff

        #
        # Create a transaction log for this run, to be left behind if an error is encountered.
        #
        suffix = randint(100, 999)
        self.log_path: PurePath = PurePath(gettempdir(), 'wandarr-' +
                                           threading.current_thread().name + '-' +
                                           str(suffix) + '.log')

        info: Dict[str, Any] = {}

        with open(str(self.log_path), 'w', encoding="utf8") as logfile:
            while proc.poll() is None:
                line = proc.stdout.readline()
                logfile.write(line)
                logfile.flush()

                if wandarr.VERBOSE:
                    print(line, end='')     # output from ffmpeg already has cr/lf
                match = status_re.match(line)
                if match is not None and len(match.groups()) >= 5:
                    info = match.groupdict()

                    info['frame'] = int(info['frame'])
                    info['size'] = int(info['size'].strip()) * 1024
                    if info['time'] != 'N/A':
                        hh, mm, ss = info['time'].split(':')
                        ss = ss.split('.')[0]
                        info['time'] = (int(hh) * 3600) + (int(mm) * 60) + int(ss)

                    if datetime.datetime.now() > event:
                        yield info
                        event = datetime.datetime.now() + diff

        if proc.returncode == 0:
            # if we got here then everything went fine, so remove the transaction log
            try:
                os.remove(str(self.log_path))
            except Exception:
                pass
            self.log_path = None
        # yield the final info results before terminating loop
        yield info

    def monitor_agent(self, sock: socket.socket):
        suffix = randint(100, 999)
        self.log_path: PurePath = PurePath(gettempdir(), 'wandarr-' +
                                           threading.current_thread().name + '-' +
                                           str(suffix) + '.log')

        diff = datetime.timedelta(seconds=self.monitor_interval)
        event = datetime.datetime.now() + diff
#        print(f"See error log at {self.log_path}")
        with open(str(self.log_path), 'w', encoding="utf8") as logfile:
            while True:
                sock.settimeout(10)
                c = sock.recv(4096).decode()
                logfile.write(c)
                logfile.flush()
                if c.startswith("DONE|") or c.startswith("ERR|"):
#                    print("Transcode complete")
                    # found end of processing marker
                    try:
                        if c.startswith("ERR|"):
                            print(f"See error log at {self.log_path}")
                            break
                        os.remove(str(self.log_path))
                        self.log_path = None
                    except Exception as ex:
                        print(str(ex))

                    yield c

                sock.send(bytes("ACK!".encode()))
                line = c

                match = status_re.match(line)
                if match is not None and len(match.groups()) >= 5:
                    if datetime.datetime.now() > event:
                        event = datetime.datetime.now() + diff
                        info: Dict[str, Any] = match.groupdict()

                        info['frame'] = int(info['frame'])
                        info['size'] = int(info['size'].strip()) * 1024
                        hh, mm, ss = info['time'].split(':')
                        ss = ss.split('.')[0]
                        info['time'] = (int(hh) * 3600) + (int(mm) * 60) + int(ss)
                        yield info

    def run(self, params, event_callback) -> Optional[int]:
        return self.execute_and_monitor(params, event_callback, self.monitor_ffmpeg)

    def run_remote(self, sshcli: str, user: str, ip: str, params: list, event_callback) -> Optional[int]:
        return self.remote_execute_and_monitor(sshcli, user, ip, params, event_callback, self.monitor_ffmpeg)
