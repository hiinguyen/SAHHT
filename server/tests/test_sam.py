"""The `.sam` animation reader and writer (tools/sam.py)."""

import struct
import unittest

from tools import sam


def _tag(kind, body, size=None):
    return struct.pack("<II", kind, len(body) if size is None else size) + body


def _sample():
    return b"".join([
        _tag(6, struct.pack("<IIfI", 200, 250, 24.0, 3)),
        _tag(2, b"daiji\0"),
        _tag(1, struct.pack("<I", 1) + b"hero.swf1.png\0"),
        _tag(3, struct.pack("<5I", 1, 7, 2, 1, 1) + struct.pack("<6f", 1, 0, 0, 1, 10.5, -4)
             + struct.pack("<II", 0, 1) + struct.pack("<4I", 256, 256, 256, 128), size=84),
        _tag(7, b'{"type":"wav","res":"hit"}\0'),
        _tag(5, b""),
        _tag(3, struct.pack("<5I", 0, 7, 2, 0, 1) + struct.pack("<6f", 1, 0, 0, 1, 12.5, -4), size=44),
        _tag(5, b""),
        _tag(2, b"gongji1\0"),
        _tag(4, struct.pack("<I", 7)),
        _tag(5, b""),
        _tag(0, b""),
    ])


class SamTests(unittest.TestCase):
    def test_reads_every_tag_type(self):
        s = sam.loads(_sample())
        self.assertEqual(s.tags[0], sam.Handle(200, 250, 24.0, 3))
        self.assertEqual(s.images(), {1: "hero.swf1.png"})
        place = s.tags[3]
        self.assertEqual((place.char_id, place.depth, place.z), (1, 7, 2))
        self.assertEqual(place.matrix, (1, 0, 0, 1, 10.5, -4))
        self.assertEqual(place.color, sam.ColorForm(mult=(256, 256, 256, 128)))
        self.assertEqual(s.tags[4], sam.Anchor('{"type":"wav","res":"hit"}'))
        self.assertIsInstance(s.tags[-1], sam.End)

    def test_sections_are_frame_ranges(self):
        s = sam.loads(_sample())
        self.assertEqual(s.sections(), {"daiji": [0, 1], "gongji1": [2, 2]})
        self.assertEqual(s.frame_count(), 3)

    def test_round_trip_is_byte_exact(self):
        data = _sample()
        self.assertEqual(sam.dumps(sam.loads(data)), data)

    def test_declared_place_size_follows_the_struct(self):
        bare = sam.dumps(sam.Sam([sam.Place(char_id=1)]))
        self.assertEqual(struct.unpack_from("<II", bare)[1], 20)
        full = sam.dumps(sam.Sam([sam.Place(matrix=(1, 0, 0, 1, 0, 0), color=sam.ColorForm())]))
        self.assertEqual(struct.unpack_from("<II", full)[1], 84)

    def test_color_flag_without_parts_survives(self):
        data = _tag(3, struct.pack("<5I", 1, 1, 1, 1, 0) + struct.pack("<II", 0, 0), size=60)
        s = sam.loads(data)
        self.assertEqual(s.tags[0].color, sam.ColorForm())
        self.assertEqual(sam.dumps(s), data)

    def test_rejects_unknown_tag_and_truncation(self):
        with self.assertRaises(sam.SamError):
            sam.loads(_tag(9, b""))
        with self.assertRaises(sam.SamError):
            sam.loads(_tag(2, b"no terminator"))
        with self.assertRaises(sam.SamError):
            sam.loads(struct.pack("<II", 4, 4) + b"\x01")


if __name__ == "__main__":
    unittest.main()
