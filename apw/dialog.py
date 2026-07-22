"""图形化目录选择对话框，基于标准库 tkinter，不可用时回退为 None。"""

from __future__ import annotations

from pathlib import Path


def pick_directory(title: str, initial_dir: str | None = None) -> Path | None:
    """弹出系统文件夹选择对话框；无显示环境、tkinter 不可用或用户取消时返回 None。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        path = filedialog.askdirectory(title=title, initialdir=initial_dir, mustexist=True)
        return Path(path) if path else None
    except Exception:
        return None
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
