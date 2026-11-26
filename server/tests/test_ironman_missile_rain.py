"""The missile-rain ultimate keeps what the Lua script and the battle rely on (needs the shipped APK files)."""

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools import ironman_missile_rain as rain, sam, sam_render

SHIPPED = sam_render.ANIM_DIR / "ironman.swf.sam"
PARTS = sam_render.PARTS_DIR / "ironman"
HIT_ANCHORS = ('"beiji"', '"bao"', "shock_screen", "zhongpao")
SPRITE_NAMES = (["pose_" + n for n in ("crouch", "rise", "charge", "fire", "descend")]
                + ["explosion_%d" % i for i in range(1, 7)] + ["missile"] + ["puff_%d" % i for i in (1, 2, 3)])


def _fake_sprites(folder: Path):
    """Solid-colour stand-ins with the right names; the animation only needs sizes and pivots."""
    info = {}
    for index, name in enumerate(SPRITE_NAMES):
        size = (60, 80) if name.startswith("pose_") else (50, 50)
        Image.new("RGBA", size, (10 * index % 255, 120, 200, 255)).save(folder / (name + ".png"))
        info[name] = {"file": name + ".png", "width": size[0], "height": size[1], "pivot": [size[0] / 2, size[1] / 2]}
    (folder / "sprites.json").write_text(json.dumps({"pose_supersample": 2, "sprites": info}))


@unittest.skipUnless(SHIPPED.exists() and PARTS.exists(), "decompiled APK not available (set SAHHT_DECOMPILED)")
class MissileRainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "sprites").mkdir()
        _fake_sprites(root / "sprites")
        cls.old = sam.load(str(SHIPPED))
        prepared, cls.sprites = rain.add_sprites(cls.old, root / "sprites", PARTS, root / "parts")
        cls.root = root
        cls.new = rain.build(prepared, cls.sprites, PARTS)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _section(self, animation):
        tags, inside = [], False
        for tag in animation.tags:
            if isinstance(tag, sam.Label):
                inside = tag.name == rain.SECTION
            elif inside:
                tags.append(tag)
        return tags

    def _anchors(self, animation):
        out, frame = [], 0
        for tag in self._section(animation):
            if isinstance(tag, sam.Show):
                frame += 1
            elif isinstance(tag, sam.Anchor):
                out.append((frame, tag.name))
        return out

    def test_section_length_and_the_other_sections_are_untouched(self):
        self.assertEqual(self.new.sections()[rain.SECTION], self.old.sections()[rain.SECTION])
        self.assertEqual(self.new.frame_count(), self.old.frame_count())
        for name in ("daiji", "gongji1", "gongji2", "gongji3", "gongji5", "mofa"):
            self.assertEqual(self.new.sections()[name], self.old.sections()[name])
        self.assertEqual(self.new.tags[0], self.old.tags[0])

    def test_hit_anchors_stay_on_their_frames(self):
        old, new = self._anchors(self.old), self._anchors(self.new)
        hits = [(frame, text) for frame, text in old if any(key in text for key in HIT_ANCHORS)]
        self.assertTrue(hits)
        for entry in hits:
            self.assertIn(entry, new)

    def test_old_bomb_and_old_full_body_poses_are_gone_and_the_new_sprites_are_used(self):
        names = self.new.images()
        used = {names[t.char_id] for t in self._section(self.new) if isinstance(t, sam.Place) and t.char_id}
        for gone in ("ironman.swf200.png", "ironman.swf202.png", "ironman.swf204.png", "ironman.swf206.png"):
            self.assertNotIn(gone, used)
        for name, sprite in self.sprites.items():
            self.assertIn(sprite[4], used, name)

    def test_every_target_gets_a_missile_and_six_explosion_pictures(self):
        names = self.new.images()
        places = [names[t.char_id] for t in self._section(self.new) if isinstance(t, sam.Place) and t.char_id]
        self.assertEqual(places.count(self.sprites["missile"][4]), len(rain.TARGETS))
        for number in range(1, 7):
            self.assertEqual(places.count(self.sprites["explosion_%d" % number][4]), len(rain.TARGETS))

    def test_nothing_from_the_section_before_is_left_on_the_screen(self):
        displays = list(sam_render.frame_states(self.new))
        first, last = self.new.sections()[rain.SECTION]
        allowed = ({rain.SHADOW_DEPTH, rain.FLAME_DEPTH, rain.GLOW_DEPTH} | set(rain.POSE_DEPTH.values())
                   | set(range(rain.MISSILE_DEPTH, rain.MISSILE_DEPTH + len(rain.TARGETS)))
                   | set(range(rain.PUFF_DEPTH, rain.PUFF_DEPTH + len(rain.TARGETS))))
        hero_parts = set(range(2, 21))     # the idle armor, while it is faded in at the start and the end
        for frame in range(first, last + 1):
            extra = {d for d in displays[frame] if d not in allowed and d < rain.EXPLOSION_DEPTH}
            self.assertLessEqual(extra, hero_parts, "frame %d" % (frame - first))
        for frame in range(first + 12, first + 55):          # in the middle the armor parts are gone
            self.assertFalse(set(displays[frame]) & hero_parts, "frame %d" % (frame - first))

    def test_result_survives_the_byte_format(self):
        data = sam.dumps(self.new)
        self.assertEqual(sam.dumps(sam.loads(data)), data)

    def test_new_sprites_are_written_as_atlas_frame_names(self):
        for name, sprite in self.sprites.items():
            self.assertRegex(sprite[4], r"^ironman\.swf\d+\.png$")
            self.assertTrue((self.root / "parts" / sprite[4]).exists(), name)


if __name__ == "__main__":
    unittest.main()
