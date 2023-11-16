from queue import Queue
from threading import Thread
from unittest.mock import patch

import pytest

from wandarr.agenthost import AgentManagedHost
from wandarr.base import RemoteHostProperties, EncodeJob
from wandarr.localhost import LocalHost
from wandarr.mountedhost import MountedManagedHost
from wandarr.streaminghost import StreamingManagedHost
from .fixtures import media_info, basic_config

CONFIG_PATH = "tests/basic_config.yml"


@pytest.mark.parametrize("ffmpeg_return", [0, -1])
@patch("os.path.getsize")
@patch("wandarr.ffmpeg.FFmpeg.run")
@patch("os.remove")
@patch("os.rename")
def test_localhost_job(rename_mock, remove_mock, ffmpeg_mock, getsize_mock, media_info, basic_config, ffmpeg_return):

    getsize_mock.return_value = 1_500_000_000
    ffmpeg_mock.return_value = ffmpeg_return

    config = basic_config
    props = config.hosts["workstation"]
    host_props = RemoteHostProperties("workstation", props)
    q = Queue()
    mi = media_info

    # deactivate threshold check
    config.templates["tv"].template["threshold"] = 0

    job = EncodeJob("/tmp/test.mkv", mi, config.templates["tv"])
    q.put(job)

    host = LocalHost("workstation", host_props, q)

    host.video_cli = "-c:v copy"
    host.testrun()

    if ffmpeg_return == 0:
        assert remove_mock.call_args.args[0] == "/tmp/test.mkv"
        assert rename_mock.call_args.args == ("/tmp/test.mkv.tmp", "/tmp/test.mkv")
    assert q.empty() is True


@pytest.mark.parametrize("ffmpeg_return", [0, -1])
@patch("os.path.getsize")
@patch("wandarr.ffmpeg.FFmpeg.run_remote")
@patch("os.remove")
@patch("os.rename")
def test_mountedhost_job(rename_mock, remove_mock, ffmpeg_mock, getsize_mock, media_info, basic_config, ffmpeg_return):

    getsize_mock.return_value = 1_500_000_000
    ffmpeg_mock.return_value = ffmpeg_return

    config = basic_config
    props = config.hosts["server"]
    host_props = RemoteHostProperties("server", props)
    q = Queue()
    mi = media_info

    # "fix" the template to not think threshold was met
    config.templates["tv"].template["threshold"] = 0

    job = EncodeJob("/Volumes/media/test.mkv", mi, config.templates["tv"])
    q.put(job)

    host = MountedManagedHost("server", host_props, q)

    host.video_cli = "-c:v copy"
    host.testrun()

    if ffmpeg_return == 0:
        assert remove_mock.call_args.args[0] == "/Volumes/media/test.mkv"
        assert rename_mock.call_args.args == ("/Volumes/media/test.mkv.tmp", "/Volumes/media/test.mkv")
        assert q.empty() is True
    else:
        assert remove_mock.call_args.args[0] == "/Volumes/media/test.mkv.tmp"

    # verify host-mapped files
    assert host.remote_in_path == "/mnt/media/test.mkv"
    assert host.remote_out_path == "/mnt/media/test.mkv.tmp"


@patch("os.path.getsize")
@patch("wandarr.ffmpeg.FFmpeg.run_remote")
@patch("os.remove")
@patch("os.rename")
@patch("wandarr.streaminghost.run")
@patch("shutil.move")
@patch("wandarr.streaminghost.StreamingManagedHost.run_process")
def test_streaming_job(run_process_mock, move_mock, run_mock, rename_mock, remove_mock, ffmpeg_mock,
                       getsize_mock, media_info, basic_config):

    getsize_mock.return_value = 1_500_000_000
    ffmpeg_mock.return_value = 0
    run_mock.return_value = (0, "")

    config = basic_config
    props = config.hosts["server"]
    host_props = RemoteHostProperties("server", props)
    q = Queue()
    mi = media_info

    # "fix" the template to not think threshold was met
    config.templates["tv"].template["threshold"] = 0

    job = EncodeJob("/tmp/test.mkv", mi, config.templates["tv"])
    q.put(job)

    host = StreamingManagedHost("server", host_props, q)

    host.video_cli = "-c:v copy"
    host.testrun()

    assert run_process_mock.call_args.args[0] == ["/usr/bin/ssh", "me@192.168.1.100", '"rm /tmp/test.mkv.tmp"']
    assert len(run_mock.call_args) == 2
    assert q.empty() is True


@patch("os.path.getsize")
@patch("wandarr.ffmpeg.FFmpeg.monitor_agent_ffmpeg")
@patch("os.remove")
@patch("os.rename")
@patch("os.unlink")
@patch("wandarr.agenthost.AgentManagedHost.connect", return_value=True)
@patch("wandarr.agenthost.AgentManagedHost.handshake", return_value=True)
@patch("wandarr.agenthost.AgentManagedHost.sendfile", return_value=True)
@patch("wandarr.agenthost.AgentManagedHost.recvfile", return_value=True)
@patch("wandarr.agenthost.AgentManagedHost.ack", return_value=True)
def test_agent_job(ack_mock, recv_mock, send_mock, handshake_mock, connect_mock,
                   unlink_mock, rename_mock, remove_mock, ffmpeg_mock, getsize_mock, media_info, basic_config):

    getsize_mock.return_value = 1_500_000_000
    ffmpeg_mock.return_value = (True, "DONE|0|1300000000")

    config = basic_config
    props = config.hosts["server4"]
    host_props = RemoteHostProperties("server", props)
    q = Queue()
    mi = media_info

    # "fix" the template to not think threshold was met
    config.templates["tv"].template["threshold"] = 0

    job = EncodeJob("/tmp/test.mkv", mi, config.templates["tv"])
    q.put(job)

    host = AgentManagedHost("server", host_props, q)

    host.video_cli = "-c:v copy"
    host.testrun()
