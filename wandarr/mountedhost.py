import datetime
import os
import traceback
from queue import Queue

import wandarr
from .base import ManagedHost, RemoteHostProperties, EncodeJob
from .utils import filter_threshold


class MountedManagedHost(ManagedHost):
    """Implementation of a mounted host worker thread"""

    def __init__(self, hostname, props: RemoteHostProperties, queue: Queue):
        super().__init__(hostname, props, queue)

        # last modified paths - used for testing
        self.remote_in_path = None
        self.remote_out_path = None

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
                orig_file_size_mb = int(os.path.getsize(in_path) / (1024 * 1024))

                #
                # calculate paths
                #
                out_path = in_path[0:in_path.rfind('.')] + job.template.extension() + '.tmp'
                self.remote_in_path = in_path
                self.remote_out_path = out_path
                if self.props.has_path_subst:
                    #
                    # fix the input path to match what the remote machine expects
                    #
                    self.remote_in_path, self.remote_out_path = self.props.substitute_paths(in_path, out_path)
                    if wandarr.VERBOSE:
                        print(f"substituted {self.remote_in_path} for {in_path}")
                #
                # build command line
                #
                video_options = self.video_cli.split(" ")

                self.remote_in_path = self.converted_path(self.remote_in_path)
                self.remote_out_path = self.converted_path(self.remote_out_path)

                stream_map = super().map_streams(job)

                cmd = ['-stats_period', '2', '-y', *job.template.input_options_list(), '-i', self.remote_in_path,
                       *video_options,
                       *job.template.output_options_list(), *stream_map,
                       self.remote_out_path]

                basename = os.path.basename(job.in_path)

                if super().dump_job_info(job, cmd):
                    continue

                opts_only = [*job.template.input_options_list(), *video_options,
                             *job.template.output_options_list(), *stream_map]
                print(f"{basename} -> ffmpeg {' '.join(opts_only)}")

                wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                          'file': basename,
                                          'completed': 0})
                #
                # Start remote
                #
                job_start = datetime.datetime.now()
                code = self.ffmpeg.run_remote(wandarr.SSH, self.props.user, self.props.ip, cmd,
                                              super().callback_wrapper(job))
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
                        self.complete(in_path, (job_stop - job_start).seconds)
                        os.remove(out_path)
                        continue

                    if not wandarr.KEEP_SOURCE:
                        if wandarr.VERBOSE:
                            self.log('removing ' + in_path)
                        os.remove(in_path)
                        if wandarr.VERBOSE:
                            self.log('renaming ' + out_path)
                        os.rename(out_path, out_path[0:-4])
                        self.complete(in_path, (job_stop - job_start).seconds)

                        new_filesize_mb = int(os.path.getsize(out_path[0:-4]) / (1024 * 1024))
                        wandarr.status_queue.put({'host': f"{self.hostname}/{self.engine_name}",
                                                  'file': basename,
                                                  'completed': 100,
                                                  'status': f'{orig_file_size_mb}mb -> {new_filesize_mb}mb'})
                elif code is not None:
                    self.log(f'Did not complete normally: {self.ffmpeg.last_command}')
                    self.log(f'Output can be found in {self.ffmpeg.log_path}')
                    try:
                        os.remove(out_path)
                    except OSError:
                        pass

            except Exception:
                print(traceback.format_exc())
            finally:
                self.queue.task_done()
