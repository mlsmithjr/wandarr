import json
import os
import re
from datetime import timedelta
from os.path import basename
from typing import Dict, Optional, List

from rich.table import Table
from rich.console import Console

video_dur = re.compile(r".*Duration: (\d+):(\d+):(\d+)", re.DOTALL)
frames_re = re.compile(r'^.*Stream #0:0.*NUMBER_OF_FRAMES.+?(?P<frames>\d+)$', re.DOTALL | re.MULTILINE)
video_info = re.compile(
    r'.*Stream #0:(\d+)(?:\(\w+\))?: Video: (\w+).*, (yuv\w+)[(,].* (\d+)x(\d+).* (\d+)(\.\d.)? fps', re.DOTALL)
audio_info = re.compile(
    r'^\s+Stream #0:(?P<stream>\d+)(\((?P<lang>\w+)\))?: Audio: (?P<format>\w+).*?(?P<default>\(default\))?$',
    re.MULTILINE)
subtitle_info = re.compile(
    r'^\s+Stream #0:(?P<stream>\d+)(\((?P<lang>\w+)\))?: Subtitle: (?P<format>\w+)\s(?P<default>\(default\))?',
    re.MULTILINE)


class StreamInfoWrapper:
    def __init__(self, data: dict):
        self.data = data

    @property
    def stream(self) -> int:
        return self.data.get("stream", -1)

    @property
    def format(self) -> str:
        return self.data.get("format", "???")

    @property
    def default(self) -> str:
        return self.data.get("default", "0")

    @property
    def lang(self) -> str:
        return self.data.get("lang", "???")

    @property
    def size_mb(self) -> int:
        return int(self.data.get("mb", 0))

    def __str__(self):
        return json.dumps(self.data)


class MediaInfo:
    # pylint: disable=too-many-instance-attributes

    def __init__(self, info: Optional[Dict]):
        self.valid = info is not None
        if not self.valid:
            return
        self.path = info['path']
        self.vcodec = info['vcodec']
        self.frames = info['frames']
        self.stream = info['stream']
        self.res_height = info['res_height']
        self.res_width = info['res_width']
        self.runtime = info.get('runtime', 0)
        self.filesize_mb = info['filesize_mb']
        self.fps = info['fps']
        self.colorspace = info['colorspace']
        self.audio: List[StreamInfoWrapper] = info['audio']
        self.subtitle: List[StreamInfoWrapper] = info['subtitle']

    def __str__(self):
        runtime = "{:0>8}".format(str(timedelta(seconds=self.runtime)))
        for a in self.audio:
            print(a)

        audios = []
        for a in self.audio:
            dind = '*' if a.default == "1" else ''
            lang = a.lang
            line = lang + dind + ',' + a.format
            if a.size_mb:
                line += f', {a.size_mb}mb'
            audios.append(line)

        subs = []
        for s in self.subtitle:
            dind = '*' if s.default == "1" else ''
            subs.append(s.lang + dind)

        audio = '(' + ','.join(audios) + ')'
        sub = '(' + ','.join(subs) + ')'
        buf = f"{self.path}, {self.filesize_mb}mb, {self.fps} fps, {self.res_width}x{self.res_height}, {runtime}, {self.vcodec}, audio={audio}, sub={sub}"
        return buf

    @staticmethod
    def show_info(use_rich, files, ffmpeg):
        if use_rich:
            console = Console()
            table = Table(title="Technical Details")

            table.add_column("File", style="magenta")
            table.add_column("Runtime", justify="right", style="cyan", no_wrap=True)
            table.add_column("Video", justify="right", style="green")
            table.add_column("Resolution", justify="right", style="green")
            table.add_column("SizeMB", justify="right", style="green")
            table.add_column("FPS", justify="right", style="green")
            table.add_column("Audio", justify="right", style="green")
            table.add_column("Subtitle", justify="right", style="green")

            for path in files:
                mi = ffmpeg.fetch_details(path)
                mins = int(mi.runtime / 60)
                audios = []
                for a in mi.audio:
                    dind = '*' if a.default == "1" else ''
                    lang = a.lang
                    line = lang + dind + ',' + a.format
                    if a.size_mb:
                        line += ',' + str(a.size_mb) + 'mb'
                    audios.append(line)

                subs = []
                for s in mi.subtitle:
                    dind = '*' if s.default == "1" else ''
                    subs.append(s.lang + dind)

                table.add_row(basename(mi.path),
                              str(mins) + "m",
                              mi.vcodec,
                              f"{mi.res_width}x{mi.res_height}",
                              str(round(mi.filesize_mb, 1)),
                              str(mi.fps),
                              "|".join(audios),
                              "|".join(subs))
            console.print(table)
        else:
            for path in files:
                media_info = ffmpeg.fetch_details(path)
                print(str(media_info))

    def is_multistream(self) -> bool:
        return len(self.audio) > 1 or len(self.subtitle) > 1

    @staticmethod
    def _parse_regex_audio(output: str) -> list:
        audio_tracks = []
        for audio_match in audio_info.finditer(output):
            ainfo = audio_match.groupdict()
            if ainfo['lang'] is None:
                ainfo['lang'] = 'und'  # set as (und)efined
            ainfo['default'] = "1" if ainfo.get('default') == "(default)" else "0"
            audio_tracks.append(StreamInfoWrapper(ainfo))
        return audio_tracks

    @staticmethod
    def _parse_regex_subtitle(output: str) -> list:
        subtitle_tracks = []
        for subt_match in subtitle_info.finditer(output):
            sinfo = subt_match.groupdict()
            if sinfo['lang'] is None:
                sinfo['lang'] = 'und'
            sinfo['default'] = "1" if sinfo.get('default') == "(default)" else "0"
            subtitle_tracks.append(StreamInfoWrapper(sinfo))
        return subtitle_tracks

    @staticmethod
    def _parse_regex_video(_path: str, output: str) -> Optional[dict]:
        match1 = video_dur.match(output)
        if match1 is None or len(match1.groups()) < 3:
            print(f'>>>> regex match on video stream data failed: ffmpeg -i {_path}')
            return None

        frames_match = frames_re.match(output)
        frames = int(frames_match.groupdict()['frames']) if frames_match else 0

        match2 = video_info.match(output)
        if match2 is None or len(match2.groups()) < 5:
            print(f'>>>> regex match on video stream data failed: ffmpeg -i {_path}')
            return None
        _dur_hrs, _dur_mins, _dur_secs = match1.group(1, 2, 3)
        _id, _codec, _colorspace, _res_width, _res_height, fps = match2.group(1, 2, 3, 4, 5, 6)
        filesize = int(os.path.getsize(_path) / (1024 * 1024))

        minfo = {
            'path': _path,
            'vcodec': _codec,
            'stream': _id,
            'frames': frames,
            'res_width': int(_res_width),
            'res_height': int(_res_height),
            'runtime': (int(_dur_hrs) * 3600) + (int(_dur_mins) * 60) + int(_dur_secs),
            'filesize_mb': filesize,
            'fps': int(fps),
            'colorspace': _colorspace,
        }
        return minfo

    @staticmethod
    def parse_ffmpeg_details(_path, output):

        info = MediaInfo._parse_regex_video(_path, output)
        audio_tracks = MediaInfo._parse_regex_audio(output)
        subtitle_tracks = MediaInfo._parse_regex_subtitle(output)

        info['audio'] = audio_tracks
        info['subtitle'] = subtitle_tracks

        return MediaInfo(info)

    @staticmethod
    def _parse_json_video(_path: str, stream: dict, minfo: dict):
        minfo['path'] = _path
        minfo['vcodec'] = stream['codec_name']
        minfo['stream'] = str(stream['index'])
        minfo['res_width'] = stream['width']
        minfo['res_height'] = stream['height']
        minfo['filesize_mb'] = int(os.path.getsize(_path) / (1024 * 1024))
        fr_parts = stream['r_frame_rate'].split('/')
        fr = int(int(fr_parts[0]) / int(fr_parts[1]))
        minfo['fps'] = fr
        minfo['colorspace'] = stream['pix_fmt']
        if 'tags' in stream and 'NUMBER_OF_FRAMES' in stream['tags']:
            frames = int(stream['tags']['NUMBER_OF_FRAMES'])
            minfo['frames'] = frames
        else:
            minfo['frames'] = 0

        if 'duration' in stream:
            minfo['runtime'] = int(float(stream['duration']))
        else:
            if 'tags' in stream:
                for name, value in stream['tags'].items():
                    if name[0:8] == 'DURATION':
                        hh, mm, ss = value.split(':')
                        duration = (int(float(hh)) * 3600) + (int(float(mm)) * 60) + int(float(ss))
                        minfo['runtime'] = duration
                        break

    @staticmethod
    def _parse_json_audio(stream: Dict, minfo: Dict):
        audio = {"stream": str(stream["index"]), "format": stream["codec_name"], "default": "0"}
        # need to check for duration b/c it may not appear in the video stream
        if 'duration' in stream:
            minfo['runtime'] = int(float(stream['duration']))
        if 'disposition' in stream:
            audio['default'] = str(stream['disposition'].get('default', 0))
        if 'tags' in stream:
            tags = stream['tags']
            if 'language' in tags:
                audio['lang'] = tags['language']
            else:
                # derive the language
                for name in tags.keys():
                    if name[0:9] == 'DURATION-':
                        lang = name[9:]
                        audio['lang'] = lang
                        break
            if "NUMBER_OF_BYTES" in tags:
                audio['mb'] = str(int(int(tags["NUMBER_OF_BYTES"]) / 1024000))

        minfo['audio'].append(StreamInfoWrapper(audio))

    @staticmethod
    def _parse_json_subtitle(stream: Dict, minfo: Dict):
        sub = {"stream": str(stream["index"]), "format": stream["codec_name"], "default": "0"}
        # need to check for duration b/c it may not appear in the video stream
        if 'duration' in stream:
            minfo['runtime'] = int(float(stream['duration']))

        if 'disposition' in stream:
            sub['default'] = str(stream['disposition'].get('default', 0))
        if 'tags' in stream:
            if 'language' in stream['tags']:
                sub['lang'] = stream['tags']['language']
            else:
                # derive the language
                for name in stream['tags'].keys():
                    if name[0:9] == 'DURATION-':
                        lang = name[9:]
                        sub['lang'] = lang
                        break
        minfo['subtitle'].append(StreamInfoWrapper(sub))

    @staticmethod
    def parse_ffprobe_details_json(_path, info):
        minone = MediaInfo(None)
        minfo = {'audio': [], 'subtitle': []}
        if 'streams' not in info:
            return minone
        found_video = False  # used to detect first video stream (the real one)
        for stream in info['streams']:
            match stream['codec_type']:
                case "video" if not found_video:
                    found_video = True
                    MediaInfo._parse_json_video(_path, stream, minfo)

                case "audio":
                    MediaInfo._parse_json_audio(stream, minfo)

                case "subtitle" | "subrip":
                    MediaInfo._parse_json_subtitle(stream, minfo)

        return MediaInfo(minfo)
