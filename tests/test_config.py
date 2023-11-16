
from .fixtures import basic_config


def test_config_load(basic_config):
    config = basic_config

    assert config.ffmpeg_path == "/opt/homebrew/bin/ffmpeg"
    assert len(config.engines) == 4
    assert len(config.templates) == 2
    assert list(config.templates.keys()) == ["tv", "sub-scrub"]
    assert config.templates["tv"].cli == {"audio": "-c:a copy", "subtitles": "-c:s copy"}
    assert config.templates["tv"].audio_langs() == ["eng"]
    assert config.templates["sub-scrub"].audio_langs() == ["eng", "jpn"]


def test_cli(basic_config):

    t = basic_config.templates["tv"]
    assert t.output_options_list() == ['-c:a', 'copy', '-c:s', 'copy']

