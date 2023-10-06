
import os
import re
from datetime import timedelta
from os.path import basename
from typing import Dict, Optional, List

import wandarr
from wandarr import verbose

#video_re = re.compile(r'^.*Duration: (\d+):(\d+):.* Stream .*: Video: (\w+).*, (\w+)[(,].* (\d+)x(\d+).* (\d+)(\.\d.)? fps,.*$',
#                      re.DOTALL)


video_dur = re.compile(r".*Duration: (\d+):(\d+):(\d+)", re.DOTALL)
video_info = re.compile(r'.*Stream #0:(\d+)(?:\(\w+\))?: Video: (\w+).*, (yuv\w+)[(,].* (\d+)x(\d+).* (\d+)(\.\d.)? fps', re.DOTALL)
audio_info = re.compile(r'^\s+Stream #0:(?P<stream>\d+)(\((?P<lang>\w+)\))?: Audio: (?P<format>\w+).*?(?P<default>\(default\))?$', re.MULTILINE)
subtitle_info = re.compile(r'^\s+Stream #0:(?P<stream>\d+)(\((?P<lang>\w+)\))?: Subtitle:', re.MULTILINE)


class MediaInfo:
    # pylint: disable=too-many-instance-attributes

    def __init__(self, info: Optional[Dict]):
        self.valid = info is not None
        if not self.valid:
            return
        self.path = info['path']
        self.vcodec = info['vcodec']
        self.stream = info['stream']
        self.res_height = info['res_height']
        self.res_width = info['res_width']
        self.runtime = info['runtime']
        self.filesize_mb = info['filesize_mb']
        self.fps = info['fps']
        self.colorspace = info['colorspace']
        self.audio = info['audio']
        self.subtitle = info['subtitle']

    def __str__(self):
        runtime = "{:0>8}".format(str(timedelta(seconds=self.runtime)))
        print("DEBUG")
        for a in self.audio:
            print(a)

        audios = [a['stream'] + ':' + a['lang'] + ':' + a['format'] + ':' + a.get('default',"0") for a in self.audio]
        audio = '(' + ','.join(audios) + ')'
        subs = [s['stream'] + ':' + s['lang'] + ':' + s.get('default', '') for s in self.subtitle]
        sub = '(' + ','.join(subs) + ')'
        buf = f"{self.path}, {self.filesize_mb}mb, {self.fps} fps, {self.res_width}x{self.res_height}, {runtime}, {self.vcodec}, audio={audio}, sub={sub}"
        return buf

    @staticmethod
    def show_info(use_rich, files, ffmpeg):
        if use_rich:
            from rich.table import Table
            from rich.console import Console

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
                audios = [a['stream'] + ':' + a['lang'] + ':' + a['format'] + ':' + a.get('default',"") for a in mi.audio]
                subs = [s['stream'] + ':' + s['lang'] + ':' + s.get('default', '') for s in mi.subtitle]

                table.add_row(basename(mi.path),
                              str(mins)+"m",
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
    def parse_ffmpeg_details(_path, output):

        match1 = video_dur.match(output)
        if match1 is None or len(match1.groups()) < 3:
            print(f'>>>> regex match on video stream data failed: ffmpeg -i {_path}')
            return MediaInfo(None)

        match2 = video_info.match(output)
        if match2 is None or len(match2.groups()) < 5:
            print(f'>>>> regex match on video stream data failed: ffmpeg -i {_path}')
            return MediaInfo(None)

        audio_tracks = list()
        for audio_match in audio_info.finditer(output):
            ainfo = audio_match.groupdict()
            if ainfo['lang'] is None:
                ainfo['lang'] = 'und'   # set as (und)efined
            if ainfo['default'] is None:
                ainfo['default'] = "0"
            audio_tracks.append(ainfo)

        subtitle_tracks = list()
        for subt_match in subtitle_info.finditer(output):
            sinfo = subt_match.groupdict()
            if sinfo['lang'] is None:
                sinfo['lang'] = 'und'
            sinfo['default'] = "0"
            subtitle_tracks.append(sinfo)

        _dur_hrs, _dur_mins, _dur_secs = match1.group(1, 2, 3)
        _id, _codec, _colorspace, _res_width, _res_height, fps = match2.group(1, 2, 3, 4, 5, 6)
        filesize = os.path.getsize(_path) / (1024 * 1024)

        minfo = {
            'path': _path,
            'vcodec': _codec,
            'stream': _id,
            'res_width': int(_res_width),
            'res_height': int(_res_height),
            'runtime': (int(_dur_hrs) * 3600) + (int(_dur_mins) * 60) + int(_dur_secs),
            'filesize_mb': filesize,
            'fps': int(fps),
            'colorspace': _colorspace,
            'audio': audio_tracks,
            'subtitle': subtitle_tracks
        }
        return MediaInfo(minfo)

    @staticmethod
    def parse_ffmpeg_details_json(_path, info):
        minone = MediaInfo(None)
        minfo = { 'audio': [], 'subtitle': []}
        if 'streams' not in info:
            return minone
        found_video = False     # used to detect first video stream (the real one)
        for stream in info['streams']:
            if stream['codec_type'] == 'video' and not found_video:
                found_video = True
                minfo['path'] = _path
                minfo['vcodec'] = stream['codec_name']
                minfo['stream'] = str(stream['index'])
                minfo['res_width'] = stream['width']
                minfo['res_height'] = stream['height']
                minfo['filesize_mb'] = os.path.getsize(_path) / (1024 * 1024)
                fr_parts = stream['r_frame_rate'].split('/')
                fr = int(int(fr_parts[0]) / int(fr_parts[1]))
                minfo['fps'] = str(fr)
                minfo['colorspace'] = stream['pix_fmt']
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

            elif stream['codec_type'] == 'audio':
                audio = dict()
                audio['stream'] = str(stream['index'])
                audio['format'] = stream['codec_name']
                audio['default'] = "0"
                if 'disposition' in stream:
                    if 'default' in stream['disposition']:
                        audio['default'] = stream['disposition']['default'] or "0"
                if 'tags' in stream:
                    if 'language' in stream['tags']:
                        audio['lang'] = stream['tags']['language']
                    else:
                        # derive the language
                        for name, value in stream['tags'].items():
                            if name[0:9] == 'DURATION-':
                                lang = name[9:]
                                audio['lang'] = lang
                                break
                minfo['audio'].append(audio)
            elif stream['codec_type'] == 'subrip':
                sub = dict()
                sub['stream'] = str(stream['index'])
                sub['format'] = stream['codec_name']
                sub['default'] = "0"
                if 'disposition' in stream:
                    if 'default' in stream['disposition']:
                        sub['default'] = stream['disposition']['default'] or "0"
                if 'tags' in stream:
                    if 'language' in stream['tags']:
                        sub['lang'] = stream['tags']['language']
                    else:
                        # derive the language
                        for name, value in stream['tags'].items():
                            if name[0:9] == 'DURATION-':
                                lang = name[9:]
                                sub['lang'] = lang
                                break
                minfo['subtitle'].append(sub)
        return MediaInfo(minfo)

