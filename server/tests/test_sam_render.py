"""Placement rules of tools/sam_render.py on synthetic parts."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools import sam, sam_render


def _animation():
    return sam.Sam([
        sam.Handle(40, 40, 24.0, 2),
        sam.Label("daiji"),
        sam.Image(1, "p.png"),
        sam.Place(char_id=1, depth=1, z=1, matrix=(1, 1, 0, 0, 20, 20)),
        sam.Show(),
        sam.Place(char_id=0, depth=1, z=1, matrix=(1, 1, 0, 0, 30, 20)),
        sam.Show(),
        sam.Remove(1),
        sam.Show(),
        sam.End(),
    ])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(Path(self.tmp.name) / "p.png")

    def _frame(self, index):
        animation = _animation()
        display = list(sam_render.frame_states(animation))[index]
        return sam_render.render_frame(animation, display, Path(self.tmp.name), scale=1)

    def _pixel(self, frame, x, y):
        return frame.getpixel((x + sam_render.PAD, y + sam_render.PAD))[:3]

    def test_display_list_follows_place_move_and_remove(self):
        states = list(sam_render.frame_states(_animation()))
        self.assertEqual([len(s) for s in states], [1, 1, 0])
        self.assertEqual(states[1][1][2][4], 30)

    def test_part_is_centred_on_its_translation(self):
        frame = self._frame(0)
        self.assertEqual(self._pixel(frame, 20, 20), (255, 0, 0))
        self.assertEqual(self._pixel(frame, 16, 16), (255, 0, 0))
        self.assertNotEqual(self._pixel(frame, 30, 20), (255, 0, 0))

    def test_moved_part_follows_the_new_matrix(self):
        frame = self._frame(1)
        self.assertEqual(self._pixel(frame, 30, 20), (255, 0, 0))
        self.assertNotEqual(self._pixel(frame, 20, 20), (255, 0, 0))

    def test_color_form_multiplies_then_adds(self):
        part = Image.new("RGBA", (1, 1), (200, 100, 50, 255))
        out = sam_render._tint(part, sam.ColorForm(mult=(128, 256, 256, 256), add=(0, 0, 10, 0)))
        self.assertEqual(out.getpixel((0, 0)), (100, 100, 60, 255))


if __name__ == "__main__":
    unittest.main()
