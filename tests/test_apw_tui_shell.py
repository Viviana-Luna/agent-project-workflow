from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apw.shell import PATH_END, PATH_START, remove_path_profile, update_path_profile
from apw.tui import Choice, choose_one, select_many


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 42


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

    def test_numbered_multi_select_accepts_all(self) -> None:
        selected = select_many(
            "选择工作流 Skill",
            [Choice("init", "初始化"), Choice("todo", "执行 TODO")],
            input_stream=io.StringIO("all\n"),
            output_stream=io.StringIO(),
        )
        self.assertEqual(selected, ["init", "todo"])

    def test_numbered_single_select_uses_default(self) -> None:
        selected = choose_one(
            "选择操作",
            [Choice("install", "安装"), Choice("status", "状态")],
            "status",
            input_stream=io.StringIO("\n"),
            output_stream=io.StringIO(),
        )
        self.assertEqual(selected, "status")

    @unittest.skipUnless(os.name == "posix", "TTY 原始模式依赖 termios")
    def test_tty_multi_select_uses_carriage_return_and_correct_redraw_height(self) -> None:
        input_stream = TtyBuffer("\x1b[B\r")
        output_stream = TtyBuffer()
        with (
            mock.patch("termios.tcgetattr", return_value=[0]),
            mock.patch("termios.tcsetattr"),
            mock.patch("tty.setraw"),
        ):
            selected = select_many(
                "选择客户端",
                [Choice("codex", "Codex"), Choice("claude", "Claude Code")],
                {"codex", "claude"},
                input_stream=input_stream,
                output_stream=output_stream,
            )
        rendered = output_stream.getvalue()
        self.assertEqual(selected, ["codex", "claude"])
        self.assertIn("选择客户端\r\n", rendered)
        self.assertIn("Codex\r\n", rendered)
        self.assertIn("\x1b[3A", rendered)

    @unittest.skipUnless(os.name == "posix", "TTY 原始模式依赖 termios")
    def test_tty_single_select_redraws_without_diagonal_drift(self) -> None:
        input_stream = TtyBuffer("\x1b[B\r")
        output_stream = TtyBuffer()
        with (
            mock.patch("termios.tcgetattr", return_value=[0]),
            mock.patch("termios.tcsetattr"),
            mock.patch("tty.setraw"),
        ):
            selected = choose_one(
                "选择操作",
                [Choice("install", "安装"), Choice("status", "状态")],
                "install",
                input_stream=input_stream,
                output_stream=output_stream,
            )
        rendered = output_stream.getvalue()
        self.assertEqual(selected, "status")
        self.assertIn("选择操作\r\n", rendered)
        self.assertIn("安装\r\n", rendered)
        self.assertIn("\x1b[3A", rendered)

    @unittest.skipUnless(os.name == "nt", "Windows TTY 虚拟终端")
    def test_windows_tty_single_select_arrow(self) -> None:
        output = TtyBuffer()
        keys = iter([b"\xe0", b"P", b"\r"])  # 下移、回车
        with (
            mock.patch("apw.tui._enable_vt_output", return_value=True),
            mock.patch("msvcrt.getch", side_effect=lambda: next(keys)),
        ):
            selected = choose_one(
                "选择操作",
                [Choice("install", "安装"), Choice("status", "状态")],
                "install",
                input_stream=TtyBuffer(""),
                output_stream=output,
            )
        rendered = output.getvalue()
        self.assertEqual(selected, "status")
        self.assertIn("选择操作\r\n", rendered)
        self.assertIn("安装\r\n", rendered)
        self.assertIn("\x1b[3A", rendered)

    @unittest.skipUnless(os.name == "nt", "Windows TTY 虚拟终端")
    def test_windows_tty_multi_select(self) -> None:
        output = TtyBuffer()
        keys = iter([b"\xe0", b"P", b" ", b"\r"])  # 下移、空格、回车
        with (
            mock.patch("apw.tui._enable_vt_output", return_value=True),
            mock.patch("msvcrt.getch", side_effect=lambda: next(keys)),
        ):
            selected = select_many(
                "选择客户端",
                [Choice("codex", "Codex"), Choice("claude", "Claude Code")],
                {"codex"},
                input_stream=TtyBuffer(""),
                output_stream=output,
            )
        self.assertEqual(selected, ["codex", "claude"])
        self.assertIn("\x1b[3A", output.getvalue())

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
