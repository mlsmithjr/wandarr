import os
import datetime
import traceback
from queue import Queue

import wandarr
from .base import RemoteHostProperties, EncodeJob, ManagedHost
from .utils import filter_threshold


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

                stream_map = super().map_streams(job, self._manager.config)

                # stream_map = []
                # if job.media_info.is_multistream() and self._manager.config.automap:
                #     stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                #                                          job.media_info.subtitle)
                #     if not stream_map:
                #         continue            # require at least 1 audio track
                cli = ['-y', *job.template.input_options_list(), '-i', remote_in_path,
                       *video_options,
                       *job.template.output_options_list(self._manager.config), *stream_map,
                       remote_out_path]

                basename = os.path.basename(job.in_path)

                if super().dump_job_info(job, cli):
                    continue

                wandarr.status_queue.put({'host': self.hostname,
                                      'file': basename,
                                      'completed': 0})
                #
                # Start process
                #
                job_start = datetime.datetime.now()
                code = self.ffmpeg.run(cli, super().callback_wrapper(job))
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
                    wandarr.status_queue.put({'host': self.hostname, 'file': basename, 'completed': 100})
                    if not filter_threshold(job.template, in_path, out_path):
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
#                    self.log(f'Finished {job.in_path}')
                elif code is not None:
                    self.log(f' Did not complete normally: {self.ffmpeg.last_command}')
                    self.log(f'Output can be found in {self.ffmpeg.log_path}')
                    try:
                        os.remove(out_path)
                    except:
                        pass

            except Exception as ex:
                print(traceback.format_exc())
            finally:
                self.queue.task_done()
