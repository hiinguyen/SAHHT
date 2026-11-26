"""tools/sam_author.py: keyframes and clips compiled to .sam tags the loader and renderer agree on."""

import unittest

from tools import sam, sam_author as au


def _state_after(tags):
    """Replay place/remove tags the way the client does; return the display list at each show."""
    shown, out = {}, []
    for tag in tags:
        if isinstance(tag, sam.Place):
            if tag.char_id > 0:
                shown[tag.depth] = [tag.char_id, tag.z, tag.matrix, tag.color]
            else:
                entry = shown[tag.depth]
                entry[1], entry[2] = tag.z, tag.matrix or entry[2]
                entry[3] = tag.color or entry[3]
        elif isinstance(tag, sam.Remove):
            del shown[tag.depth]
        elif isinstance(tag, sam.Show):
            out.append({depth: tuple(v) for depth, v in shown.items()})
    return out


class MatrixTests(unittest.TestCase):
    def test_tag_order_round_trips(self):
        m = au.make(10, 20, 2.0, 3.0, 30)
        for got, want in zip(au.from_tag(au.to_tag(m)), m):
            self.assertAlmostEqual(got, want)

    def test_rotation_turns_clockwise_on_screen(self):
        a, b, c, d, _, _ = au.make(rot=90)
        self.assertAlmostEqual(a * 1 + c * 0, 0, places=6)   # the point (1, 0) turns to (0, 1): down
        self.assertAlmostEqual(b * 1 + d * 0, 1, places=6)

    def test_compose_applies_outer_after_inner(self):
        moved = au.compose(au.make(5, 0), au.make(0, 3))
        self.assertEqual((moved[4], moved[5]), (5, 3))
        self.assertEqual(au.compose(au.make(sx=2), au.make(4, 0))[4], 8)

    def test_about_keeps_the_pivot_fixed(self):
        m = au.about((10, 10), au.make(rot=45, sx=2))
        self.assertAlmostEqual(m[0] * 10 + m[2] * 10 + m[4], 10, places=6)
        self.assertAlmostEqual(m[1] * 10 + m[3] * 10 + m[5], 10, places=6)


class TimelineTests(unittest.TestCase):
    def test_track_interpolates_between_keys_and_ends_on_the_last_key(self):
        timeline = au.Timeline(10)
        timeline.track(5, 7, 5, {2: {"x": 0, "y": 0}, 6: {"x": 40, "y": -20}}, ease=au.linear)
        self.assertNotIn(5, timeline.frames[1])
        self.assertEqual(timeline.frames[2][5].matrix[4], 0)
        self.assertEqual(timeline.frames[4][5].matrix[4], 20)
        self.assertEqual(timeline.frames[6][5].matrix[5], -20)
        self.assertNotIn(5, timeline.frames[7])

    def test_alpha_interpolates(self):
        timeline = au.Timeline(6)
        timeline.track(1, 3, 1, {0: {"alpha": 256}, 4: {"alpha": 0}}, ease=au.linear)
        self.assertEqual([timeline.frames[i][1].alpha for i in range(5)], [256, 192, 128, 64, 0])

    def test_copy_clip_moves_scales_and_shifts_time(self):
        displays = [{3: (9, 1, (1, 1, 0, 0, 10, 20), None)}, {3: (9, 1, (1, 1, 0, 0, 12, 20), None)}]
        timeline = au.Timeline(8)
        timeline.copy_clip(displays, 0, 1, start=3, transform=au.make(100, 0, 0.5), depth_base=20)
        item = timeline.frames[4][23]
        self.assertEqual(item.char_id, 9)
        self.assertAlmostEqual(item.matrix[0], 0.5)
        self.assertAlmostEqual(item.matrix[4], 100 + 0.5 * 12)
        self.assertNotIn(23, timeline.frames[2])

    def test_copy_clip_fades_out_to_the_end_of_the_section(self):
        displays = [{1: (9, 1, (1, 1, 0, 0, 0, 0), None)}] * 5
        timeline = au.Timeline(5)
        timeline.copy_clip(displays, 0, 4, start=0, fade_from=2)
        self.assertEqual([timeline.frames[i][1].alpha for i in (0, 2, 3, 4)], [256, 256, 128, 0])

    def test_move_all_uses_the_frame_number(self):
        timeline = au.Timeline(3)
        for frame in range(3):
            timeline.set_item(frame, 2, au.Item(4, 2, au.IDENTITY))
        timeline.move_all([2], lambda frame: au.make(frame * 10, 0))
        self.assertEqual([timeline.frames[i][2].matrix[4] for i in range(3)], [0, 10, 20])


class CompileTests(unittest.TestCase):
    def _timeline(self):
        timeline = au.Timeline(4)
        timeline.track(1, 7, 1, {0: {"x": 0}, 2: {"x": 20}}, ease=au.linear)
        timeline.anchor(1, '{"type":"wav","res":"hit"}')
        return timeline

    def test_a_depth_is_placed_once_then_moved_then_removed(self):
        tags = au.compile_section("boom", self._timeline())
        self.assertIsInstance(tags[0], sam.Label)
        self.assertEqual([p.char_id for p in tags if isinstance(p, sam.Place)], [7, 0, 0])
        self.assertEqual(sum(isinstance(t, sam.Remove) for t in tags), 1)
        self.assertEqual(sum(isinstance(t, sam.Show) for t in tags), 4)

    def test_replaying_the_tags_gives_back_the_timeline(self):
        frames = _state_after(au.compile_section("boom", self._timeline()))
        self.assertEqual(frames[0][1][0], 7)
        self.assertAlmostEqual(frames[1][1][2][4], 10)
        self.assertAlmostEqual(frames[2][1][2][4], 20)
        self.assertEqual(frames[3], {})

    def test_the_anchor_lands_before_its_frames_show(self):
        tags = au.compile_section("boom", self._timeline())
        shows = [i for i, t in enumerate(tags) if isinstance(t, sam.Show)]
        anchor = next(i for i, t in enumerate(tags) if isinstance(t, sam.Anchor))
        self.assertTrue(shows[0] < anchor < shows[1])

    def test_alpha_becomes_a_color_form_multiplier(self):
        timeline = au.Timeline(3)
        timeline.track(1, 7, 1, {0: {"alpha": 256}, 2: {"alpha": 0}}, ease=au.linear)
        place = [t for t in au.compile_section("x", timeline) if isinstance(t, sam.Place)][-1]
        self.assertEqual(place.color.mult[3], 0)

    def test_returning_to_opaque_resets_the_tint_on_the_client(self):
        timeline = au.Timeline(4)
        timeline.track(1, 7, 1, {0: {"alpha": 0}, 1: {"alpha": 256}, 3: {"alpha": 256}}, ease=au.linear)
        frames = _state_after(au.compile_section("x", timeline))
        self.assertEqual(frames[0][1][3].mult[3], 0)
        self.assertEqual(frames[1][1][3].mult, (256, 256, 256, 256))
        self.assertEqual(frames[2][1][3].mult, (256, 256, 256, 256))

    def test_output_survives_the_byte_format(self):
        animation = sam.Sam([sam.Handle(10, 10, 24.0, 4), sam.Image(7, "a.png")]
                            + au.compile_section("boom", self._timeline()) + [sam.End()])
        self.assertEqual(sam.loads(sam.dumps(animation)).tags, animation.tags)


class ReplaceTests(unittest.TestCase):
    def test_only_the_named_section_changes_and_images_and_end_stay(self):
        old = sam.Sam([sam.Handle(10, 10, 24.0, 3), sam.Label("a"), sam.Show(), sam.Label("b"),
                       sam.Image(5, "p.png"), sam.Show(), sam.Label("c"), sam.Show(), sam.End()])
        new = au.replace_section(old, "b", [sam.Label("b"), sam.Show(), sam.Show()])
        self.assertEqual([type(t).__name__ for t in new.tags],
                         ["Handle", "Label", "Show", "Image", "Label", "Show", "Show", "Label", "Show", "End"])
        self.assertEqual(new.sections()["a"], [0, 0])
        self.assertEqual(new.sections()["c"], [3, 3])

    def test_replacing_the_last_section_keeps_the_closing_end(self):
        old = sam.Sam([sam.Handle(10, 10, 24.0, 2), sam.Label("a"), sam.Show(), sam.Label("z"), sam.Show(),
                       sam.End()])
        new = au.replace_section(old, "z", [sam.Label("z"), sam.Show(), sam.Show()])
        self.assertIsInstance(new.tags[-1], sam.End)
        self.assertEqual(new.sections()["z"], [1, 2])

    def test_image_ids_pick_the_first_id_per_name(self):
        animation = sam.Sam([sam.Image(1, "a.png"), sam.Image(2, "a.png"), sam.Image(3, "b.png")])
        self.assertEqual(au.image_ids(animation), {"a.png": 1, "b.png": 3})


if __name__ == "__main__":
    unittest.main()
