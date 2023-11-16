from unittest.mock import patch

from wandarr.cluster import Cluster
from wandarr.config import ConfigFile

from .fixtures import basic_config, media_info


@patch("wandarr.agenthost.AgentManagedHost.host_ok", return_value=True)
@patch("wandarr.base.ManagedHost.host_ok", return_value=True)
def test_cluster_setup(remote_host_ok_mock, agent_host_ok_mock, basic_config, media_info):
    config = basic_config
    c = Cluster(config)

    # verify disabled host not loaded
    assert len(c.hosts), "hosts" == 4

    with patch("wandarr.ffmpeg.FFmpeg.fetch_details") as ffmpeg:
        ffmpeg.return_value = media_info

        c.enqueue("/tmp/test.mkv", "tv")
        assert c.queues["medium"].qsize() == 1


