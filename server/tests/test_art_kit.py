"""tools/art_kit.py: part sheets out to an image AI and back."""

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from tools import art_kit


def _open(path):
    with Image.open(path) as image:
        image.load()
        return image.copy()


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

    def _redraw(self, size=(1376, 768), loose=False):
        """A 'redrawn' sheet with a different size and a shifted grid, like a real AI returns."""
        sheet = Image.new("RGB", size, (190, 192, 196))
        draw = ImageDraw.Draw(sheet)
        # part 1 (60x40) bigger and tinted green, part 3 (20x30) in the next cell, plus a watermark
        draw.ellipse((100, 80 + (30 if loose else 0), 340, 240 + (30 if loose else 0)), fill=(10, 200, 10))
        draw.ellipse((500, 90, 580, 210), fill=(240, 240, 20))
        draw.polygon([(1250, 640), (1260, 660), (1280, 665), (1260, 670), (1250, 690), (1240, 670),
                      (1220, 665), (1240, 660)], fill=(250, 250, 250))
        (self.kit / "redrawn").mkdir(exist_ok=True)
        sheet.save(self.kit / "redrawn" / "sheet_01.png")

    def test_export_lays_parts_on_a_grid_largest_first(self):
        parts = json.loads((self.kit / "manifest.json").read_text())["parts"]
        self.assertEqual([p["part"] for p in parts], ["hero.swf1.png", "hero.swf3.png"])
        self.assertEqual((parts[0]["col"], parts[0]["row"]), (0, 0))
        self.assertEqual((parts[1]["col"], parts[1]["row"]), (1, 0))
        self.assertEqual(_open(self.kit / "sheets" / "sheet_01.png").size, art_kit.SHEET_SIZE)

    def test_redrawn_parts_are_fitted_into_the_old_parts_box(self):
        self._redraw()
        out = self.root / "out"
        replaced = art_kit.import_sheets("hero", self.kit, out, parts_dir=self.parts)
        self.assertEqual(replaced, ["hero.swf1.png", "hero.swf3.png"])
        for name, colour in (("hero.swf1.png", (10, 200, 10)), ("hero.swf3.png", (240, 240, 20))):
            result = _open(out / name).convert("RGBA")
            original = _open(self.parts / name).convert("RGBA")
            self.assertEqual(result.size, original.size)
            self.assertEqual(result.getbbox() is not None, True)
            centre = result.getpixel((result.width // 2, result.height // 2))
            self.assertEqual(centre[:3], colour)
            self.assertEqual(centre[3], 255)
            box, old = result.getchannel("A").getbbox(), original.getchannel("A").getbbox()
            self.assertLessEqual(box[2] - box[0], old[2] - old[0])
            self.assertLessEqual(box[3] - box[1], old[3] - old[1])

    def test_a_loose_grid_still_orders_parts_by_row_then_column(self):
        self._redraw(loose=True)
        out = self.root / "out"
        art_kit.import_sheets("hero", self.kit, out, parts_dir=self.parts)
        first = _open(out / "hero.swf1.png").convert("RGBA")
        self.assertEqual(first.getpixel((first.width // 2, first.height // 2))[:3], (10, 200, 10))

    def test_parts_not_redrawn_keep_their_original_pixels(self):
        self._redraw()
        out = self.root / "out"
        _make_part(self.parts / "hero.swf5.png", (10, 10), (1, 2, 3))
        art_kit.import_sheets("hero", self.kit, out, parts_dir=self.parts)
        self.assertEqual(_open(out / "hero.swf5.png").convert("RGBA").getpixel((5, 5))[:3], (1, 2, 3))

    def test_missing_parts_on_the_sheet_are_refused(self):
        (self.kit / "redrawn").mkdir(exist_ok=True)
        Image.new("RGB", (400, 300), (190, 192, 196)).save(self.kit / "redrawn" / "sheet_01.png")
        with self.assertRaises(SystemExit):
            art_kit.import_sheets("hero", self.kit, self.root / "out", parts_dir=self.parts)


if __name__ == "__main__":
    unittest.main()
