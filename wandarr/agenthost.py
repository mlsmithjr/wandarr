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

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue, cluster):
        super().__init__(hostname, props, queue, cluster)

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
            if self._manager.VERBOSE:
                self.log(f"checking if remote agent at {self.props.ip} is up")
            s.send(bytes("PING".encode()))
            s.settimeout(5)
            rsp = s.recv(4).decode()
            return rsp == "PONG"
        except Exception:
            if wandarr.console:
                wandarr.console.print(f":warning: Agent not running on {self.props.ip}")
            else:
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
                stream_map = super().map_streams(job, self._manager.config)

                cmd = [self.props.ffmpeg_path, '-y', *job.template.input_options_list(), '-i', '{FILENAME}',
                       *video_options,
                       *job.template.output_options_list(), *stream_map]

                basename = os.path.basename(job.in_path)

                if super().dump_job_info(job, cmd):
                    continue

                #
                # Send to agent
                #
                s = socket.socket()

                wandarr.status_queue.put({'host': self.hostname,
                                          'file': basename,
                                          'completed': 0,
                                          'status': 'Connect'})

                if self._manager.VERBOSE:
                    self.log(f"connect to '{self.props.ip}'", style="info")

                s.connect((self.props.ip, Agent.PORT))
                input_size = os.path.getsize(in_path)
                tmpdir = self.props.working_dir
                cmd_str = "$".join(cmd)
                hello = f"HELLO|{input_size}|{tmpdir}|{basename}|{cmd_str}"
                if self._manager.VERBOSE:
                    self.log("handshaking with remote agent", style="info")
                s.send(bytes(hello.encode()))
                rsp = s.recv(1024).decode()
                if rsp != hello:
                    self.log("Received unexpected response from agent: " + rsp, style="magenta'")
                    continue
                # send the file
                wandarr.status_queue.put({'host': self.hostname,
                                          'file': basename,
                                          'status': 'Copying...'})
                #                self.log(f"sending {in_path} to agent")
                with open(in_path, "rb") as f:
                    while True:
                        buf = f.read(4096)
                        s.send(buf)
                        if len(buf) < 4096:
                            break

                wandarr.status_queue.put({'host': self.hostname,
                                          'file': basename,
                                          'status': 'Running'})
                job_start = datetime.datetime.now()
                finished, stats = self.ffmpeg.monitor_agent_ffmpeg(s, super().callback_wrapper(job),
                                                                   self.ffmpeg.monitor_agent)
                job_stop = datetime.datetime.now()

                try:
                    if finished:
                        parts = stats.split(r"|")
                        if parts[0] == "DONE":
                            s.send(bytes("ACK!".encode()))
                            tag, exitcode, sent_filesize = parts
                            filesize = int(sent_filesize)
                            tmp_file = in_path + ".tmp"
                            wandarr.status_queue.put({'host': self.hostname,
                                                      'file': basename,
                                                      'completed': 100,
                                                      'status': 'Retrieving'})

                            if self._manager.VERBOSE:
                                self.log(f"receiving ({filesize} bytes)")

                            with open(tmp_file, "wb") as out:
                                while filesize > 0:
                                    blk = s.recv(1_000_000)
                                    out.write(blk)
                                    filesize -= len(blk)

                            if not wandarr.KEEP_SOURCE:
                                os.unlink(in_path)
                                os.rename(tmp_file, in_path)
                                new_filesize_mb = int(os.path.getsize(in_path) / (1024 * 1024))

                                wandarr.status_queue.put({'host': self.hostname,
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

            except Exception:
                print(traceback.format_exc())
            finally:
                self.queue.task_done()
