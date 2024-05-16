import datetime
import os
import traceback
from queue import Queue
import socket

import wandarr
from wandarr.agent import Agent
from wandarr.base import ManagedHost, RemoteHostProperties, EncodeJob


class AgentManagedHost(ManagedHost):
    """Implementation of an agent host worker thread"""

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue):
        super().__init__(hostname, props, queue)

        self.remote_in_path = None
        self.remote_out_path = None

    #
    # override the standard ssh-based host_ok for agent verification
    #
    def host_ok(self):
        if not super().ping_test_ok():
            return False

        s = socket.socket()
        s.settimeout(2)
        try:
            s.connect((self.props.ip, Agent.PORT))
            if wandarr.VERBOSE:
                self.log(f"checking if remote agent at {self.props.ip} is up")
            s.send(bytes("PING".encode()))
            s.settimeout(5)
            rsp = s.recv(4).decode()
            return rsp == "PONG"
        except Exception as ex:
            if wandarr.console:
                wandarr.console.print(f":warning: Agent not running on {self.props.ip}")
                wandarr.console.print(str(ex))
            else:
                print(str(ex))
                print(f"Agent not running on {self.props.ip}")
        return False

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

    def handshake(self, s: socket.socket, hello: str) -> bool:
        if wandarr.VERBOSE:
            self.log("handshaking with remote agent", style="info")
        s.send(bytes(hello.encode()))
        rsp = s.recv(1024).decode()
        if rsp.startswith("NAK"):
            self.log(rsp[4:])
            return False
        if rsp != hello:
            self.log("Received unexpected response from agent: " + rsp, style="magenta")
            return False
        return True

    def sendfile(self, s: socket.socket, in_path: str):
        with open(in_path, "rb") as f:
            while True:
                buf = f.read(4096)
                s.send(buf)
                if len(buf) < 4096:
                    break

    def recvfile(self, s: socket.socket, filesize: int, tmp_file: str):
        with open(tmp_file, "wb") as out:
            while filesize > 0:
                blk = s.recv(1_000_000)
                out.write(blk)
                filesize -= len(blk)

    def connect(self, s: socket.socket):
        s.connect((self.props.ip, Agent.PORT))

    def ack(self, s:socket.socket):
        s.send(bytes("ACK!".encode()))

    def go(self):

        while not self.queue.empty():
            try:
                job: EncodeJob = self.queue.get()
                in_path = job.in_path
                orig_file_size_mb = int(os.path.getsize(in_path) / (1024 * 1024))

                #
                # build command line
                #
                video_options = self.video_cli.split(" ")
                stream_map = super().map_streams(job)

                has_sharing = False
                #
                # if path substitutions were given then the host where the agent resides has access to shared file,
                # so map the paths same as mountedhost.
                #
                if self.props.has_path_subst:
                    out_path = in_path[0:in_path.rfind('.')] + job.template.extension() + '.tmp'
                    self.remote_in_path, self.remote_out_path = self.props.substitute_paths(in_path, out_path)
                    if wandarr.VERBOSE:
                        print(f"substituted {self.remote_in_path} for {in_path}")
                    cmd = [self.props.ffmpeg_path, '-stats_period', '2', '-y', *job.template.input_options_list(), '-i', self.remote_in_path,
                           *video_options,
                           *job.template.output_options_list(), *stream_map, self.remote_out_path]
                    has_sharing = True
                else:
                    # no path mapping, so we're sending the file
                    cmd = [self.props.ffmpeg_path, '-stats_period', '2', '-y', *job.template.input_options_list(), '-i', '{FILENAME}',
                           *video_options,
                           *job.template.output_options_list(), *stream_map]

                basename = os.path.basename(job.in_path)

                if super().dump_job_info(job, cmd):
                    continue

                #
                # Send to agent
                #
                s = socket.socket()

                opts_only = [*job.template.input_options_list(), *video_options,
                             *job.template.output_options_list(), *stream_map]
                print(f"{basename} -> ffmpeg {' '.join(opts_only)}")

                wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                          'file': basename,
                                          'completed': 0,
                                          'status': 'Connect'})

                if wandarr.VERBOSE:
                    self.log(f"connect to '{self.props.ip}'", style="info")

                self.connect(s)

                input_size = os.path.getsize(in_path)
                cmd_str = "$".join(cmd)
                if has_sharing:
                    hello = f"HELLOS|{wandarr.__version__}|{self.remote_in_path}|{self.remote_out_path}|{cmd_str}|{'1' if wandarr.KEEP_SOURCE else '0'}"
                else:
                    tmpdir = self.props.working_dir
                    hello = f"HELLO|{wandarr.__version__}|{input_size}|{tmpdir}|{basename}|{cmd_str}"

                if not self.handshake(s, hello):
                    continue

                if not has_sharing:
                    # send the file
                    wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                              'file': basename,
                                              'status': 'Copying...'})

                    self.sendfile(s, in_path)

                wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                          'file': basename,
                                          'status': 'Running'})
                job_start = datetime.datetime.now()
                finished, stats = self.ffmpeg.monitor_agent_ffmpeg(s, super().callback_wrapper(job),
                                                                   self.ffmpeg.monitor_agent)
                job_stop = datetime.datetime.now()

                try:
                    if finished and stats:
                        parts = stats.split(r"|")
                        if parts[0] == "DONE":
                            self.ack(s)

                            if not has_sharing:
                                #
                                # agent will send us the transcoded file
                                #
                                tag, exitcode, sent_filesize = parts
                                filesize = int(sent_filesize)
                                tmp_file = in_path + ".tmp"
                                wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                                          'file': basename,
                                                          'completed': 100,
                                                          'status': 'Retrieving'})

                                if wandarr.VERBOSE:
                                    self.log(f"receiving ({filesize} bytes)")

                                self.recvfile(s, filesize, tmp_file)

                                if not wandarr.KEEP_SOURCE:
                                    os.unlink(in_path)
                                    os.rename(tmp_file, in_path)
                                    new_filesize_mb = int(os.path.getsize(in_path) / (1024 * 1024))

                                    wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                                              'file': basename,
                                                              'completed': 100,
                                                              'status': f'{orig_file_size_mb}mb -> {new_filesize_mb}mb'})
                            else:
                                # agent already put the new file in place on the share
                                new_filesize = parts[2]
                                new_filesize_mb = int(int(new_filesize) / (1024 * 1024))
                                wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                                          'file': basename,
                                                          'completed': 100,
                                                          'status': f'{orig_file_size_mb}mb -> {new_filesize_mb}mb'})

                        elif parts[0] == "ERR":
                            self.log(f"Agent returned process error code '{parts[1]}'")
                        else:
                            self.log(f"Unknown process code from agent: '{parts[0]}'")
                        self.complete(in_path, (job_stop - job_start).seconds)

                except KeyboardInterrupt:
                    s.send(bytes("STOP".encode()))

                s.close()

            except Exception:
                print(traceback.format_exc())
            finally:
                self.queue.task_done()
