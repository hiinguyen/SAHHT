"""tools/atlas.py: CCZ/PVR RGBA4444 round trip and frame replace/add on a small synthetic atlas."""

import plistlib
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

from tools import atlas


def _plist(frames):
    return {"frames": frames, "metadata": {"format": 2, "size": "{64,64}", "textureFileName": "t-hd.pvr.ccz",
                                           "realTextureFileName": "t-hd.pvr.ccz", "smartupdate": "x"}}


def _entry(x, y, w, h, rotated=False):
    return {"frame": "{{%d,%d},{%d,%d}}" % (x, y, w, h), "offset": "{0,0}", "rotated": rotated,
            "sourceColorRect": "{{0,0},{%d,%d}}" % (w, h), "sourceSize": "{%d,%d}" % (w, h)}


def _atlas_image():
    """64x64 whose pixels are exact multiples of 17, like a decoded RGBA4444 atlas."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.paste(Image.new("RGBA", (10, 6), (255, 119, 34, 255)), (2, 2))          # frame "a", 10 x 6
    image.paste(Image.new("RGBA", (5, 12), (17, 68, 255, 255)), (20, 20))         # frame "b", drawn 12 x 5, stored rotated
    return image


def _sheet():
    return _atlas_image(), _plist({"a.png": _entry(2, 2, 10, 6), "b.png": _entry(20, 20, 12, 5, rotated=True)})


class CodecTests(unittest.TestCase):
    def test_pixels_that_are_multiples_of_17_survive_exactly(self):
        image = _atlas_image()
        back = atlas.decode_ccz(atlas.encode_ccz(image))
        self.assertEqual(back.size, image.size)
        self.assertEqual(back.tobytes(), image.tobytes())

    def test_header_matches_what_the_game_files_use(self):
        blob = atlas.encode_ccz(_atlas_image())
        self.assertEqual(blob[:4], b"CCZ!")
        self.assertEqual(blob[4:8], b"\x00\x00\x00\x02")
        pvr = zlib.decompress(blob[16:])
        self.assertEqual(int.from_bytes(blob[12:16], "big"), len(pvr))
        self.assertEqual(atlas.PVR_HEADER.unpack_from(pvr),
                         (52, 64, 64, 0, 0x8010, 64 * 64 * 2, 16, 0xF000, 0x0F00, 0x00F0, 0x000F, atlas.PVR_TAG, 1))

    def test_dither_keeps_every_pixel_within_one_level_and_the_mean(self):
        gradient = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))
        image = Image.fromarray(np.dstack([gradient, gradient, gradient, np.full_like(gradient, 255)]), "RGBA")
        back = np.asarray(atlas.decode_ccz(atlas.encode_ccz(image, np.ones((64, 64), dtype=bool)))).astype(int)
        error = back[..., 0] - np.asarray(image).astype(int)[..., 0]
        self.assertLessEqual(np.abs(error).max(), 17)
        self.assertLess(abs(error.mean()), 2)

    def test_transparent_pixels_stay_transparent(self):
        image = Image.new("RGBA", (8, 8), (200, 100, 50, 0))
        back = atlas.decode_ccz(atlas.encode_ccz(image, np.ones((8, 8), dtype=bool)))
        self.assertEqual({p[3] for p in back.getdata()}, {0})

    def test_a_file_that_is_not_ccz_is_refused(self):
        with self.assertRaises(atlas.AtlasError):
            atlas.decode_ccz(b"nope")


class RepackTests(unittest.TestCase):
    def test_a_replaced_frame_keeps_its_place_and_rotation_and_others_are_untouched(self):
        image, plist = _sheet()
        new_b = Image.new("RGBA", (12, 5), (255, 0, 0, 255))
        canvas, new_plist, dither = atlas.repack(image, plist, {"b.png": new_b}, {})
        self.assertEqual(atlas.read_frame(canvas, new_plist["frames"]["b.png"]).tobytes(), new_b.tobytes())
        self.assertEqual(canvas.crop((2, 2, 12, 8)).tobytes(), image.crop((2, 2, 12, 8)).tobytes())
        self.assertEqual(canvas.size, image.size)
        self.assertTrue(dither[20:32, 20:25].all())
        self.assertFalse(dither[2:8, 2:12].any())

    def test_a_replacement_of_the_wrong_size_is_refused(self):
        image, plist = _sheet()
        with self.assertRaises(atlas.AtlasError):
            atlas.repack(image, plist, {"a.png": Image.new("RGBA", (9, 6))}, {})

    def test_added_frames_go_to_the_right_with_padding_and_a_plist_entry(self):
        image, plist = _sheet()
        sprite = Image.new("RGBA", (30, 20), (0, 255, 0, 255))
        canvas, new_plist, _ = atlas.repack(image, plist, {}, {"n.png": sprite}, max_width=200)
        x, y, w, h, rotated = atlas.frame_box(new_plist["frames"]["n.png"])
        self.assertEqual((w, h, rotated), (30, 20, False))
        self.assertGreaterEqual(x, image.width + atlas.GAP + atlas.PADDING)
        self.assertEqual(atlas.read_frame(canvas, new_plist["frames"]["n.png"]).tobytes(), sprite.tobytes())
        self.assertEqual(new_plist["metadata"]["size"], "{%d,%d}" % canvas.size)
        self.assertEqual(canvas.getpixel((x - 1, y + 5))[:3], (0, 255, 0))      # the edge is extruded into the padding

    def test_shelves_wrap_and_never_overlap(self):
        image, plist = _sheet()
        sprites = {"s%d.png" % i: Image.new("RGBA", (30, 10 + i), (i * 20, 0, 0, 255)) for i in range(6)}
        canvas, new_plist, _ = atlas.repack(image, plist, {}, sprites, max_width=140)
        boxes = [atlas.frame_box(new_plist["frames"][n])[:4] for n in sprites]
        pad = 2 * atlas.PADDING
        for index, (x, y, w, h) in enumerate(boxes):
            self.assertLessEqual(x + w + atlas.PADDING, 140)
            for ox, oy, ow, oh in boxes[index + 1:]:
                self.assertTrue(x + w + pad <= ox or ox + ow + pad <= x or y + h + pad <= oy or oy + oh + pad <= y)
        for name, part in sprites.items():
            self.assertEqual(atlas.read_frame(canvas, new_plist["frames"][name]).tobytes(), part.tobytes())

    def test_an_added_name_that_exists_is_refused(self):
        image, plist = _sheet()
        with self.assertRaises(atlas.AtlasError):
            atlas.repack(image, plist, {}, {"a.png": Image.new("RGBA", (4, 4))})


class EditTests(unittest.TestCase):
    def test_edit_replaces_only_frames_whose_png_changed_and_writes_loadable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image, plist = _sheet()
            anim, parts, out = root / "anim", root / "parts", root / "out"
            anim.mkdir()
            parts.mkdir()
            (anim / "t-hd.pvr.ccz").write_bytes(atlas.encode_ccz(image))
            (anim / "t.plist").write_bytes(plistlib.dumps(plist))
            atlas.read_frame(image, plist["frames"]["a.png"]).save(parts / "a.png")       # unchanged
            Image.new("RGBA", (12, 5), (255, 0, 0, 255)).save(parts / "b.png")             # changed
            Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(parts / "n.png")            # new
            result = atlas.edit("t", anim, parts, {"sprite": "n.png"}, out)
            self.assertEqual(result["replaced"], ["b.png"])
            self.assertEqual(result["added"], ["n.png"])
            new_plist = plistlib.loads((out / "t.plist").read_bytes())
            new_atlas = atlas.decode_ccz((out / "t-hd.pvr.ccz").read_bytes())
            self.assertEqual(set(new_plist["frames"]), {"a.png", "b.png", "n.png"})
            self.assertEqual(new_atlas.size, tuple(int(v) for v in new_plist["metadata"]["size"].strip("{}").split(",")))
            self.assertEqual(atlas.read_frame(new_atlas, new_plist["frames"]["b.png"]).getpixel((3, 2)), (255, 0, 0, 255))
            self.assertEqual(atlas.read_frame(new_atlas, new_plist["frames"]["a.png"]).tobytes(),
                             atlas.read_frame(image, plist["frames"]["a.png"]).tobytes())


if __name__ == "__main__":
    unittest.main()
