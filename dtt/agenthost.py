import datetime
import os
from queue import Queue
import socket

import dtt
from dtt.agent import Agent
from dtt.base import ManagedHost, RemoteHostProperties, EncodeJob
from dtt.utils import calculate_progress


class AgentManagedHost(ManagedHost):
    """Implementation of a agent host worker thread"""

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue, cluster):
        super().__init__(hostname, props, queue, cluster)

    #
    # override the standard ssh-based host_ok for agent verification
    #
    def host_ok(self):
        s = socket.socket()
        try:
            s.connect((self.props.ip, Agent.PORT))
            if self._manager.verbose:
                self.log(f"checking if remote agent at {self.props.ip} is up")
            s.send(bytes("PING".encode()))
            s.settimeout(5)
            rsp = s.recv(4).decode()
            return rsp == "PONG"
        except Exception as e:
            print(e)
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

                #
                # build command line
                #
                remote_in_path = in_path

                video_options = self.video_cli.split(" ")
                stream_map = []
                if job.media_info.is_multistream() and self._manager.config.automap:
                    stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                                                         job.media_info.subtitle)
                    if not stream_map:
                        continue            # require at least 1 audio track
                cmd = [self.props.ffmpeg_path, '-y', *job.template.input_options_list(), '-i', '{FILENAME}',
                       *video_options,
                       *job.template.output_options_list(self._manager.config), *stream_map]


                if dtt.dry_run:
                    #
                    # display useful information
                    #
                    self.lock.acquire()
                    try:
                        print('-' * 40)
                        print(f'Host     : {self.hostname} (agent)')
                        print('Filename : ' + os.path.basename(remote_in_path))
                        print(f'Directive: {job.template.name()}')
                        print('Command  : ' + ' '.join(cmd) + '\n')
                    finally:
                        self.lock.release()
                    continue

                basename = os.path.basename(job.in_path)

                def log_callback(stats):
                    pct_done, pct_comp = calculate_progress(job.media_info, stats)
                    dtt.status_queue.put({'host': self.hostname,
                                          'file': basename,
                                          'speed': stats['speed'],
                                          'comp': pct_comp,
                                          'completed': pct_done})

                    if job.should_abort(pct_done):
                        # compression goal (threshold) not met, kill the job and waste no more time...
#                        self.log(f'Encoding of {basename} cancelled and skipped due to threshold not met')
                        dtt.status_queue.put({'host': self.hostname,
                                              'file': basename,
                                              'speed': f"{stats['speed']}x",
                                              'comp': f"{pct_comp}%",
                                              'completed': 100,
                                              'status': "Skipped (threshold)"})
                        return True
                    return False

                #
                # Send to agent
                #
                s = socket.socket()
                s.settimeout(5)

                dtt.status_queue.put({'host': self.hostname,
                                      'file': basename,
                                      'completed': 0,
                                      'status': 'Connect'})

                if self._manager.verbose:
                    self.log(f"connect to '{self.props.ip}'", style="info")

                s.connect((self.props.ip, Agent.PORT))
                inputsize = os.path.getsize(in_path)
                tmpdir = self.props.working_dir
                cmd_str = "$".join(cmd)
                hello = f"HELLO|{inputsize}|{tmpdir}|{basename}|{cmd_str}"
                if self._manager.verbose:
                    self.log("handshaking with remote agent", style="info")
                s.send(bytes(hello.encode()))
                rsp = s.recv(1024).decode()
                if rsp != hello:
                    self.log("Received unexpected response from agent: " + rsp, style="magenta'")
                    continue
                # send the file
                dtt.status_queue.put({'host': self.hostname,
                                      'file': basename,
                                      'status': 'Copy'})
#                self.log(f"sending {in_path} to agent")
                with open(in_path, "rb") as f:
                    while True:
                        buf = f.read(1_000_000)
                        s.send(buf)
                        if len(buf) < 1_000_000:
                            break

                dtt.status_queue.put({'host': self.hostname,
                                      'file': basename,
                                      'status': 'Running'})
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
                            dtt.status_queue.put({'host': self.hostname,
                                                  'file': basename,
                                                  'completed': 100,
                                                  'status': 'Retrieving'})

                            if self._manager.verbose:
                                self.log(f"receiving ({filesize} bytes)")

                            with open(tmp_file, "wb") as out:
                                while filesize > 0:
                                    blk = s.recv(1_000_000)
                                    out.write(blk)
                                    filesize -= len(blk)

                            if not dtt.keep_source:
                                os.unlink(in_path)
                                os.rename(tmp_file, in_path)
                                dtt.status_queue.put({'host': self.hostname,
                                                      'file': basename,
                                                      'completed': 100,
                                                      'status': 'Complete'})

#                            self.log(crayons.green(f'Finished {in_path}'))
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
