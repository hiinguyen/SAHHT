"""tools/skill_sprites.py on synthetic sheets laid out like the ones the image AI returns."""

import unittest

from PIL import Image, ImageDraw

from tools import skill_sprites as ss

GREY = (200, 200, 200)


def _black_sheet(width=1800, height=2400):
    return Image.new("RGB", (width, height), (0, 0, 0))


class KeyBlackTests(unittest.TestCase):
    def test_black_is_transparent_and_bright_pixels_keep_their_color(self):
        image = Image.new("RGB", (3, 1))
        image.putdata([(0, 0, 0), (255, 128, 0), (60, 60, 60)])
        keyed = ss.key_black(image)
        self.assertEqual(keyed.getpixel((0, 0))[3], 0)
        self.assertEqual(keyed.getpixel((1, 0)), (255, 128, 0, 255))
        r, _g, _b, a = keyed.getpixel((2, 0))
        self.assertTrue(0 < a < 255)
        self.assertAlmostEqual(r * a / 255, 60, delta=3)   # over black it looks like the original

    def test_a_dim_color_keeps_its_hue_and_looks_the_same_over_black(self):
        r, g, _b, a = ss.key_black(Image.new("RGB", (1, 1), (30, 20, 10))).getpixel((0, 0))
        self.assertAlmostEqual(r * a / 255, 30, delta=3)
        self.assertAlmostEqual(g * a / 255, 20, delta=3)


class WatermarkTests(unittest.TestCase):
    def test_a_grey_sparkle_on_black_is_wiped_but_an_ember_stays(self):
        sheet = _black_sheet(1000, 1000)
        draw = ImageDraw.Draw(sheet)
        draw.polygon([(830, 860), (840, 880), (860, 890), (840, 900), (830, 920), (820, 900), (800, 890), (820, 880)],
                     fill=(120, 125, 130))
        draw.ellipse((860, 870, 868, 878), fill=(255, 120, 0))
        out = ss.erase_watermark(sheet, (0, 0, 0))
        self.assertEqual(out.getpixel((830, 890)), (0, 0, 0))
        self.assertEqual(out.getpixel((864, 874)), (255, 120, 0))

    def test_dark_armor_beside_a_sparkle_on_grey_is_kept(self):
        sheet = Image.new("RGB", (1000, 1000), GREY)
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((800, 870, 830, 900), fill=(120, 20, 30))     # a red boot
        draw.polygon([(850, 860), (860, 880), (880, 890), (860, 900), (850, 920), (840, 900), (820, 890), (840, 880)],
                     fill=(235, 235, 240))
        out = ss.erase_watermark(sheet, GREY)
        self.assertEqual(out.getpixel((815, 885)), (120, 20, 30))
        self.assertEqual(out.getpixel((850, 890)), GREY)


class ExplosionTests(unittest.TestCase):
    def _sheet(self, empty_cell=None):
        sheet = _black_sheet(1800, 2400)
        draw = ImageDraw.Draw(sheet)
        for index in range(6):
            if index == empty_cell:
                continue
            col, row = index % 3, index // 3
            cx, cy = col * 600 + 300, row * 1200 + 700
            size = 60 + 40 * index
            draw.ellipse((cx - size, cy - size, cx + size, cy + size), fill=(255, 160, 40))
        return sheet

    def test_six_frames_come_out_in_order_at_one_common_scale(self):
        frames = ss.extract_explosion(self._sheet())
        self.assertEqual(len(frames), 6)
        widths = [f.width for f in frames]
        self.assertEqual(max(widths), ss.EXPLOSION_WIDTH)
        self.assertEqual(widths, sorted(widths))

    def test_an_empty_cell_is_refused(self):
        with self.assertRaises(SystemExit):
            ss.extract_explosion(self._sheet(empty_cell=3))

    def test_a_frame_cut_by_the_cell_edge_fades_out_on_that_side(self):
        sheet = _black_sheet(1800, 2400)
        ImageDraw.Draw(sheet).rectangle((300, 600, 599, 800), fill=(255, 200, 100))   # touches the cell's right edge
        for index in range(1, 6):
            col, row = index % 3, index // 3
            ImageDraw.Draw(sheet).ellipse((col * 600 + 250, row * 1200 + 600, col * 600 + 350, row * 1200 + 700),
                                          fill=(255, 160, 40))
        first = ss.extract_explosion(sheet)[0]
        self.assertLess(first.getpixel((first.width - 2, first.height // 2))[3], 40)
        self.assertEqual(first.getpixel((first.width // 3, first.height // 2))[3], 255)


class MissileTests(unittest.TestCase):
    def _sheet(self, puffs=3):
        sheet = _black_sheet(1800, 2400)
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((100, 600, 700, 660), fill=(255, 220, 160))          # trail
        draw.rectangle((700, 590, 1200, 670), fill=(160, 20, 50))           # body
        for index in range(puffs):
            x = 200 + index * 500
            draw.ellipse((x, 1700, x + 200, 1850), fill=(255, 150, 50))
        draw.text((260, 2100), "(1)", fill=(255, 255, 255))
        return sheet

    def test_the_missile_body_is_the_rotation_centre_and_the_padding_is_empty(self):
        missile, _ = ss.extract_missile(self._sheet())
        body_end = round(missile.width / (2 * ss.MISSILE_PIVOT))     # the width before the padding was added
        row = missile.height // 2
        self.assertGreater(missile.getpixel((body_end - 3, row))[3], 0)
        self.assertEqual(missile.getpixel((missile.width - 2, row))[3], 0)

    def test_puffs_are_found_left_to_right_and_the_label_is_ignored(self):
        _, puffs = ss.extract_missile(self._sheet())
        self.assertEqual(len(puffs), ss.PUFF_COUNT)
        self.assertEqual(max(p.width for p in puffs), ss.PUFF_WIDTH)
        self.assertEqual([p.getpixel((p.width // 2, p.height // 2))[3] for p in puffs], [255, 255, 255])

    def test_too_few_puffs_are_refused(self):
        with self.assertRaises(SystemExit):
            ss.extract_missile(self._sheet(puffs=2))


class PoseTests(unittest.TestCase):
    def _sheet(self, poses=5):
        sheet = Image.new("RGB", (1800, 2400), GREY)
        draw = ImageDraw.Draw(sheet)
        boxes = [(200, 200, 500, 800), (1000, 150, 1300, 900),
                 (150, 1400, 450, 2100), (700, 1400, 1000, 2100), (1250, 1400, 1550, 2100)]
        for box in boxes[:poses]:
            draw.rectangle(box, fill=(150, 30, 40), outline=(20, 20, 30), width=6)
        return sheet

    def test_five_poses_in_two_rows_come_out_in_story_order_scaled_to_the_idle_height(self):
        poses = ss.extract_poses(self._sheet(), idle_height=100)
        self.assertEqual(len(poses), 5)
        hover = sum(poses[i].height for i in ss.HOVER_POSES) / len(ss.HOVER_POSES)
        self.assertAlmostEqual(hover, 100 * ss.POSE_SUPERSAMPLE, delta=3)
        self.assertGreater(poses[1].height, poses[0].height)   # the rise pose is the taller of the top row

    def test_a_missing_pose_is_refused(self):
        with self.assertRaises(SystemExit):
            ss.extract_poses(self._sheet(poses=4), idle_height=100)


if __name__ == "__main__":
    unittest.main()
