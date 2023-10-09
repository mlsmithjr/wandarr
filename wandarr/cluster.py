"""
    Cluster support
"""
import os
import signal
import sys
from queue import Queue
import queue
from threading import Thread, Lock
from typing import Dict, List

import wandarr
from wandarr import verbose
from wandarr.agenthost import AgentManagedHost
from wandarr.base import ManagedHost, RemoteHostProperties, EncodeJob
from wandarr.config import ConfigFile
from wandarr.ffmpeg import FFmpeg
from wandarr.localhost import LocalHost
from wandarr.mountedhost import MountedManagedHost
from wandarr.streaminghost import StreamingManagedHost


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

        down_hosts = []
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

                    _h = None
                    if host_type == 'local':
                        _h = LocalHost(host, host_props, self.queues[qname], self)
                        if not _h.validate_settings():
                            sys.exit(1)
                        _h.video_cli = cli
                        _h.qname = qname
                        self.hosts.append(_h)

                    elif host_type == 'mounted':
                        _h = MountedManagedHost(host, host_props, self.queues[qname], self)
                        if _h.host_ok():
                            if not _h.validate_settings():
                                sys.exit(1)
                            _h.video_cli = cli
                            _h.qname = qname
                            self.hosts.append(_h)
                        else:
                            down_hosts.append(host)
                            continue

                    elif host_type == 'streaming':
                        _h = StreamingManagedHost(host, host_props, self.queues[qname], self)
                        if _h.host_ok():
                            if not _h.validate_settings():
                                sys.exit(1)
                            _h.video_cli = cli
                            _h.qname = qname
                            self.hosts.append(_h)
                        else:
#                            print(f"Host {host} not available - skipping")
                            down_hosts.append(host)
                            continue

                    elif host_type == 'agent':
                        _h = AgentManagedHost(host, host_props, self.queues[qname], self)
                        if _h.host_ok():
                            if not _h.validate_settings():
                                sys.exit(1)
                            _h.video_cli = cli
                            _h.qname = qname
                            self.hosts.append(_h)
                        else:
#                            print(f"Host {host} not available - skipping")
                            down_hosts.append(host)
                            continue
                    else:
                        print(f'Unknown cluster host type "{host_type}" - skipping')

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
        if wandarr.verbose:
            print('matching ' + path)

        media_info = self.ffmpeg.fetch_details(path)

        if media_info is None:
            print(f'File not found: {path}')
            return None, None
        if media_info.valid:
            if wandarr.verbose:
                print(str(media_info))

            if wandarr.show_info:
                media_info.show_info()

            template = self.config.templates[template_name]

            video_quality = template.video_select()
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
            if wandarr.verbose:
                print(f"Starting {host.name} thread with queue {host.qname}")
            host.start()

        # all hosts running, wait for them to finish
        for host in self.hosts:
            host.join()
            self.completed.extend(host.completed)

    def terminate(self):
        for host in self.hosts:
            host.terminate()


def manage_cluster(files, config: ConfigFile, template_name: str, testing=False) -> List:
    """Main entry point for setup and execution of all jobs

        There is one thread for the cluster that manages multiple hosts, each having their own thread.
    """
    completed = list()

    if config.rich():
        from rich.console import Console
        wandarr.console = Console()
        wandarr.console.clear()

    if not config.hosts:
        print('Error: no cluster defined')
        return completed

    cluster = Cluster(config, config.ssh_path)

    for item in files:
        cluster.enqueue(item, template_name)

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
        os.system("stty sane")
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)

    if not testing:

        if config.rich() and not wandarr.verbose:
            from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
            from rich import rule

            progress = Progress(
                TextColumn("{task.fields[host]}"),
                TextColumn("{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
    #            *Progress.get_default_columns(),
                TextColumn("Comp={task.fields[comp]}"),
                TextColumn("Speed={task.fields[speed]}"),
                TextColumn("{task.fields[status]}"),
                console = wandarr.console
            )

            wandarr.console.print()
            rule.Rule(title="Encoding")

            with progress:
                tasks = {}

                busy = True
                while busy:
                    try:
                        report = wandarr.status_queue.get(block=True, timeout=2)
                        host = "[bold]" + report['host'] + "[/bold]"
                        basename = report['file']
                        if basename not in tasks:
                            tasks[basename] = progress.add_task(f"{basename}", total=100, host = host, comp = 0, speed = 0, status = '')

                        taskid = tasks[basename]
                        # add an emoji to call attention to the skipped job
                        if "status" in report and "Skipped" in report["status"]:
                            report["status"] = ":stop_sign: " + report["status"]
                        # if done > 99 and not report.get("status"):
                        #     report["status"] = "Complete"
    #                    progress.update(taskid, completed = done, speed = speed, comp = comp, status = report.get("status", ""))
                        progress.update(taskid, **report)
                        wandarr.status_queue.task_done()
                    except queue.Empty as e:
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

                    print(f'{host:20}|{basename}: speed: {speed or "?"}x, comp: {comp or "?"}%, done: {done or 0:3}%, status: {status or ""}')

#                    print(f'{host:20}|{basename}: speed: {speed}x, comp: {comp}%, done: {done:3}%, status: {status}')
                    sys.stdout.flush()
                    wandarr.status_queue.task_done()
                except queue.Empty as e:
                    busy = False
                    if cluster.is_alive():
                        busy = True
        #
        # wait for each cluster thread to complete
        #
    return completed
