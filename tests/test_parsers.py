import json
from unittest.mock import patch

from wandarr.config import ConfigFile
from wandarr.media import MediaInfo
from .fixtures import media_info


def validate_media_info(mi: MediaInfo):
    assert mi is not None
    assert len(mi.audio) == 1
    assert len(mi.subtitle) == 3
    assert mi.fps == 23
    assert (mi.res_width, mi.res_height) == (1920,960)
    assert mi.runtime == (53*60)+17
    assert mi.frames == 74426

    assert mi.audio[0].format == "eac3"
    assert mi.audio[0].lang == "eng"
    assert mi.audio[0].default == "1"

    assert mi.subtitle[0].format == "subrip"
    assert mi.subtitle[0].lang == "eng"
    assert mi.subtitle[0].default == "1"

    s = str(mi)
    assert s == '/tmp/test.mkv, 1430mb, 23 fps, 1920x960, 00:53:17, hevc, audio=(eng*,eac3), sub=(eng*,eng,eng)'


def test_parse_ffprobe(media_info):
    validate_media_info(media_info)


@patch("wandarr.media.os.path.getsize")
def test_parse_ffmpeg(getsize_mock):
    getsize_mock.return_value = 1_500_000_000

    f = open("tests/ffmpeg.txt", "r", encoding="utf8")
    doc = f.read()
    f.close()
    mi = MediaInfo.parse_ffmpeg_details("/tmp/test.mkv", doc)
    validate_media_info(mi)


def test_stream_map(media_info):

    with open("tests/ffprobe.json", "r", encoding="utf8") as f:
        buf = f.read()
        doc = json.loads(buf)

    config = ConfigFile("tests/basic_config.yml")

    template = config.templates["tv"]
    stream_map = template.stream_map(media_info.stream, media_info.audio, media_info.subtitle)
    assert stream_map == ['-map', '0:0', '-map', '0:1', '-map', '0:2', '-map', '0:3', '-map', '0:4']

