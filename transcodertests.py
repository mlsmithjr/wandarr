
import unittest
import os
from typing import Dict
from unittest import mock

from dtt.cluster import RemoteHostProperties, Cluster, StreamingManagedHost
from dtt.config import ConfigFile
from dtt.ffmpeg import status_re, FFmpeg
from dtt.media import MediaInfo
from dtt.template import Template
from dtt.utils import files_from_file, get_local_os_type, calculate_progress, dump_stats, is_exceeded_threshold


class TranscoderTests(unittest.TestCase):

    @staticmethod
    def make_media(path, vcodec, res_width, res_height, runtime, source_size, fps, colorspace,
                   audio, subtitle) -> MediaInfo:
        info = {
            'path': path,
            'vcodec': vcodec,
            'stream': 0,
            'res_width': res_width,
            'res_height': res_height,
            'runtime': runtime,
            'filesize_mb': source_size,
            'fps': fps,
            'colorspace': colorspace,
            'audio': audio,
            'subtitle': subtitle
        }
        return MediaInfo(info)

    def test_progress(self):
        info = TranscoderTests.make_media(None, None, None, 1080, 90 * 60, 2300, 25, None, [], [])
        stats = {'size': 1225360000, 'time': 50 * 60}
        done, comp = calculate_progress(info, stats)
        self.assertEqual(done, 55, 'Expected 55% done')
        self.assertEqual(comp, 6, 'Expected 6% compression')

    def test_ffmpeg_status_regex(self):
        sample = 'frame=  307 fps= 86 q=-0.0 size=    3481kB time=00:00:13.03 bitrate=2187.9kbits/s speed=3.67x   \n'
        match = status_re.match(sample)
        self.assertIsNotNone(match, 'no ffmpeg status match')
        self.assertTrue(len(match.groups()) == 5, 'Expected 5 matches')

    def test_loadconfig(self):
        config = ConfigFile('config-samples/transcode.yml')
        self.assertIsNotNone(config.settings, 'Config object not loaded')
        self.assertIsNotNone(config.hosts, 'Expected host definitions')
        self.assertIsNotNone(config.templates, 'Expected template definitions')

    def test_mediainfo(self):
        with open('tests/ffmpeg.out', 'r') as ff:
            info = MediaInfo.parse_ffmpeg_details('/dev/null', ff.read())
            self.assertIsNotNone(info)
            self.assertEqual(info.vcodec, 'h264')
            self.assertEqual(info.res_width, 1280)
            self.assertEqual(info.fps, 23)
            self.assertEqual(info.runtime, (2 * 3600) + (9 * 60) + 38)
            self.assertEqual(info.path, '/dev/null')
            self.assertEqual(info.colorspace, 'yuv420p')

    def test_mediainfo2(self):
        with open('tests/ffmpeg2.out', 'r') as ff:
            info = MediaInfo.parse_ffmpeg_details('/dev/null', ff.read())
            self.assertIsNotNone(info)
            self.assertEqual(info.vcodec, 'h264')
            self.assertEqual(info.res_width, 1920)
            self.assertEqual(info.fps, 24)
            self.assertEqual(info.runtime, (52 * 60) + 49)
            self.assertEqual(info.path, '/dev/null')
            self.assertEqual(info.colorspace, 'yuv420p')

    def test_mediainfo3(self):
        with open('tests/ffmpeg3.out', 'r') as ff:
            info = MediaInfo.parse_ffmpeg_details('/dev/null', ff.read())
            self.assertIsNotNone(info)
            self.assertEqual(info.vcodec, 'hevc')
            self.assertEqual(info.res_width, 3840)
            self.assertEqual(info.fps, 23)
            self.assertEqual(info.runtime, (2 * 3600) + (5 * 60) + 53)
            self.assertEqual(info.path, '/dev/null')
            self.assertEqual(info.colorspace, 'yuv420p10le')

    def test_loc_os(self):
        self.assertNotEqual(get_local_os_type(), 'unknown', 'Expected other than "unknown" as os type')

    def test_path_substitutions(self):
        config: Dict = self.get_setup()
        props = RemoteHostProperties('m1', config['cluster']['m1'])
        intest, outtest = props.substitute_paths('/volume2/test.in', '/volume2/test.out')
        self.assertEqual(intest, '/media/test.in', 'Path substitution failed on input path')
        self.assertEqual(outtest, '/media/test.out', 'Path substitution failed on output path')

    def test_threshold_calculation(self):
        src = 1_234_567_890
        dest = 1_000_000_000
        threshold = 20
        result = is_exceeded_threshold(threshold, src, dest)
        self.assertFalse(result, "Expected threshold to be false")

    @staticmethod
    def get_setup():
        setup = {
            'config': {
                'ffmpeg': '/usr/bin/ffmpeg',
            },
            'cluster': {
                'm1': {
                    'type': 'mounted',
                    'ip': '127.0.0.1',
                    'user': 'mark',
                    'os': 'linux',
                    'ffmpeg': '/usr/bin/ffmpeg',
                    'path-substitutions': [
                        '/v2/ /m2/',
                        '/volume2/ /media/'
                    ],
                    'engines': ['cuda'],
                    'status': 'enabled',
                },
                'workstation': {
                    'os': 'linux',
                    'type': 'local',
                    'ip': '192.168.2.63',
                    'ffmpeg': '/usr/bin/ffmpeg',
                    'engines': ['qsv'],
                    'status': 'enabled',
                },
                'm2': {
                    'type': 'streaming',
                    'ip': '127.0.0.1',
                    'os': 'linux',
                    'user': 'mark',
                    'ffmpeg': '/usr/bin/ffmpeg',
                    'working_dir': '/tmp/pytranscode-remote',
                    'engines': ['qsv'],
                    'status': 'enabled',
                },
                "mbp": {
                    "os": "macos",
                    "type": "local",
                    "working_dir": "/tmp",
                    "ffmpeg": '/opt/homebrew/bin/ffmpeg',
                    "engines": ["qsv"],
                    "status": "enabled"
                },
            },
            "engines": {
                "qsv": {
                    "quality": {
                        "medium": "-c:v hevc_qsv -preset medium -qp 21 -b:v 7000K -f matroska -max_muxing_queue_size 1024",
                    },
                },
                "cuda": {
                    "quality": {
                        "medium": "-c:v hevc_nvenc -cq:v 23 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 7M -profile:v main -maxrate:v 7M -preset medium -pix_fmt yuv420p -f matroska -max_muxing_queue_size 1024",
                    },
                },
            },
            "templates": {
                "tv": {
                    "cli": {
                        "audio-codec": "-c:a copy",
                        "subtitles": "-c:s copy",
                    },
                    "video-quality": "medium",
                    "audio-lang": "eng",
                    "subtitle-lang": "eng",
                    "threshold": "15",
                    "threshold_check": "20",
                    "extension": '.mkv'
                },
            }
        }
        return setup

    def test_stream_map(self):
        setup = ConfigFile(self.get_setup())
        template = setup.templates.get("tv")
        x = template.stream_map("0", [{"lang":"eng","stream":"1"}], [{"lang":"jpn","stream":"2"}])
        self.assertEqual(x, ['-map', '0:0', '-map', '0:1'], "stream mapping failed")

    @mock.patch.object(FFmpeg, 'run_remote')
    @mock.patch('dtt.cluster.filter_threshold')
    @mock.patch('dtt.cluster.os.rename')
    @mock.patch('dtt.cluster.os.remove')
    @mock.patch.object(FFmpeg, 'fetch_details')
    def test_cluster_match(self, mock_ffmpeg_details, mock_os_rename, mock_os_remove,
                            mock_filter_threshold, mock_run_remote):

        setup = ConfigFile(self.get_setup())

        #
        # setup all mocks
        #
        mock_run_remote.return_value = 0
        mock_filter_threshold.return_value = True
        mock_os_rename.return_value = None
        mock_os_remove.return_value = None
        info = TranscoderTests.make_media('/dev/null', 'x264', 1920, 1080, 45 * 60, 3200, 24, None, [], [])
        mock_ffmpeg_details.return_value = info

        #
        # configure the cluster, add the job, and run
        #
        cluster = self.setup_cluster(setup)
        quality, job = cluster.enqueue('/dev/null.mp4', "tv")
        self.assertEqual(quality, 'medium', 'Wrong quality matched')
        self.assertEqual(job.template._name, 'tv', 'Wrong template selected')

        cluster.testrun()
        for host in cluster.hosts:
            if host.hostname == 'm1' and len(host._complete) > 0:
                filename, elapsed = host.completed.pop()
                self.assertEqual('/dev/null.mp4', filename, 'Completed filename missing from assigned host')
                break

    @staticmethod
    def setup_cluster(config) -> Cluster:
        cluster = Cluster(config, config.ssh_path)
        return cluster

    @mock.patch.object(FFmpeg, 'run_remote')
    @mock.patch('dtt.cluster.filter_threshold')
    @mock.patch('dtt.cluster.os.rename')
    @mock.patch('dtt.cluster.os.remove')
    @mock.patch.object(MediaInfo, 'parse_ffmpeg_details')
    @mock.patch('dtt.cluster.run')
    @mock.patch('dtt.cluster.shutil.move')
    @mock.patch.object(FFmpeg, 'fetch_details')
    @mock.patch.object(StreamingManagedHost, 'run_process')
    def test_cluster_streaming_host(self, mock_run_proc, mock_ffmpeg_fetch, mock_move, mock_run, mock_info_parser,
                                    mock_os_rename, mock_os_remove,
                                    mock_filter_threshold, mock_run_remote):

        setup = ConfigFile(self.get_setup())

        #
        # setup all mocks
        #
        mock_run.return_value = 0, 'ok'
        mock_run_remote.return_value = 0
        mock_move.return_value = 0
        mock_filter_threshold.return_value = True
        mock_os_rename.return_value = None
        mock_os_remove.return_value = None
        info = TranscoderTests.make_media('/dev/null', 'x264', 1920, 1080, 110 * 60, 3000, 24, None, [], [])
        mock_info_parser.return_value = info
        mock_ffmpeg_fetch.return_value = info
        #
        # configure the cluster, add the job, and run
        #
        cluster = self.setup_cluster(setup)
        quality, job = cluster.enqueue('/dev/null.mp4', "tv")
        self.assertEqual(quality, 'medium', 'Wrong quality')
        self.assertEqual(job.template._name, 'tv', 'Wrong template')

        cluster.testrun()
        for host in cluster.hosts:
            if host.hostname == 'm2' and len(host._complete) > 0:
                filename, elapsed = host.completed.pop()
                self.assertEqual('/dev/null.mp4', filename,
                                  'Completed filename missing from assigned host')
                break


if __name__ == '__main__':
    unittest.main()
