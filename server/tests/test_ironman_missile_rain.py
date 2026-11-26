"""The missile-rain ultimate keeps what the Lua script and the battle rely on (needs the shipped APK files)."""

import unittest

from tools import ironman_missile_rain as rain, sam, sam_render

SHIPPED = sam_render.ANIM_DIR / "ironman.swf.sam"
HIT_ANCHORS = ('"beiji"', '"bao"', "shock_screen", "zhongpao")


@unittest.skipUnless(SHIPPED.exists(), "decompiled APK not available (set SAHHT_DECOMPILED)")
class MissileRainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = sam.load(str(SHIPPED))
        cls.new = rain.build(cls.old)

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

    def test_section_length_and_the_rest_of_the_file_are_untouched(self):
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

    def test_the_old_bomb_and_old_full_body_poses_are_gone(self):
        names = self.new.images()
        used = {names[t.char_id] for t in self._section(self.new) if isinstance(t, sam.Place) and t.char_id}
        for gone in ("ironman.swf200.png", "ironman.swf202.png", "ironman.swf206.png"):
            self.assertNotIn(gone, used)
        self.assertIn(rain.MISSILE_PART, used)

    def test_every_target_gets_a_missile_and_the_result_survives_the_byte_format(self):
        data = sam.dumps(self.new)
        self.assertEqual(sam.dumps(sam.loads(data)), data)
        missile_id = next(i for i, name in self.new.images().items() if name == rain.MISSILE_PART)
        launched = sum(isinstance(t, sam.Place) and t.char_id == missile_id for t in self._section(self.new))
        self.assertGreaterEqual(launched, len(rain.TARGETS))


if __name__ == "__main__":
    unittest.main()
