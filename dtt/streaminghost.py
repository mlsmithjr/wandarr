import os
import datetime
import shutil
from queue import Queue
from tempfile import gettempdir

import dtt
from dtt.base import ManagedHost, RemoteHostProperties, EncodeJob
from dtt.utils import calculate_progress, filter_threshold, run, get_local_os_type


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

                stream_map = super().map_streams(job, self._manager.config)
                if not stream_map:
                    continue
                # stream_map = []
                # if job.media_info.is_multistream() and self._manager.config.automap:
                #     stream_map = job.template.stream_map(job.media_info.stream, job.media_info.audio,
                #                                          job.media_info.subtitle)
                #     if not stream_map:
                #         continue            # require at least 1 audio track
                cmd = ['-y', *job.template.input_options_list(), '-i', self.converted_path(remote_in_path),
                       *video_options,
                       *job.template.output_options_list(self._manager.config), *stream_map,
                       self.converted_path(remote_out_path)]
                cli = [*ssh_cmd, *cmd]

                if dtt.dry_run:
                    #
                    # display useful information
                    #
                    self.lock.acquire()  # used to synchronize threads so multiple threads don't create a jumble of output
                    try:
                        print('-' * 40)
                        print(f'Host     : {self.hostname} (streaming)')
                        print('Filename : ' + os.path.basename(remote_in_path))
                        print(f'Template : {job.template.name()}')
                        print('ssh      : ' + ' '.join(cli) + '\n')
                    finally:
                        self.lock.release()
                    continue

                basename = os.path.basename(job.in_path)

                dtt.status_queue.put({'host': 'local',
                                      'file': basename,
                                      'speed': '0x',
                                      'comp': '0%',
                                      'completed': 0,
                                      'status': 'Copying'})
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
                    self.log('Unknown error copying source to remote - media skipped', style="magenta")
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
                                          'completed': pct_done})
                    if job.should_abort(pct_done):
                        # compression goal (threshold) not met, kill the job and waste no more time...
#                        self.log(f'Encoding of {basename} cancelled and skipped due to threshold not met')
                        dtt.status_queue.put({'host': 'local',
                                              'file': basename,
                                              'speed': f"{stats['speed']}x",
                                              'comp': f"{pct_comp}%",
                                              'completed': 100,
                                              'status': "Skipped (threshold)"})
                        return True
                    return False

                #
                # Start remote
                #
                dtt.status_queue.put({'host': self.hostname,
                                      'file': basename,
                                      'completed': 0,
                                      'status': 'Running'})
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
#                        self.log(
#                            f'Encoding file {in_path} did not meet minimum savings threshold, skipped')
                        self.complete(in_path, (job_stop - job_start).seconds)
                        os.remove(retrieved_copy_name)
                        continue
                    self.complete(in_path, (job_stop - job_start).seconds)

                    if not dtt.keep_source:
                        os.rename(retrieved_copy_name, retrieved_copy_name[0:-4])
                        retrieved_copy_name = retrieved_copy_name[0:-4]
                        if dtt.verbose:
                            self.log(f'moving media to {in_path}')
                        shutil.move(retrieved_copy_name, in_path)
                    #self.log(f'Finished {in_path}')
                elif code is not None:
                    self.log(f'error during remote transcode of {in_path}', style="magenta")
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
