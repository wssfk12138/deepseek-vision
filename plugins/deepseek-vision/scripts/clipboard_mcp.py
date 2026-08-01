"""剪贴板图片 MCP 服务器：让 Codex 直接读取用户剪贴板中的图片。

用户截图（Win+Shift+S）或复制图片后，Codex 可调用 save_clipboard_image
把图片保存到本地，再交给 deepseek-vision 视觉模型分析。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

INBOX = Path(__file__).resolve().parent.parent / "images" / "inbox"

mcp = FastMCP(
    "clipboard-capture",
    instructions="从 Windows 剪贴板读取图片并保存到本地，供视觉分析工具使用。",
)


def _clipboard_image():
    if os.name != "nt":
        raise RuntimeError("剪贴板图片功能目前仅支持 Windows")
    from PIL import ImageGrab

    image = ImageGrab.grabclipboard()
    if image is None:
        raise RuntimeError("剪贴板中没有图片，请先截图（Win+Shift+S）或复制一张图片")
    return image


@mcp.tool()
def save_clipboard_image(directory: str | None = None) -> str:
    """将剪贴板中的图片保存为 PNG，返回文件路径。截图或复制图片后调用。

    Args:
        directory: 可选，保存目录；默认使用插件 images/inbox 收件箱。
    """
    image = _clipboard_image()
    target = Path(directory) if directory else INBOX
    target.mkdir(parents=True, exist_ok=True)
    out = target / f"clipboard_{time.strftime('%Y%m%d_%H%M%S')}.png"
    image.save(out, "PNG")
    return f"已保存: {out}（{image.size[0]} x {image.size[1]}）"


@mcp.tool()
def list_inbox_images(directory: str | None = None) -> str:
    """列出收件箱中最近保存的剪贴板图片。"""
    target = Path(directory) if directory else INBOX
    if not target.exists():
        return "收件箱为空"
    files = sorted(
        (p for p in target.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return "收件箱为空"
    return "\n".join(f"{p}（{p.stat().st_size} 字节）" for p in files)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
