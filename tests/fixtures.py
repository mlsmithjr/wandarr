import json
from unittest.mock import patch
import pytest

from wandarr.config import ConfigFile
from wandarr.media import MediaInfo

@pytest.fixture
def media_info():

    with patch("os.path.getsize") as getsize_mock:
        getsize_mock.return_value = 1_500_000_000
        with open("tests/ffprobe.json", "r", encoding="utf8") as f:
            buf = f.read()
            doc = json.loads(buf)

        mi = MediaInfo.parse_ffprobe_details_json("/tmp/test.mkv", doc)
        return mi


@pytest.fixture
def basic_config():
    config = ConfigFile("tests/basic_config.yml")
    return config
