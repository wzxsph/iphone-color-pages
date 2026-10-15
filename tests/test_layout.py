import unittest

from iphone_color_pages.colors import PALETTE, LABELS
from iphone_color_pages.layout import (LayoutError, build_plan, canonical, fingerprint,
                                       icon_counter, members, safe_app_id, verify_layout)


class LayoutTests(unittest.TestCase):
    def test_folder_pages_do_not_lose_the_first_icon(self):
        self.assertEqual(members(["Reading", ["org.example.a", "org.example.b"], ["org.example.c"]]),
                         ["org.example.a", "org.example.b", "org.example.c"])

    def test_flat_and_nested_single_page_are_equivalent(self):
        a = [[], [["Folder", "a", "b"]]]
        b = [[], [["Folder", ["a", "b"]]]]
        self.assertEqual(canonical(a), canonical(b))
        self.assertTrue(verify_layout(a, b)["ok"])

    def test_page_boundaries_affect_stale_fingerprint(self):
        a = [[], [["Folder", ["a", "b"]]]]
        b = [[], [["Folder", ["a"], ["b"]]]]
        self.assertNotEqual(fingerprint(a), fingerprint(b))
        self.assertFalse(verify_layout(a, b)["ok"])

    def test_unknown_or_mixed_layouts_are_rejected(self):
        for bad in ([], [[]], [[], [{"widget": "unknown"}]], [[], [["Folder", "a", ["b"]]]],
                    [[], [["Folder", [["nested", "a"]]]]], [[], [""]]):
            with self.subTest(bad=bad), self.assertRaises(LayoutError):
                canonical(bad)

    def test_duplicate_occurrences_dock_webclips_and_overflow_are_preserved(self):
        blue = [f"org.example.blue{i}" for i in range(35)]
        source = [["org.example.dock"], [blue[0], blue[0], "/"], [["Old", *blue[1:]]]]
        colors = {bid: "blue" for bid in blue}
        colors["/"] = "orange"
        result, summary = build_plan(source, colors, PALETTE, LABELS)
        self.assertEqual(result[0], source[0])
        self.assertEqual(icon_counter(result[1:]), icon_counter(source[1:]))
        self.assertEqual(icon_counter(result[1:])[blue[0]], 2)
        self.assertEqual(len(result), 3)
        self.assertEqual([s["color"] for s in summary], ["orange", "blue"])
        self.assertEqual(len(result[2]), 24)
        folder = result[2][-1]
        self.assertEqual([len(p) for p in folder[1:]], [9, 4])

    def test_color_and_capacity_errors(self):
        for mapping, slots in (({}, 24), ({"a": "nonsense"}, 24), ({"a": "blue"}, 1)):
            with self.subTest(mapping=mapping, slots=slots), self.assertRaises(LayoutError):
                build_plan([[], ["a"]], mapping, PALETTE, LABELS, slots=slots)
        with self.assertRaises(LayoutError):
            build_plan([[], []], {}, PALETTE, LABELS)

    def test_verifier_catches_library_insertion_and_reordering(self):
        expected = [["dock"], ["a", "b"]]
        added = [["dock"], ["a", "b", "extra"]]
        report = verify_layout(expected, added)
        self.assertFalse(report["ok"])
        self.assertEqual(report["added"], {"extra": 1})
        self.assertTrue(report["dock_matches"])
        report = verify_layout(expected, [["dock"], ["b", "a"]])
        self.assertFalse(report["ok"])
        self.assertFalse(report["missing"])
        self.assertFalse(report["added"])

    def test_export_filename_safety_and_legacy_ids(self):
        self.assertTrue(safe_app_id("CtClient"))
        self.assertTrue(safe_app_id("org.example.app-name"))
        for value in ("/", "../escape", "https://example.org", ".", "a/../../b", ""):
            self.assertFalse(safe_app_id(value))


if __name__ == "__main__":
    unittest.main()
