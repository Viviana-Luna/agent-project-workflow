from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from apw.shell import PATH_END, PATH_START, remove_path_profile, update_path_profile
from apw.tui import Choice, choose_one, select_many


class TuiAndShellTests(unittest.TestCase):
    def test_numbered_multi_select(self) -> None:
        output = io.StringIO()
        selected = select_many(
            "选择客户端",
            [Choice("codex", "Codex"), Choice("claude", "Claude Code")],
            {"codex"},
            input_stream=io.StringIO("1,2\n"),
            output_stream=output,
        )
        self.assertEqual(selected, ["codex", "claude"])
        self.assertIn("输入编号", output.getvalue())

    def test_numbered_multi_select_rejects_invalid_index(self) -> None:
        with self.assertRaises(ValueError):
            select_many(
                "选择客户端",
                [Choice("codex", "Codex")],
                input_stream=io.StringIO("2\n"),
                output_stream=io.StringIO(),
            )

    def test_numbered_single_select_uses_default(self) -> None:
        selected = choose_one(
            "选择操作",
            [Choice("install", "安装"), Choice("status", "状态")],
            "status",
            input_stream=io.StringIO("\n"),
            output_stream=io.StringIO(),
        )
        self.assertEqual(selected, "status")

    def test_path_managed_block_preserves_other_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / ".zprofile"
            profile.write_text("export LANG=zh_CN.UTF-8\n", encoding="utf-8")
            update_path_profile(profile, root / ".local" / "bin")
            content = profile.read_text(encoding="utf-8")
            self.assertIn(PATH_START, content)
            self.assertIn(PATH_END, content)
            self.assertIn("export LANG", content)
            remove_path_profile(profile)
            self.assertEqual(profile.read_text(encoding="utf-8"), "export LANG=zh_CN.UTF-8\n")

    def test_path_block_quotes_special_home_characters(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / ".zprofile"
            update_path_profile(profile, Path(temp) / "带'引号" / "bin")
            content = profile.read_text(encoding="utf-8")
            self.assertIn("'\\''", content)
            self.assertIn(':"$PATH"', content)


if __name__ == "__main__":
    unittest.main()
