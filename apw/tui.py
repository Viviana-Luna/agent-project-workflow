"""不依赖第三方库的终端交互组件。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    description: str = ""


def terminal_capable(input_stream: TextIO, output_stream: TextIO) -> bool:
    if not (input_stream.isatty() and output_stream.isatty()):
        return False
    if os.name == "nt":
        return _enable_vt_output(output_stream)
    return True


def _enable_vt_output(output_stream: TextIO) -> bool:
    """Windows：启用控制台虚拟终端处理以支持 ANSI 转义；失败则回退编号菜单。"""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        std_output_handle = -11
        enable_virtual_terminal_processing = 0x0004
        handle = kernel32.GetStdHandle(std_output_handle)
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if not kernel32.SetConsoleMode(handle, mode.value | enable_virtual_terminal_processing):
            return False
        return True
    except Exception:
        return False


def _read_key_windows() -> str:
    """Windows：用 msvcrt 读取单键，映射为方向/确认/选择/退出动作。"""
    import msvcrt

    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):
        ext = msvcrt.getch().decode("ascii", "ignore")
        return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(ext, "")
    if ch == b"\r":
        return "enter"
    if ch == b" ":
        return "space"
    if ch == b"\x03":
        raise KeyboardInterrupt
    return ch.decode("utf-8", "ignore").lower()


def select_many(
    title: str,
    choices: list[Choice],
    selected: set[str] | None = None,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> list[str]:
    if not choices:
        return []
    initial = set(selected or set())
    if terminal_capable(input_stream, output_stream):
        if os.name == "nt":
            return _select_many_tty_windows(title, choices, initial, output_stream)
        return _select_many_tty(title, choices, initial, input_stream, output_stream)
    output_stream.write(f"{title}\n")
    for index, choice in enumerate(choices, 1):
        marker = "*" if choice.value in initial else " "
        suffix = f" — {choice.description}" if choice.description else ""
        output_stream.write(f"  {index}. [{marker}] {choice.label}{suffix}\n")
    output_stream.write("输入编号，使用逗号分隔；直接回车保留默认选择：")
    output_stream.flush()
    value = input_stream.readline()
    if value == "":
        raise EOFError("终端输入已结束")
    value = value.strip()
    if not value:
        return [choice.value for choice in choices if choice.value in initial]
    indexes = _parse_indexes(value, len(choices))
    return [choices[index - 1].value for index in indexes]


def choose_one(
    title: str,
    choices: list[Choice],
    default: str | None = None,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> str:
    if not choices:
        raise ValueError("没有可选项")
    if terminal_capable(input_stream, output_stream):
        if os.name == "nt":
            return _choose_one_tty_windows(title, choices, default, output_stream)
        return _choose_one_tty(title, choices, default, input_stream, output_stream)
    output_stream.write(f"{title}\n")
    default_index = 1
    for index, choice in enumerate(choices, 1):
        if choice.value == default:
            default_index = index
        marker = "*" if choice.value == default else " "
        suffix = f" — {choice.description}" if choice.description else ""
        output_stream.write(f"  {index}. [{marker}] {choice.label}{suffix}\n")
    output_stream.write(f"输入一个编号；直接回车选择 {default_index}：")
    output_stream.flush()
    value = input_stream.readline()
    if value == "":
        raise EOFError("终端输入已结束")
    value = value.strip()
    index = default_index if not value else _parse_indexes(value, len(choices))[0]
    if "," in value or "，" in value:
        raise ValueError("只能选择一个编号")
    return choices[index - 1].value


def prompt(
    label: str,
    default: str | None = None,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> str:
    suffix = f" [{default}]" if default else ""
    output_stream.write(f"{label}{suffix}：")
    output_stream.flush()
    value = input_stream.readline()
    if value == "":
        raise EOFError("终端输入已结束")
    value = value.strip()
    return value or (default or "")


def confirm(
    message: str,
    default: bool = False,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    value = prompt(f"{message} {suffix}", input_stream=input_stream, output_stream=output_stream).lower()
    if not value:
        return default
    return value in {"y", "yes", "是", "确认"}


def _parse_indexes(value: str, maximum: int) -> list[int]:
    indexes: list[int] = []
    for item in value.replace("，", ",").split(","):
        item = item.strip()
        if not item.isdigit():
            raise ValueError(f"不是有效编号：{item!r}")
        index = int(item)
        if index < 1 or index > maximum:
            raise ValueError(f"编号超出范围：{index}")
        if index not in indexes:
            indexes.append(index)
    return indexes


def _select_many_tty(
    title: str,
    choices: list[Choice],
    selected: set[str],
    input_stream: TextIO,
    output_stream: TextIO,
) -> list[str]:
    import termios
    import tty

    current = 0
    descriptor = input_stream.fileno()
    previous = termios.tcgetattr(descriptor)
    output_stream.write("\x1b[?25l")
    try:
        tty.setraw(descriptor)
        while True:
            output_stream.write(f"\r\x1b[2K{title}\r\n")
            for index, choice in enumerate(choices):
                cursor = ">" if index == current else " "
                marker = "x" if choice.value in selected else " "
                suffix = f" — {choice.description}" if choice.description else ""
                output_stream.write(f"\x1b[2K {cursor} [{marker}] {choice.label}{suffix}\r\n")
            output_stream.write("\x1b[2K↑↓ 移动  Space 选择  Enter 继续  Q 退出")
            output_stream.flush()
            key = input_stream.read(1)
            if key == "\x1b":
                following = input_stream.read(2)
                if following == "[A":
                    current = (current - 1) % len(choices)
                elif following == "[B":
                    current = (current + 1) % len(choices)
            elif key == " ":
                value = choices[current].value
                if value in selected:
                    selected.remove(value)
                else:
                    selected.add(value)
            elif key in {"\r", "\n"}:
                break
            elif key.lower() == "q" or key == "\x03":
                raise KeyboardInterrupt
            output_stream.write(f"\x1b[{len(choices) + 1}A")
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        output_stream.write("\x1b[?25h\n")
        output_stream.flush()
    return [choice.value for choice in choices if choice.value in selected]


def _choose_one_tty(
    title: str,
    choices: list[Choice],
    default: str | None,
    input_stream: TextIO,
    output_stream: TextIO,
) -> str:
    import termios
    import tty

    current = next((index for index, choice in enumerate(choices) if choice.value == default), 0)
    descriptor = input_stream.fileno()
    previous = termios.tcgetattr(descriptor)
    output_stream.write("\x1b[?25l")
    try:
        tty.setraw(descriptor)
        while True:
            output_stream.write(f"\r\x1b[2K{title}\r\n")
            for index, choice in enumerate(choices):
                cursor = ">" if index == current else " "
                suffix = f" — {choice.description}" if choice.description else ""
                output_stream.write(f"\x1b[2K {cursor} {choice.label}{suffix}\r\n")
            output_stream.write("\x1b[2K↑↓ 移动  Enter 选择  Q 退出")
            output_stream.flush()
            key = input_stream.read(1)
            if key == "\x1b":
                following = input_stream.read(2)
                if following == "[A":
                    current = (current - 1) % len(choices)
                elif following == "[B":
                    current = (current + 1) % len(choices)
            elif key in {"\r", "\n"}:
                return choices[current].value
            elif key.lower() == "q" or key == "\x03":
                raise KeyboardInterrupt
            output_stream.write(f"\x1b[{len(choices) + 1}A")
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        output_stream.write("\x1b[?25h\n")
        output_stream.flush()


def _select_many_tty_windows(
    title: str,
    choices: list[Choice],
    selected: set[str],
    output_stream: TextIO,
) -> list[str]:
    current = 0
    output_stream.write("\x1b[?25l")
    try:
        while True:
            output_stream.write(f"\r\x1b[2K{title}\r\n")
            for index, choice in enumerate(choices):
                cursor = ">" if index == current else " "
                marker = "x" if choice.value in selected else " "
                suffix = f" - {choice.description}" if choice.description else ""
                output_stream.write(f"\x1b[2K {cursor} [{marker}] {choice.label}{suffix}\r\n")
            output_stream.write("\x1b[2K↑↓ 移动  Space 选择  Enter 继续  Q 退出")
            output_stream.flush()
            key = _read_key_windows()
            if key == "up":
                current = (current - 1) % len(choices)
            elif key == "down":
                current = (current + 1) % len(choices)
            elif key == "space":
                value = choices[current].value
                if value in selected:
                    selected.remove(value)
                else:
                    selected.add(value)
            elif key == "enter":
                break
            elif key == "q":
                raise KeyboardInterrupt
            output_stream.write(f"\x1b[{len(choices) + 1}A")
    finally:
        output_stream.write("\x1b[?25h\n")
        output_stream.flush()
    return [choice.value for choice in choices if choice.value in selected]


def _choose_one_tty_windows(
    title: str,
    choices: list[Choice],
    default: str | None,
    output_stream: TextIO,
) -> str:
    current = next((index for index, choice in enumerate(choices) if choice.value == default), 0)
    output_stream.write("\x1b[?25l")
    try:
        while True:
            output_stream.write(f"\r\x1b[2K{title}\r\n")
            for index, choice in enumerate(choices):
                cursor = ">" if index == current else " "
                suffix = f" - {choice.description}" if choice.description else ""
                output_stream.write(f"\x1b[2K {cursor} {choice.label}{suffix}\r\n")
            output_stream.write("\x1b[2K↑↓ 移动  Enter 选择  Q 退出")
            output_stream.flush()
            key = _read_key_windows()
            if key == "up":
                current = (current - 1) % len(choices)
            elif key == "down":
                current = (current + 1) % len(choices)
            elif key == "enter":
                return choices[current].value
            elif key == "q":
                raise KeyboardInterrupt
            output_stream.write(f"\x1b[{len(choices) + 1}A")
    finally:
        output_stream.write("\x1b[?25h\n")
        output_stream.flush()
