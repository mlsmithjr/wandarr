import datetime
import os
import traceback
from queue import Queue

import wandarr
from .base import ManagedHost, RemoteHostProperties, EncodeJob
from .utils import filter_threshold


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
                    if wandarr.verbose:
                        print(f"substituted {remote_in_path} for {in_path}")
                #
                # build command line
                #
                video_options = self.video_cli.split(" ")

                remote_in_path = self.converted_path(remote_in_path)
                remote_out_path = self.converted_path(remote_out_path)

                stream_map = super().map_streams(job, self._manager.config)

                # stream_map = []
                # if job.media_info.is_multistream() and self._manager.config.automap:
                #     stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                #                                          job.media_info.subtitle)
                #     if not stream_map:
                #         continue            # require at least 1 audio track
                cmd = ['-y', *job.template.input_options_list(), '-i', f'"{remote_in_path}"',
                       *video_options,
                       *job.template.output_options_list(self._manager.config), *stream_map,
                       f'"{remote_out_path}"']

                basename = os.path.basename(job.in_path)

                if super().dump_job_info(job, cmd):
                    continue

                wandarr.status_queue.put({'host': self.hostname,
                                      'file': basename,
                                      'completed': 0})
                #
                # Start remote
                #
                job_start = datetime.datetime.now()
                code = self.ffmpeg.run_remote(self._manager.ssh, self.props.user, self.props.ip, cmd,
                                              super().callback_wrapper(job))
                job_stop = datetime.datetime.now()

                #print(f"host {self.hostname} done with code {code}")
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
#                        self.log(
#                            f'Encoding file {in_path} did not meet minimum savings threshold, skipped')
                        self.complete(in_path, (job_stop - job_start).seconds)
                        os.remove(out_path)
                        continue

                    if not wandarr.keep_source:
                        if wandarr.verbose:
                            self.log('removing ' + in_path)
                        os.remove(in_path)
                        if wandarr.verbose:
                            self.log('renaming ' + out_path)
                        os.rename(out_path, out_path[0:-4])
                        self.complete(in_path, (job_stop - job_start).seconds)
                    #self.log(crayons.green(f'Finished {job.in_path}'))
                elif code is not None:
                    self.log(f'Did not complete normally: {self.ffmpeg.last_command}')
                    self.log(f'Output can be found in {self.ffmpeg.log_path}')
                    try:
                        os.remove(out_path)
                    except:
                        pass

            except Exception as ex:
                print(traceback.format_exc())
            finally:
                self.queue.task_done()
