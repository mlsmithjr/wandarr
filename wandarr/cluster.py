"""
    Cluster support
"""
import os
import signal
import sys
from queue import Queue
import queue
from threading import Thread
from typing import Dict, List
from rich.console import Console

import wandarr
from wandarr.agenthost import AgentManagedHost
from wandarr.base import ManagedHost, RemoteHostProperties, EncodeJob
from wandarr.config import ConfigFile
from wandarr.ffmpeg import FFmpeg
from wandarr.localhost import LocalHost
from wandarr.mountedhost import MountedManagedHost
from wandarr.streaminghost import StreamingManagedHost


class Cluster(Thread):
    """Thread to create host threads and wait for their completion."""

    def __init__(self, config: ConfigFile):
        """
        :param config:      The full configuration object
        """
        super().__init__(daemon=True)
        self.queues: Dict[str, Queue] = {}
        self.hosts: List[ManagedHost] = []
        self.config = config
        self.ffmpeg = FFmpeg(config.ffmpeg_path)
        self.completed: List = []

        down_hosts = []
        up_hosts = []
        for host, props in config.hosts.items():
            if host in down_hosts:
                continue
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
                if host in down_hosts:
                    continue
                engine = self.config.engine(host_engine_name)
                if not engine:
                    print(f"Engine {host_engine_name} not found for host {host} - skipping")
                    continue
                eng_qualities = engine.qualities()
                for qname, cli in eng_qualities.items():
                    if host in down_hosts:
                        continue
                    if qname not in self.queues:
                        self.queues[qname] = Queue()

                    match host_type:
                        case "local":
                            if wandarr.VERBOSE:
                                print(f"{host=} {qname=} {host_engine_name=} {cli=}")
                            self._init_host_local(host, host_props, qname, host_engine_name, cli)

                        case "mounted":
                            if wandarr.VERBOSE:
                                print(f"{host=} {qname=} {host_engine_name=} {cli=}")
                            if not self._init_host_mounted(host, host_props, qname, host_engine_name, cli, host not in up_hosts):
                                down_hosts.append(host)
                                continue
                            up_hosts.append(host)

                        case "streaming":
                            if wandarr.VERBOSE:
                                print(f"{host=} {qname=} {host_engine_name=} {cli=}")
                            if not self._init_host_streaming(host, host_props, qname, host_engine_name, cli, host not in up_hosts):
                                down_hosts.append(host)
                                continue
                            up_hosts.append(host)

                        case "agent":
                            if wandarr.VERBOSE:
                                print(f"{host=} {qname=} {host_engine_name=} {cli=}")
                            if not self._init_host_agent(host, host_props, qname, host_engine_name, cli, host not in up_hosts):
                                down_hosts.append(host)
                                continue
                            up_hosts.append(host)

                        case _:
                            print(f'Unknown cluster host type "{host_type}" - skipping')

    def _init_host_local(self, host: str, host_props: RemoteHostProperties, qname: str, engine_name: str, cli: str):
        _h = LocalHost(host, host_props, self.queues[qname])
        if not _h.validate_settings():
            sys.exit(1)
        _h.video_cli = cli
        _h.qname = qname
        _h.engine_name = engine_name
        self.hosts.append(_h)

    def _init_host_mounted(self, host: str, host_props: RemoteHostProperties, qname: str, engine_name: str, cli: str, check_host: bool):
        _h = MountedManagedHost(host, host_props, self.queues[qname])
        if check_host and not _h.host_ok():
            return False

        if not _h.validate_settings():
            sys.exit(1)
        _h.video_cli = cli
        _h.qname = qname
        _h.engine_name = engine_name
        self.hosts.append(_h)
        return True

    def _init_host_streaming(self, host: str, host_props: RemoteHostProperties, qname: str, engine_name: str, cli: str, check_host: bool):
        _h = StreamingManagedHost(host, host_props, self.queues[qname])
        if check_host and not _h.host_ok():
            return False

        if not _h.validate_settings():
            sys.exit(1)
        _h.video_cli = cli
        _h.qname = qname
        _h.engine_name = engine_name
        self.hosts.append(_h)
        return True

    def _init_host_agent(self, host: str, host_props: RemoteHostProperties, qname: str, engine_name: str, cli: str, check_host: bool):
        _h = AgentManagedHost(host, host_props, self.queues[qname])
        if check_host and not _h.host_ok():
            return False

        if not _h.validate_settings():
            sys.exit(1)
        _h.video_cli = cli
        _h.qname = qname
        _h.engine_name = engine_name
        self.hosts.append(_h)
        return True

    def enqueue(self, file, template_name: str, vq_override: str = None):
        """Add a media file to this cluster queue.
           This is different from in local mode in that we only care about handling skips here.
           The profile will be selected once a host is assigned to the work
        """
        if template_name is None:
            print("No template specified")
            return None, None
        if template_name not in self.config.templates:
            print(f"Template {template_name} not found")
            return None, None

        path = os.path.abspath(file)
        if wandarr.VERBOSE:
            print('matching ' + path)

        media_info = self.ffmpeg.fetch_details(path)

        if media_info is None:
            print(f'File not found: {path}')
            return None, None
        if media_info.valid:
            if wandarr.VERBOSE:
                print(str(media_info))

            template = self.config.templates[template_name]
            video_quality = vq_override or template.video_select()
            if not video_quality:
                print(f"Template setting 'video-quality' not set for template {template_name}")
                sys.exit(1)

            if video_quality not in self.queues:
                print((f"Cannot match quality '{video_quality}' to any related host engines. "
                      "Make sure there is at least one host with an engine that supports this quality."))
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
            if wandarr.VERBOSE:
                print(f"Starting {host.name} thread with queue {host.qname}")
            host.start()

        # all hosts running, wait for them to finish
        for host in self.hosts:
            host.join()
            self.completed.extend(host.completed)

    def terminate(self):
        for host in self.hosts:
            host.terminate()


def manage_cluster(files, config: ConfigFile, template_name: str, vq_override: str, testing=False) -> List:
    """Main entry point for setup and execution of all jobs

        There is one thread for the cluster that manages multiple hosts, each having their own thread.
    """
    completed = []

    if config.rich:
        wandarr.console = Console()

    if not config.hosts:
        print('Error: no cluster defined')
        return completed

    # ugh, dirty I know.
    wandarr.SSH = config.ssh_path

    try:
        cluster = Cluster(config)
    except ValueError as ve:
        print("Error initializing: " + str(ve))
        sys.exit(1)

    for item in files:
        cluster.enqueue(item, template_name, vq_override)

    #
    # Start cluster, which will start hosts too
    #
    if testing:
        cluster.testrun()
    else:
        cluster.start()

    def sig_handler(sig, frame):
        if cluster.is_alive():
            cluster.terminate()
        os.system("stty sane")
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)

    if not testing:

        if config.rich and not wandarr.VERBOSE:
            from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

            progress = Progress(
                TextColumn("{task.fields[host]}"),
                TextColumn("{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                TextColumn("Comp={task.fields[comp]}"),
                TextColumn("Speed={task.fields[speed]}"),
                TextColumn("{task.fields[status]}"),
                console=wandarr.console
            )

            wandarr.console.print("\n")

            with progress:
                tasks = {}

                busy = True
                while busy:
                    try:
                        report = wandarr.status_queue.get(block=True, timeout=2)
                        host = "[bold]" + report['host'] + "[/bold]"
                        report['host'] = host
                        basename = report['file']
                        if basename not in tasks:
                            tasks[basename] = progress.add_task(f"{basename}", total=100, host=host,
                                                                comp=0, speed=0, status='')

                        taskid = tasks[basename]
                        # add an emoji to call attention to the skipped job
                        if "status" in report and "Skipped" in report["status"]:
                            report["status"] = ":stop_sign: " + report["status"]
                        progress.update(taskid, **report)
                        wandarr.status_queue.task_done()
                    except queue.Empty:
                        busy = False
                        if cluster.is_alive():
                            busy = True
        else:
            # not using pretty output, revert to terminal blah
            busy = True
            while busy:
                try:
                    report = wandarr.status_queue.get(block=True, timeout=2)
                    host = report['host']
                    basename = report['file']
                    speed = report.get('speed')
                    comp = report.get('comp')
                    done = int(report.get('completed', '0'))
                    report['completed'] = done
                    status = report.get('status')

                    print(f'{host:20}|{basename}: speed: {speed or "?"}, comp: {comp or "?"}, done: {done or 0:3}%, status: {status or "running"}')

#                    print(f'{host:20}|{basename}: speed: {speed}x, comp: {comp}%, done: {done:3}%, status: {status}')
                    sys.stdout.flush()
                    wandarr.status_queue.task_done()
                except queue.Empty:
                    busy = False
                    if cluster.is_alive():
                        busy = True

    return completed
