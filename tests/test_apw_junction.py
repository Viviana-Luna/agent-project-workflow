from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from apw.junction import create_junction, is_junction, read_junction, remove_junction


@unittest.skipUnless(os.name == "nt", "目录联接仅支持 Windows")
class JunctionTests(unittest.TestCase):
    def test_create_read_remove(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "目标目录"
            target.mkdir()
            (target / "apw.pyz").write_bytes(b"pyz")
            link = root / "current"
            create_junction(link, target)
            self.assertTrue(is_junction(link))
            self.assertEqual(read_junction(link), target)
            self.assertEqual((link / "apw.pyz").read_bytes(), b"pyz")
            remove_junction(link)
            self.assertFalse(link.exists())
            self.assertTrue(target.exists())
            self.assertTrue((target / "apw.pyz").exists())

    def test_swap_via_rename(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target_a = root / "target-a"
            target_b = root / "target-b"
            target_a.mkdir()
            target_b.mkdir()
            (target_a / "apw.pyz").write_bytes(b"a")
            (target_b / "apw.pyz").write_bytes(b"b")
            link = root / "current"
            create_junction(link, target_a)
            previous = root / "current.old"
            os.replace(link, previous)
            staging = root / "current.new"
            create_junction(staging, target_b)
            os.replace(staging, link)
            self.assertTrue(is_junction(link))
            self.assertEqual((link / "apw.pyz").read_bytes(), b"b")
            remove_junction(previous)
            self.assertTrue(target_a.exists())
            self.assertTrue(target_b.exists())

    def test_create_on_existing_raises(self) -> None:
        with TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            target.mkdir()
            with self.assertRaises(FileExistsError):
                create_junction(target, target)

    def test_remove_non_junction_raises(self) -> None:
        with TemporaryDirectory() as temp:
            directory = Path(temp) / "dir"
            directory.mkdir()
            with self.assertRaises(OSError):
                remove_junction(directory)


if __name__ == "__main__":
    unittest.main()
