"""tools/patch_assets.py: replace entries of an APK and keep everything else as it was."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import patch_assets

SIGNATURE_NAMES = {"META-INF/MANIFEST.MF", "META-INF/CERT.SF", "META-INF/CERT.RSA"}


def _apk(path: Path):
    with zipfile.ZipFile(path, "w") as z:
        for name, data, method in (("assets/a.sam", b"old sam", zipfile.ZIP_DEFLATED),
                                   ("assets/a-hd.pvr.ccz", b"old atlas", zipfile.ZIP_STORED),
                                   ("assets/keep.bin", b"\x00\x01\x02", zipfile.ZIP_STORED),
                                   ("META-INF/MANIFEST.MF", b"manifest", zipfile.ZIP_DEFLATED),
                                   ("META-INF/CERT.SF", b"sf", zipfile.ZIP_DEFLATED),
                                   ("META-INF/CERT.RSA", b"rsa", zipfile.ZIP_DEFLATED),
                                   ("META-INF/androidx.core.version", b"1", zipfile.ZIP_DEFLATED)):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = method
            z.writestr(info, data)


class ReplaceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src, self.dst = self.root / "in.apk", self.root / "out.apk"
        _apk(self.src)

    def test_named_entries_change_and_the_rest_keeps_its_bytes_and_compression(self):
        patch_assets.replace_entries(self.src, self.dst, {"assets/a.sam": b"new sam", "assets/a-hd.pvr.ccz": b"new"})
        with zipfile.ZipFile(self.src) as old, zipfile.ZipFile(self.dst) as new:
            self.assertEqual(new.read("assets/a.sam"), b"new sam")
            self.assertEqual(new.read("assets/a-hd.pvr.ccz"), b"new")
            self.assertEqual(new.read("assets/keep.bin"), old.read("assets/keep.bin"))
            for name in ("assets/a.sam", "assets/a-hd.pvr.ccz", "assets/keep.bin"):
                self.assertEqual(new.getinfo(name).compress_type, old.getinfo(name).compress_type)
            kept = [n for n in old.namelist() if n not in SIGNATURE_NAMES]
            self.assertEqual(new.namelist(), kept)

    def test_old_signature_files_are_dropped_but_other_meta_inf_entries_stay(self):
        patch_assets.replace_entries(self.src, self.dst, {"assets/a.sam": b"x"})
        with zipfile.ZipFile(self.dst) as new:
            names = set(new.namelist())
        self.assertFalse(names & SIGNATURE_NAMES)
        self.assertIn("META-INF/androidx.core.version", names)

    def test_an_entry_that_is_not_in_the_apk_is_refused_and_nothing_is_written(self):
        with self.assertRaises(ValueError):
            patch_assets.replace_entries(self.src, self.dst, {"assets/nope.sam": b"x"})
        self.assertFalse(self.dst.exists())

    def test_output_may_not_overwrite_the_input(self):
        with self.assertRaises(ValueError):
            patch_assets.replace_entries(self.src, self.src, {"assets/a.sam": b"x"})

    def test_pairs_are_entry_equals_file(self):
        path = self.root / "f.bin"
        path.write_bytes(b"data")
        self.assertEqual(patch_assets.parse_replacements(["assets/x=%s" % path]), {"assets/x": b"data"})
        for bad in ("no-equals", "=file", "entry="):
            with self.assertRaises(ValueError):
                patch_assets.parse_replacements([bad])


if __name__ == "__main__":
    unittest.main()
