"""tools/art_kit.py: part sheets out to an image AI and back."""

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from tools import art_kit


def _make_part(path: Path, size, color):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((1, 1, size[0] - 2, size[1] - 2), fill=color + (255,))
    image.save(path)


class ArtKitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.parts = self.root / "parts"
        self.parts.mkdir()
        _make_part(self.parts / "hero.swf1.png", (60, 40), (200, 30, 30))
        _make_part(self.parts / "hero.swf3.png", (20, 30), (30, 30, 200))
        self.kit = self.root / "kit"
        art_kit.export("hero", self.kit, parts_dir=self.parts, group="all")

    def _redraw(self, fill=None):
        (self.kit / "redrawn").mkdir(exist_ok=True)
        sheet = Image.open(self.kit / "sheets" / "sheet_01.png")
        if fill is not None:
            sheet = Image.new("RGB", sheet.size, fill)
        sheet.save(self.kit / "redrawn" / "sheet_01.png")

    def test_export_lays_parts_on_a_grid_largest_first(self):
        parts = json.loads((self.kit / "manifest.json").read_text())["parts"]
        self.assertEqual([p["part"] for p in parts], ["hero.swf1.png", "hero.swf3.png"])
        self.assertEqual((parts[0]["col"], parts[0]["row"]), (0, 0))
        self.assertEqual((parts[1]["col"], parts[1]["row"]), (1, 0))
        self.assertEqual(Image.open(self.kit / "sheets" / "sheet_01.png").size, art_kit.SHEET_SIZE)

    def test_untouched_sheet_comes_back_with_the_original_shape(self):
        self._redraw()
        out = self.root / "out"
        self.assertEqual(art_kit.import_sheets("hero", self.kit, out, parts_dir=self.parts), 2)
        for name in ("hero.swf1.png", "hero.swf3.png"):
            original = Image.open(self.parts / name).convert("RGBA")
            result = Image.open(out / name).convert("RGBA")
            self.assertEqual(result.size, original.size)
            self.assertEqual(result.getchannel("A").tobytes(), original.getchannel("A").tobytes())
        centre = Image.open(out / "hero.swf1.png").getpixel((30, 20))
        self.assertGreater(centre[0], 180)
        self.assertLess(centre[2], 80)

    def test_redraw_that_bleeds_outside_is_clipped_to_the_original_alpha(self):
        self._redraw(fill=(10, 200, 10))
        out = self.root / "out"
        art_kit.import_sheets("hero", self.kit, out, parts_dir=self.parts)
        result = Image.open(out / "hero.swf1.png").convert("RGBA")
        original = Image.open(self.parts / "hero.swf1.png").convert("RGBA")
        self.assertEqual(result.getchannel("A").tobytes(), original.getchannel("A").tobytes())
        self.assertEqual(result.getpixel((30, 20))[:3], (10, 200, 10))
        self.assertEqual(result.getpixel((0, 0))[3], 0)

    def test_wrong_sheet_size_is_refused(self):
        (self.kit / "redrawn").mkdir()
        Image.new("RGB", (100, 100)).save(self.kit / "redrawn" / "sheet_01.png")
        with self.assertRaises(SystemExit):
            art_kit.import_sheets("hero", self.kit, self.root / "out", parts_dir=self.parts)


if __name__ == "__main__":
    unittest.main()
