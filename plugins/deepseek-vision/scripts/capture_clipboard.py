"""把 Windows 剪贴板中的图片保存到插件收件箱，供视觉分析使用。

用法:
    python scripts/capture_clipboard.py [保存目录]

配合截图（Win+Shift+S）或“复制图片”使用：先复制图片，再运行本脚本，
即可得到一个可被视觉模型分析的本地 PNG 文件。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def default_inbox() -> Path:
    return Path(__file__).resolve().parent.parent / "images" / "inbox"


def grab_clipboard_image():
    if os.name != "nt":
        raise RuntimeError("剪贴板图片功能目前仅支持 Windows")
    from PIL import ImageGrab

    image = ImageGrab.grabclipboard()
    if image is None:
        raise RuntimeError("剪贴板中没有图片，请先截图（Win+Shift+S）或复制一张图片")
    return image


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_inbox()
    target.mkdir(parents=True, exist_ok=True)
    image = grab_clipboard_image()
    out = target / f"clipboard_{time.strftime('%Y%m%d_%H%M%S')}.png"
    image.save(out, "PNG")
    print(f"已保存剪贴板图片: {out}")
    print(f"尺寸: {image.size[0]} x {image.size[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
