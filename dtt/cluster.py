"""
    Cluster support
"""
import datetime
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import PureWindowsPath, PosixPath
from queue import Queue, Empty
from tempfile import gettempdir
from threading import Thread, Lock
from typing import Dict, List

import crayons

import dtt
from dtt import verbose
from dtt.config import ConfigFile
from dtt.ffmpeg import FFmpeg
from dtt.media import MediaInfo
from dtt.template import Template
from dtt.utils import filter_threshold, get_local_os_type, calculate_progress, run


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
            src, dest = item.split(' ')
            if src in in_path:
                in_path = in_path.replace(src, dest)
                out_path = out_path.replace(src, dest)
                break
        return in_path, out_path

    def is_windows(self):
        if self.props['type'] == 'local':
            return get_local_os_type() == 'win10'
        return self.props.get('os', None) == 'win10'

    def is_linux(self):
        if self.props['type'] == 'local':
            return get_local_os_type() == 'linux'
        return self.props.get('os', None) == 'linux'

    def escaped_filename(self, filename):
        """Find all special characters typically found in media names and escape to be shell-friendly"""
        if self.is_windows():
            return filename
        if self.is_linux():
            filename = filename.replace(r' ', r'\ ')
            filename = filename.replace(r'(', r'\(')
            filename = filename.replace(r')', r'\)')
            filename = filename.replace(r"'", r"\'")
            filename = filename.replace(r'"', r'\"')
            filename = filename.replace(r'!', r'\!')
            return "'" + filename + "'"
        return filename

    def validate_settings(self):
        """Validate required settings"""
        msg = list()
        'type' in self.props or msg.append(f'Missing "type"')
        'status' in self.props or msg.append(f'Missing "status"')
        if self.props['type'] in ['mounted', 'streaming']:
            'ip' in self.props or msg.append(f'Missing "ip"')
            'user' in self.props or msg.append(f'Missing "user"')
            'os' in self.props or msg.append(f'Missing "os"')
            if 'os' in self.props:
                _os = self.props['os']
                _os in ['macos', 'linux', 'win10'] or msg.append(f'Unsupported "os" type {_os}')
        if self.props['type'] == 'streaming':
            'working_dir' in self.props or msg.append(f'Missing "working_dir"')
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

    def should_abort(self, pct_comp) -> bool:
        if self.template.threshold_check() < 100:
            return self.template.threshold_check() <= pct_comp < self.template.threshold()
        return False


class ManagedHost(Thread):
    """
        Base thread class for all remote host types.
    """

    def __init__(self, hostname, props, queue, cluster):
        """
        :param hostname:    name of host from cluster
        :param props:       dictionary of properties from cluster
        :param queue:       Work queue assigned to this thread, could be many-to-one in the future.
        :param cluster:     Reference to parent Cluster object
        """
        super().__init__(name=hostname, group=None, daemon=True)
        self.hostname = hostname
        self.props = props
        self.queue = queue
        self._complete = list()
        self._manager = cluster
        self.ffmpeg = FFmpeg(props.ffmpeg_path)
        self.video_cli = None

    def validate_settings(self):
        return self.props.validate_settings()

    @property
    def lock(self):
        return self._manager.lock

    @property
    def configfile(self) -> ConfigFile:
        return self._manager.config

    def complete(self, source, elapsed=0):
        self._complete.append((source, elapsed))

    @property
    def completed(self) -> List:
        return self._complete

    def log(self, *args):
        self.lock.acquire()
        try:
            msg = crayons.blue(f'({self.hostname}): ')
            print(msg, *args)
            sys.stdout.flush()
        finally:
            self.lock.release()

    def testrun(self):
        pass

    def converted_path(self, path):
        if self.props.is_windows():
            path = '"' + path + '"'
            return str(PureWindowsPath(path))
        else:
            return str(PosixPath(path))

    def ssh_cmd(self):
        return [self._manager.ssh, self.props.user + '@' + self.props.ip]

    def ping_test_ok(self):
        addr = self.props.ip
        if os.name == "nt":
            ping = [r'C:\WINDOWS\system32\ping.exe', '-n', '1', '-w', '5', addr]
        else:
            ping = ['ping', '-c', '1', '-W', '5', addr]
        p = subprocess.Popen(ping, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        p.communicate()
        if p.returncode != 0:
            self.log(crayons.yellow(f'Host at address {addr} cannot be reached - skipped'))
            return False
        return True

    def ssh_test_ok(self):
        try:
            remote_cmd = 'dir' if self.props.is_windows() else 'ls'
            # remote_cmd = 'ls'
            ssh_test = subprocess.run([*self.ssh_cmd(), remote_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     shell=False, timeout=10)
            if ssh_test.returncode != 0:
                self.log('ssh test failed with the following output: ' + str(ssh_test.stderr))
                return False
            return True
        except subprocess.TimeoutExpired:
            return False

    def host_ok(self):
        return self.ping_test_ok() and self.ssh_test_ok()

    def run_process(self, *args):
        p = subprocess.run(*args)
        if self._manager.verbose:
            self.log(' '.join(*args))
            if p.returncode != 0:
                self.log(p.stderr)
        return p

    def terminate(self):
        pass


class AgentManagedHost(ManagedHost):
    """Implementation of a agent host worker thread"""

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue, cluster):
        super().__init__(hostname, props, queue, cluster)

    #
    # initiate tests through here to avoid a new thread
    #
    def testrun(self):
        self.go()

    #
    # normal threaded entry point
    #
    def run(self):
        if self.host_ok():
            self.go()
        else:
            self.log(f"{self.props.name} not available")

    def go(self):

        while not self.queue.empty():
            try:
                job: EncodeJob = self.queue.get()
                in_path = job.in_path

                #
                # build command line
                #
                remote_in_path = in_path

                video_options = self.video_cli.split(" ")
                stream_map = []
                if job.media_info.is_multistream() and self._manager.config.automap:
                    stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                                                         job.media_info.subtitle)

                cmd = [self.props.ffmpeg_path, '-y', *job.template.input_options_list(), '-i', '{FILENAME}',
                       *video_options,
                       *job.template.output_options_list(self._manager.config), *stream_map]

                #
                # display useful information
                #
                self.lock.acquire()
                try:
                    print('-' * 40)
                    print(f'Host     : {self.hostname} (agent)')
                    print('Filename : ' + crayons.green(os.path.basename(remote_in_path)))
                    print(f'Directive: {job.template.name()}')
                    print('Command  : ' + ' '.join(cmd) + '\n')
                finally:
                    self.lock.release()

                if dtt.dry_run:
                    continue

                basename = os.path.basename(job.in_path)

                def log_callback(stats):
                    pct_done, pct_comp = calculate_progress(job.media_info, stats)
                    dtt.status_queue.put({'host': self.hostname,
                                          'file': basename,
                                          'speed': stats['speed'],
                                          'comp': pct_comp,
                                          'done': pct_done})

                    if job.should_abort(pct_done):
                        # compression goal (threshold) not met, kill the job and waste no more time...
                        self.log(f'Encoding of {basename} cancelled and skipped due to threshold not met')
                        return True
                    return False

                #
                # Send to agent
                #
                s = socket.socket()

                if self._manager.verbose:
                    self.log(f"connect to '{self.props.ip}'")

                s.connect((self.props.ip, 9567))
                inputsize = os.path.getsize(in_path)
                tmpdir = self.props.working_dir
                cmd_str = "$".join(cmd)
                hello = f"HELLO|{inputsize}|{tmpdir}|{basename}|{cmd_str}"
                if self._manager.verbose:
                    self.log("handshaking")
                s.send(bytes(hello.encode()))
                rsp = s.recv(1024).decode()
                if rsp != hello:
                    self.log("Received unexpected response from agent: " + rsp)
                    continue
                # send the file
                self.log(f"sending {in_path}")
                with open(in_path, "rb") as f:
                    while True:
                        buf = f.read(1_000_000)
                        s.send(buf)
                        if len(buf) < 1_000_000:
                            break

                job_start = datetime.datetime.now()
                finished, stats = self.ffmpeg.monitor_agent_ffmpeg(s, log_callback, self.ffmpeg.monitor_agent)
                job_stop = datetime.datetime.now()

                try:
                    if finished:
                        parts = stats.split(r"|")
                        if parts[0] == "DONE":
                            s.send(bytes("ACK!".encode()))
                            tag, exitcode, sent_filesize = parts
                            filesize = int(sent_filesize)
                            tmp_file = in_path + ".tmp"
                            if self._manager.verbose:
                                self.log(f"receiving results ({filesize} bytes)")

                            with open(tmp_file, "wb") as out:
                                while filesize > 0:
                                    blk = s.recv(1_000_000)
                                    out.write(blk)
                                    filesize -= len(blk)

                            if not dtt.keep_source:
                                os.unlink(in_path)
                                os.rename(tmp_file, in_path)
                            self.log(crayons.green(f'Finished {in_path}'))
                        elif parts[0] == "ERR":
                            self.log(f"Agent returned process error code '{parts[1]}'")
                        else:
                            self.log(f"Unknown process code from agent: '{parts[0]}'")
                        self.complete(in_path, (job_stop - job_start).seconds)

                except KeyboardInterrupt:
                    s.send(bytes("STOP".encode()))

            except Exception as ex:
                self.log(ex)
            finally:
                self.queue.task_done()

    def host_ok(self):
        s = socket.socket()
        s.connect((self.props.ip, 9567))
        s.send(bytes("PING".encode()))
        s.settimeout(5)
        try:
            results = s.recv(4)
            return results == "PONG"
        except Exception:
            return False


class StreamingManagedHost(ManagedHost):
    """Implementation of a streaming host worker thread"""

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue, cluster):
        super().__init__(hostname, props, queue, cluster)

    #
    # initiate tests through here to avoid a new thread
    #
    def testrun(self):
        self.go()

    #
    # normal threaded entry point
    #
    def run(self):
        if self.host_ok():
            self.go()

    def go(self):

        ssh_cmd = [self._manager.ssh, self.props.user + '@' + self.props.ip]

        #
        # Keep pulling items from the queue until done. Other threads will be pulling from the same queue
        # if multiple hosts configured on the same cluster.
        #
        while not self.queue.empty():
            try:
                job: EncodeJob = self.queue.get()
                in_path = job.in_path

                #
                # Convert escaped spaces back to normal. Typical for bash to escape spaces and special characters
                # in filenames.
                #
                in_path = in_path.replace('\\ ', ' ')

                #
                # calculate full input and output paths
                #
                remote_working_dir = self.props.working_dir
                remote_in_path = os.path.join(remote_working_dir, os.path.basename(in_path))
                remote_out_path = os.path.join(remote_working_dir, os.path.basename(in_path) + '.tmp')

                #
                # build remote commandline
                #
                video_options = self.video_cli.split(" ")
                stream_map = []
                if job.media_info.is_multistream() and self._manager.config.automap:
                    stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                                                         job.media_info.subtitle)

                cmd = ['-y', *job.template.input_options_list(), '-i', self.converted_path(remote_in_path),
                       *video_options,
                       *job.template.output_options_list(self._manager.config), *stream_map,
                       self.converted_path(remote_out_path)]
                cli = [*ssh_cmd, *cmd]

                #
                # display useful information
                #
                self.lock.acquire()  # used to synchronize threads so multiple threads don't create a jumble of output
                try:
                    print('-' * 40)
                    print(f'Host     : {self.hostname} (streaming)')
                    print('Filename : ' + crayons.green(os.path.basename(remote_in_path)))
                    print(f'Directive: {job.template.name()}')
                    print('ssh      : ' + ' '.join(cli) + '\n')
                finally:
                    self.lock.release()

                if dtt.dry_run:
                    continue

                #
                # Copy source file to remote
                #
                target_dir = remote_working_dir
                if self.props.is_windows():
                    # trick to make scp work on the Windows side
                    target_dir = '/' + remote_working_dir

                scp = ['scp', in_path, self.props.user + '@' + self.props.ip + ':' + target_dir]
                self.log(' '.join(scp))

                code, output = run(scp)
                if code != 0:
                    self.log(crayons.red('Unknown error copying source to remote - media skipped'))
                    if self._manager.verbose:
                        self.log(output)
                    continue

                basename = os.path.basename(job.in_path)

                def log_callback(stats):
                    pct_done, pct_comp = calculate_progress(job.media_info, stats)
                    dtt.status_queue.put({'host': self.hostname,
                                          'file': basename,
                                          'speed': stats['speed'],
                                          'comp': pct_comp,
                                          'done': pct_done})
                    if job.should_abort(pct_done):
                        # compression goal (threshold) not met, kill the job and waste no more time...
                        self.log(f'Encoding of {basename} cancelled and skipped due to threshold not met')
                        return True
                    return False

                #
                # Start remote
                #
                job_start = datetime.datetime.now()
                code = self.ffmpeg.run_remote(self._manager.ssh, self.props.user, self.props.ip, cmd, log_callback)
                job_stop = datetime.datetime.now()

                #
                # copy results back to local
                #
                retrieved_copy_name = os.path.join(gettempdir(), os.path.basename(remote_out_path))
                cmd = ['scp', self.props.user + '@' + self.props.ip + ':' + remote_out_path, retrieved_copy_name]
                self.log(' '.join(cmd))

                code, output = run(cmd)

                #
                # process completed, check results and finish
                #
                if code is None:
                    # was vetoed by threshold checker, clean up
                    self.complete(in_path, (job_stop - job_start).seconds)
                    os.remove(retrieved_copy_name)
                    continue

                if code == 0:
                    if not filter_threshold(job.template, in_path, retrieved_copy_name):
                        self.log(
                            f'Encoding file {in_path} did not meet minimum savings threshold, skipped')
                        self.complete(in_path, (job_stop - job_start).seconds)
                        os.remove(retrieved_copy_name)
                        continue
                    self.complete(in_path, (job_stop - job_start).seconds)

                    if not dtt.keep_source:
                        os.rename(retrieved_copy_name, retrieved_copy_name[0:-4])
                        retrieved_copy_name = retrieved_copy_name[0:-4]
                        if verbose:
                            self.log(f'moving media to {in_path}')
                        shutil.move(retrieved_copy_name, in_path)
                    self.log(crayons.green(f'Finished {in_path}'))
                elif code is not None:
                    self.log(crayons.red(f'error during remote transcode of {in_path}'))
                    self.log(f' Did not complete normally: {self.ffmpeg.last_command}')
                    self.log(f'Output can be found in {self.ffmpeg.log_path}')

                if self.props.is_windows():
                    remote_out_path = remote_out_path.replace("/", "\\")
                    remote_in_path = remote_in_path.replace("/", "\\")
                    if get_local_os_type() == "linux":
                        remote_out_path = remote_out_path.replace(r"\\", "\\")
                        remote_in_path = remote_in_path.replace(r"\\", "\\")
                    self.run_process([*ssh_cmd, f'del "{remote_out_path}"'])
                else:
                    self.run_process([*ssh_cmd, f'"rm {remote_out_path}"'])

            finally:
                self.queue.task_done()


class MountedManagedHost(ManagedHost):
    """Implementation of a mounted host worker thread"""

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue, cluster):
        super().__init__(hostname, props, queue, cluster)

    #
    # initiate tests through here to avoid a new thread
    #
    def testrun(self):
        self.go()

    #
    # normal threaded entry point
    #
    def run(self):
        if self.host_ok():
            self.go()

    def go(self):

        while not self.queue.empty():
            try:
                job: EncodeJob = self.queue.get()
                in_path = job.in_path

                #
                # calculate paths
                #
                out_path = in_path[0:in_path.rfind('.')] + job.template.extension() + '.tmp'
                remote_in_path = in_path
                remote_out_path = out_path
                if self.props.has_path_subst:
                    #
                    # fix the input path to match what the remote machine expects
                    #
                    remote_in_path, remote_out_path = self.props.substitute_paths(in_path, out_path)

                #
                # build command line
                #
                video_options = self.video_cli.split(" ")

                remote_in_path = self.converted_path(remote_in_path)
                remote_out_path = self.converted_path(remote_out_path)

                stream_map = []
                if job.media_info.is_multistream() and self._manager.config.automap:
                    stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                                                         job.media_info.subtitle)
                cmd = ['-y', *job.template.input_options_list(), '-i', f'"{remote_in_path}"',
                       *video_options,
                       *job.template.output_options_list(self._manager.config), *stream_map,
                       f'"{remote_out_path}"']

                #
                # display useful information
                #
                self.lock.acquire()
                try:
                    print('-' * 40)
                    print(f'Host     : {self.hostname} (mounted)')
                    print('Filename : ' + crayons.green(os.path.basename(remote_in_path)))

                    print(f'Directive: {job.template.name()}')
                    print('ssh      : ' + ' '.join(cmd) + '\n')
                finally:
                    self.lock.release()

                if dtt.dry_run:
                    continue

                basename = os.path.basename(job.in_path)

                def log_callback(stats):
                    pct_done, pct_comp = calculate_progress(job.media_info, stats)
                    dtt.status_queue.put({'host': self.hostname,
                                          'file': basename,
                                          'speed': stats['speed'],
                                          'comp': pct_comp,
                                          'done': pct_done})

                    if job.should_abort(pct_done):
                        # compression goal (threshold) not met, kill the job and waste no more time...
                        self.log(f'Encoding of {basename} cancelled and skipped due to threshold not met')
                        return True
                    return False

                #
                # Start remote
                #
                job_start = datetime.datetime.now()
                code = self.ffmpeg.run_remote(self._manager.ssh, self.props.user, self.props.ip, cmd, log_callback)
                job_stop = datetime.datetime.now()

                #
                # process completed, check results and finish
                #
                if code is None:
                    # was vetoed by threshold checker, clean up
                    self.complete(in_path, (job_stop - job_start).seconds)
                    os.remove(out_path)
                    continue

                if code == 0:
                    if not filter_threshold(job.template, in_path, out_path):
                        self.log(
                            f'Encoding file {in_path} did not meet minimum savings threshold, skipped')
                        self.complete(in_path, (job_stop - job_start).seconds)
                        os.remove(out_path)
                        continue

                    if not dtt.keep_source:
                        if verbose:
                            self.log('removing ' + in_path)
                        os.remove(in_path)
                        if verbose:
                            self.log('renaming ' + out_path)
                        os.rename(out_path, out_path[0:-4])
                        self.complete(in_path, (job_stop - job_start).seconds)
                    self.log(crayons.green(f'Finished {job.in_path}'))
                elif code is not None:
                    self.log(f'Did not complete normally: {self.ffmpeg.last_command}')
                    self.log(f'Output can be found in {self.ffmpeg.log_path}')
                    try:
                        os.remove(out_path)
                    except:
                        pass

            except Exception as ex:
                self.log(ex)
            finally:
                self.queue.task_done()


class LocalHost(ManagedHost):
    """Implementation of a worker thread when the local machine is in the same cluster.
    Pretty much the same as the LocalHost class but without multiple dedicated queues"""

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue, cluster):
        super().__init__(hostname, props, queue, cluster)

    #
    # initiate tests through here to avoid a new thread
    #
    def testrun(self):
        self.go()

    #
    # normal threaded entry point
    #
    def run(self):
        self.go()

    def go(self):

        while not self.queue.empty():
            try:
                job: EncodeJob = self.queue.get()
                in_path = job.in_path

                #
                # calculate paths
                #
                out_path = in_path[0:in_path.rfind('.')] + job.template.extension() + '.tmp'

                #
                # build command line
                #
                remote_in_path = self.converted_path(in_path)
                remote_out_path = self.converted_path(out_path)

                video_options = self.video_cli.split(" ")

                stream_map = []
                if job.media_info.is_multistream() and self._manager.config.automap:
                    stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                                                         job.media_info.subtitle)
                cli = ['-y', *job.template.input_options_list(), '-i', remote_in_path,
                       *video_options,
                       *job.template.output_options_list(self._manager.config), *stream_map,
                       remote_out_path]

                #
                # display useful information
                #
                self.lock.acquire()  # used to synchronize threads so multiple threads don't create a jumble of output
                try:
                    print('-' * 40)
                    print(f'Host     : {self.hostname} (local)')
                    print('Filename : ' + crayons.green(os.path.basename(remote_in_path)))
                    print(f'Directive: {job.template.name()}')
                    print('ffmpeg   : ' + ' '.join(cli) + '\n')
                finally:
                    self.lock.release()

                if dtt.dry_run:
                    continue

                basename = os.path.basename(job.in_path)

                def log_callback(stats):
                    pct_done, pct_comp = calculate_progress(job.media_info, stats)
                    dtt.status_queue.put({'host': 'local',
                                          'file': basename,
                                          'speed': stats['speed'],
                                          'comp': pct_comp,
                                          'done': pct_done})

                    if job.should_abort(pct_done):
                        # compression goal (threshold) not met, kill the job and waste no more time...
                        self.log(f'Encoding of {basename} cancelled and skipped due to threshold not met')
                        return True
                    return False

                #
                # Start process
                #
                job_start = datetime.datetime.now()
                code = self.ffmpeg.run(cli, log_callback)
                job_stop = datetime.datetime.now()

                #
                # process completed, check results and finish
                #
                if code is None:
                    # was vetoed by threshold checker, clean up
                    self.complete(in_path, (job_stop - job_start).seconds)
                    os.remove(out_path)
                    continue

                if code == 0:
                    if not filter_threshold(job.template, in_path, out_path):
                        self.log(
                            f'Encoding file {in_path} did not meet minimum savings threshold, skipped')
                        self.complete(in_path, (job_stop - job_start).seconds)
                        os.remove(out_path)
                        continue

                    if not dtt.keep_source:
                        if verbose:
                            self.log('removing ' + in_path)
                        os.remove(in_path)
                        if verbose:
                            self.log('renaming ' + out_path)
                        os.rename(out_path, out_path[0:-4])
                        self.complete(in_path, (job_stop - job_start).seconds)
                    self.log(crayons.green(f'Finished {job.in_path}'))
                elif code is not None:
                    self.log(f' Did not complete normally: {self.ffmpeg.last_command}')
                    self.log(f'Output can be found in {self.ffmpeg.log_path}')
                    try:
                        os.remove(out_path)
                    except:
                        pass

            except Exception as ex:
                self.log(ex)
            finally:
                self.queue.task_done()


class Cluster(Thread):
    """Thread to create host threads and wait for their completion."""

    terminal_lock: Lock = Lock()  # class-level

    def __init__(self, config: ConfigFile, ssh: str):
        """
        :param config:      The full configuration object
        :param ssh:         Path to local ssh
        """
        super().__init__(daemon=True)
        self.queues: Dict[str, Queue] = dict()
        self.ssh = ssh
        self.hosts: List[ManagedHost] = list()
        self.config = config
        self.verbose = verbose
        self.ffmpeg = FFmpeg(config.ffmpeg_path)
        self.lock = Cluster.terminal_lock
        self.completed: List = list()

        for host, props in config.hosts.items():
            host_props = RemoteHostProperties(host, props)
            if not host_props.is_enabled:
                continue
            host_type = host_props.host_type

            #
            # each host gets a queue for each quality type, whether it is used or not
            #
            host_engines: Dict = host_props.engines
            if len(host_engines) == 0:
                print(f"No engine(s) defined for host {host} - skipping")
                continue

            for host_engine_name in host_engines:
                engine = self.config.engine(host_engine_name)
                if not engine:
                    print(f"Engine {host_engine_name} not found for host {host} - skipping")
                    continue
                eng_qualities = engine.qualities()
                for qname, cli in eng_qualities.items():
                    if qname not in self.queues:
                        self.queues[qname] = Queue()

                        _h = None
                        if host_type == 'local':
                            _h = LocalHost(host, host_props, self.queues[qname], self)
                            if not _h.validate_settings():
                                sys.exit(1)
                            _h.video_cli = cli
                            self.hosts.append(_h)

                        elif host_type == 'mounted':
                            _h = MountedManagedHost(host, host_props, self.queues[qname], self)
                            if _h.host_ok():
                                if not _h.validate_settings():
                                    sys.exit(1)
                                _h.video_cli = cli
                                self.hosts.append(_h)
                            else:
                                print(f"Host {host} not available - skipping")
                                continue

                        elif host_type == 'streaming':
                            _h = StreamingManagedHost(host, host_props, self.queues[qname], self)
                            if _h.host_ok():
                                if not _h.validate_settings():
                                    sys.exit(1)
                                _h.video_cli = cli
                                self.hosts.append(_h)
                            else:
                                print(f"Host {host} not available - skipping")
                                continue

                        elif host_type == 'agent':
                            _h = AgentManagedHost(host, host_props, self.queues[qname], self)
                            if _h.host_ok():
                                if not _h.validate_settings():
                                    sys.exit(1)
                                _h.video_cli = cli
                                self.hosts.append(_h)
                            else:
                                print(f"Host {host} not available - skipping")
                                continue
                        else:
                            print(crayons.red(f'Unknown cluster host type "{host_type}" - skipping'))

    def enqueue(self, file, template_name: str):
        """Add a media file to this cluster queue.
           This is different from in local mode in that we only care about handling skips here.
           The profile will be selected once a host is assigned to the work
        """
        if template_name is None:
            print(f"No template specified")
            return None, None
        if template_name not in self.config.templates:
            print(f"Template {template_name} not found")
            return None, None

        path = os.path.abspath(file)  # convert to full path so that rule filtering can work
        if dtt.verbose:
            print('matching ' + path)

        media_info = self.ffmpeg.fetch_details(path)

        if media_info is None:
            print(crayons.red(f'File not found: {path}'))
            return None, None
        if media_info.valid:
            if dtt.verbose:
                print(str(media_info))

            template = self.config.templates[template_name]

            video_quality = template.quality()
            if video_quality not in self.queues:
                print(f"Cannot match quality '{video_quality}' to any related host engines. Make sure there is at least one host with an engine that supports this quality.")
                sys.exit(1)
            job = EncodeJob(file, media_info, template)
            self.queues[video_quality].put(job)
            return video_quality, job
        return None, None

    def testrun(self):
        for host in self.hosts:
            host.testrun()

    def run(self):
        """Start all host threads and wait until queue is drained"""

        if len(self.hosts) == 0:
            print(f'No hosts available in cluster "{self.name}"')
            return

        for host in self.hosts:
            host.start()

        # all hosts running, wait for them to finish
        for host in self.hosts:
            host.join()
            self.completed.extend(host.completed)

    def terminate(self):
        for host in self.hosts:
            host.terminate()


def manage_cluster(files, config: ConfigFile, testing=False) -> List:
    """Main entry point for setup and execution of all jobs

        There is one thread for the cluster that manages multiple hosts, each having their own thread.
    """
    completed = list()

    if not config.hosts:
        print('Error: no cluster defined')
        return completed

    cluster = Cluster(config, config.ssh_path)

    for item in files:
        filepath, template_name = item
        cluster.enqueue(filepath, template_name)

    #
    # Start cluster, which will start hosts too
    #
    if testing:
        cluster.testrun()
    else:
        cluster.start()

    def sig_handler(signal, frame):
        if cluster.is_alive():
            cluster.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)

    if not testing:

        busy = True
        while busy:
            try:
                report = dtt.status_queue.get(block=True, timeout=2)
                host = report['host']
                basename = report['file']
                speed = report['speed']
                comp = report['comp']
                done = report['done']
                print(f'{host:20}|{basename}: speed: {speed}x, comp: {comp}%, done: {done:3}%')
                sys.stdout.flush()
                dtt.status_queue.task_done()
            except Empty:
                busy = False
                if cluster.is_alive():
                    busy = True

        #
        # wait for each cluster thread to complete
        #
    return completed
