import json
import unittest
from unittest.mock import patch

from wandarr.media import MediaInfo


class MyTestCase(unittest.TestCase):

    @patch("wandarr.media.os.path.getsize")
    def test_parse_ffprobe(self, getsize_mock):
        getsize_mock.return_value = 1500

        with open("ffprobe.json", "r", encoding="utf8") as f:
            buf = f.read()
            doc = json.loads(buf)

        mi = MediaInfo.parse_ffprobe_details_json("/tmp/test.mkv", doc)

        self.assertIsNotNone(mi)
        self.assertEqual(len(mi.audio), 1)
        self.assertEqual(len(mi.subtitle), 3)
        self.assertEqual(mi.fps, 23)
        self.assertEqual((mi.res_width, mi.res_height), (1920,960))
        self.assertEqual(mi.runtime, (53*60)+17)

        self.assertEqual(mi.audio[0].format, "eac3")
        self.assertEqual(mi.audio[0].lang, "eng")
        self.assertEqual(mi.audio[0].default, "1")

        self.assertEqual(mi.subtitle[0].format, "subrip")
        self.assertEqual(mi.subtitle[0].lang, "eng")
        self.assertEqual(mi.subtitle[0].default, "1")

    @patch("wandarr.media.os.path.getsize")
    def test_parse_ffmpeg(self, getsize_mock):
        getsize_mock.return_value = 1500

        f = open("ffmpeg.txt", "r", encoding="utf8")
        doc = f.read()
        f.close()
        mi = MediaInfo.parse_ffmpeg_details("/tmp/test.mkv", doc)

        self.assertIsNotNone(mi)
        self.assertEqual(len(mi.audio), 1)
        self.assertEqual(len(mi.subtitle), 3)
        self.assertEqual(mi.fps, 23)
        self.assertEqual((mi.res_width, mi.res_height), (1920,960))
        self.assertEqual(mi.runtime, (53*60)+17)

        self.assertEqual(mi.audio[0].format, "eac3")
        self.assertEqual(mi.audio[0].lang, "eng")
        self.assertEqual(mi.audio[0].default, "1")

        self.assertEqual(mi.subtitle[0].format, "subrip")
        self.assertEqual(mi.subtitle[0].lang, "eng")
        self.assertEqual(mi.subtitle[0].default, "1")


if __name__ == '__main__':
    unittest.main()
