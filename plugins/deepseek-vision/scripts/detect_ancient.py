"""古籍影印区域检测：识别扫描书页中的古籍/经典原文图片区域。

用法:
    .venv\\Scripts\\python.exe scripts\\detect_ancient.py ^
        --pdf <扫描PDF> --pages "11-13,20-22" --out <输出目录>

输出 ancient_regions.json:
    {页码: {"whole_ancient": bool, "regions": [[x1,y1,x2,y2], ...]}}
坐标均为相对原图的 0-1 比例（左上角为原点）。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from dotenv import load_dotenv

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

DETECT_PROMPT = (
    "这是扫描的考研辅导书页。请判断："
    "1) 本页是否整体为古籍影印/经典原文内容（竖排或繁体古书排版、影印图片，而非普通横排印刷文字）；"
    "2) 页面中是否存在独立的古籍影印区域（经典文言文原文以图片/影印形式呈现，与普通印刷正文可明显区分）。"
    "只输出 JSON：{\"whole_ancient\": true 或 false, \"regions\": [[x1,y1,x2,y2], ...]}，"
    "坐标为相对原图的 0-1 比例（左上角为原点），没有区域则为空数组。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="古籍影印区域检测")
    parser.add_argument("--pdf", required=True, help="扫描 PDF 路径")
    parser.add_argument("--pages", required=True, help="待检测页码，如 11-13,20-22,28-31")
    parser.add_argument("--out", required=True, help="输出目录（写 ancient_regions.json）")
    parser.add_argument("--dpi", type=int, default=200, help="渲染分辨率（默认 200）")
    parser.add_argument("--workers", type=int, default=3, help="并行检测数（默认 3）")
    parser.add_argument("--model", default="", help="视觉模型（默认读 .env）")
    return parser.parse_args()


def parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def detect_page(
    client: httpx.Client,
    page_no: int,
    image_bytes: bytes,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> tuple[int, dict]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": DETECT_PROMPT},
                ],
            }
        ],
        "max_tokens": 512,
    }
    for attempt in (1, 2):
        try:
            resp = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            content = resp.json()["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.S)
            match = re.search(r"\{.*\}", content, flags=re.S)
            if not match:
                raise RuntimeError(f"未返回 JSON: {content[:120]}")
            data = json.loads(match.group(0))
            return page_no, {
                "whole_ancient": bool(data.get("whole_ancient", False)),
                "regions": [list(map(float, r)) for r in data.get("regions", [])],
            }
        except Exception as exc:
            if attempt == 2:
                raise


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(PLUGIN_ROOT / ".env")
    args = parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF 不存在: {pdf_path}", file=sys.stderr)
        return 2
    api_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if not api_key:
        print("未找到 SILICONFLOW_API_KEY", file=sys.stderr)
        return 2
    model = args.model or os.environ.get("SILICONFLOW_MODEL", "Qwen/Qwen3-VL-32B-Instruct")
    base_url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")

    pages = parse_pages(args.pages)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf = pdfium.PdfDocument(str(pdf_path))
    rendered: dict[int, bytes] = {}
    for page_no in pages:
        img = pdf[page_no - 1].render(scale=args.dpi / 72).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        rendered[page_no] = buf.getvalue()

    results: dict[str, dict] = {}
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    detect_page,
                    client,
                    page_no,
                    image_bytes,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                ): page_no
                for page_no, image_bytes in rendered.items()
            }
            for future in as_completed(futures):
                page_no = futures[future]
                try:
                    _, data = future.result()
                except Exception as exc:
                    data = {"whole_ancient": False, "regions": [], "error": str(exc)}
                results[f"page_{page_no:03d}"] = data
                kind = "整页古籍" if data.get("whole_ancient") else (
                    f"古籍区域 x{len(data.get('regions', []))}" if data.get("regions") else "无"
                )
                print(f"第 {page_no} 页: {kind}")

    (out_dir / "ancient_regions.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    whole = [p for p, d in results.items() if d.get("whole_ancient")]
    partial = [p for p, d in results.items() if d.get("regions")]
    print(f"\n完成: 整页古籍 {len(whole)} 页，含局部古籍区域 {len(partial)} 页")
    print(f"输出: {out_dir / 'ancient_regions.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
