import sys
from typing import Dict, List, Any, Optional

import wandarr
from wandarr.media import StreamInfoWrapper


class Template:
    def __init__(self, name: str, definition: Dict):
        self.template: Dict[str, Any] = definition
        self._name = name

        if "cli" not in self.template:
            print(f'Template error ({name}: missing "cli" section')
            sys.exit(1)

        self.cli = self.template["cli"]

    def input_options_list(self) -> List[str]:
        opt = self.cli.get("input-options", [])
        return opt

    def output_options_list(self) -> List[str]:
        opts = []
        audio_opt = self.cli.get("audio", "")
        opts.extend(audio_opt.split(" "))
        sub_opt = self.cli.get("subtitles", "")
        opts.extend(sub_opt.split(" "))

        return opts

    def audio_langs(self) -> list:
        # allow for space or , separated list
        if self.template.get("audio-lang", "").find(" ") != -1:
            return self.template.get("audio-lang", "").split(" ")
        return self.template.get("audio-lang", "").split(",")

    def subtitle_langs(self) -> list:
        # allow for space or , separated list
        if self.template.get("subtitle-lang", "").find(" ") != -1:
            return self.template.get("subtitle-lang", "").split(" ")
        return self.template.get("subtitle-lang", "").split(",")

    def video_select(self):
        return self.template.get("video-quality")

    def extension(self) -> str:
        ext = self.template.get('extension')
        if not ext:
            print(f"Required value for 'extension' missing in template {self.name}")
            sys.exit(1)
        return ext

    def name(self) -> str:
        return self._name

    def threshold(self) -> int:
        return self.template.get('threshold', 0)

    def threshold_check(self) -> int:
        return self.template.get('threshold_check', 100)

    def _map_streams(self, stream_type: str, streams: List[StreamInfoWrapper]) -> Optional[list]:
        seq_list = []
        mapped = []
        default_reassign = False
        includes = None
        if stream_type == "a":
            includes = self.audio_langs()
        elif stream_type == "s":
            includes = self.subtitle_langs()

        for s in streams:
            stream_lang = s.lang

            if len(includes) > 0 and stream_lang != "???" and stream_lang not in includes:
                if s.default != "0":
                    # we are screening out this language, but it's the default. So we'll need to set a new default later
                    default_reassign = True
                continue

            # if we got here, map the stream
            mapped.append(s)
            seq = s.stream
            seq_list.append('-map')
            seq_list.append(f'0:{seq}')

        if len(includes) == 0:
            if wandarr.console:
                wandarr.console.print("Language filtering must preserve at least 1 track - skipping", style="magenta")
                return None

        if default_reassign:
            # default to the first language listed
            new_default_lang = includes[0]
            for i, s in enumerate(mapped):
                if s.lang == new_default_lang:
                    seq_list.append(f'-disposition:{stream_type}:{i}')
                    seq_list.append('default')
        return seq_list

    def stream_map(self, video_stream: str, audio: List, subtitle: List) -> List[str]:

        if len(self.audio_langs()) == 0 and len(self.subtitle_langs()) == 0:
            # default to map everything
            return ['-map', '0']

        seq_list = ["-map", f'0:{video_stream}']
        audio_streams = self._map_streams("a", audio)
        subtitle_streams = self._map_streams("s", subtitle)
        if not audio_streams:
            return []
        return seq_list + audio_streams + subtitle_streams
