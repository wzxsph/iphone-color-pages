"""Behavioral checks for local image analysis and review artifacts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from iphone_color_pages.colors import (
    PALETTE,
    classify_icon,
    render_contact_sheets,
    render_plan_preview,
)


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, name, image):
        path = self.directory / f"{name}.png"
        image.save(path)
        return path

    def test_solid_color_families_and_dark_blue(self):
        samples = {
            "red": (236, 35, 40), "orange": (246, 127, 24),
            "yellow": (250, 218, 40), "green": (37, 166, 65),
            "teal": (28, 181, 177), "blue": (11, 29, 89),
            "purple": (143, 64, 211), "pink": (230, 65, 151),
            "black": (12, 13, 15), "gray": (141, 143, 146),
            "white": (250, 250, 250),
        }
        for expected, rgb in samples.items():
            with self.subTest(expected=expected):
                self.assertEqual(classify_icon(self.save(expected, Image.new("RGB", (64, 64), rgb))), expected)

    def test_transparent_padding_does_not_dilute_logo(self):
        image = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(image).ellipse((30, 30, 90, 90), fill=(220, 25, 40, 255))
        self.assertEqual(classify_icon(self.save("transparent", image)), "red")
        self.assertEqual(classify_icon(self.save("empty", Image.new("RGBA", (20, 20)))), "white")

    def test_dark_slate_is_neutral_but_gold_and_rose_keep_their_hues(self):
        samples = {"slate": ((30, 31, 45), "black"),
                   "gold": ((255, 210, 44), "yellow"),
                   "rose": ((234, 37, 69), "pink")}
        for name, (rgb, expected) in samples.items():
            with self.subTest(name=name):
                self.assertEqual(classify_icon(self.save(name, Image.new("RGB", (40, 40), rgb))), expected)

    def test_white_background_with_small_colored_logo_stays_white(self):
        image = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(image).rectangle((30, 30, 70, 70), fill="#2675e8")
        self.assertEqual(classify_icon(self.save("white-logo", image)), "white")

    def test_equal_separated_color_regions_are_multicolor(self):
        image = Image.new("RGB", (120, 90), "red")
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 0, 79, 89), fill="#14c036")
        draw.rectangle((80, 0, 119, 89), fill="#2549ed")
        self.assertEqual(classify_icon(self.save("three-colors", image)), "multicolor")

    def test_single_dominant_hue_wins_over_small_other_hue(self):
        image = Image.new("RGB", (100, 100), "#2664e9")
        ImageDraw.Draw(image).rectangle((0, 0, 18, 99), fill="#ec2727")
        self.assertEqual(classify_icon(self.save("dominant", image)), "blue")

    def test_missing_and_invalid_images_are_reported(self):
        with self.assertRaises(OSError):
            classify_icon(self.directory / "missing.png")
        invalid = self.directory / "invalid.png"
        invalid.write_text("not an image")
        with self.assertRaises(OSError):
            classify_icon(invalid)

    def test_review_sheets_paginate_and_handle_missing_or_webclip_icons(self):
        self.save("com.example.app", Image.new("RGB", (80, 80), "red"))
        records = [{"id": "com.example.app", "name": "A long app name " * 20,
                    "kind": "app", "color": "red"}]
        records += [{"id": f"missing.{index}", "name": "中文名称和表情 🙂" * 10,
                     "kind": "app", "color": PALETTE[index % len(PALETTE)]}
                    for index in range(63)]
        records.append({"id": "https://example.com", "name": "网站",
                        "kind": "webclip", "color": "white"})
        output = self.directory / "sheets"
        # Simulate a machine without Chinese fonts as well as missing image files.
        fallback = ImageFont.load_default()
        with patch("iphone_color_pages.colors._font", return_value=(fallback, False)):
            paths = render_contact_sheets(records, self.directory, output)
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0].name, "icons-001.png")
        with Image.open(paths[0]) as first, Image.open(paths[1]) as last:
            self.assertGreater(first.height, last.height)
            self.assertEqual(first.width, last.width)
            self.assertIsNone(first.verify())
        self.assertEqual(render_contact_sheets([], self.directory, output), [])

    def test_plan_preview_supports_flat_and_nested_folders_and_many_pages(self):
        self.save("red.app", Image.new("RGB", (30, 30), "red"))
        pages = [
            ["red.app", ["中文文件夹", ["red.app", "missing.app"]]],
            [["Flat folder", "red.app", "missing.app"]],
        ] + [[] for _ in range(10)]
        destination = self.directory / "nested" / "preview.png"
        fallback = ImageFont.load_default()
        with patch("iphone_color_pages.colors._font", return_value=(fallback, False)):
            render_plan_preview([["red.app"], *pages], {"red.app": "red"}, self.directory, destination)
        with Image.open(destination) as preview:
            self.assertGreater(preview.width, 1000)
            self.assertGreater(preview.height, 1000)
            preview.verify()

    def test_preview_rejects_malformed_top_level_layout(self):
        with self.assertRaises(ValueError):
            render_plan_preview(["app"], {}, self.directory, self.directory / "preview.png")


if __name__ == "__main__":
    unittest.main()
