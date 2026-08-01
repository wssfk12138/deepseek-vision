"""图片表格提取：用视觉模型把扫描页中的表格识别为结构化数据（JSON）。

用法:
    .venv\\Scripts\\python.exe scripts\\table_extract.py ^
        --pdf <扫描PDF> --pages "5,26,56" --out <输出目录>

输出 tables.json: {页码: {"tables": [{"rows": [[...], ...]}, ...]}}
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

from vision_config import ConfigError, resolve_config

EXTRACT_PROMPT = (
    "这是扫描书页。请把页面上所有表格提取为结构化数据，每个表格一个对象。"
    "要求：1) 保持行、列顺序；2) 空单元格用空字符串；3) 国际音标、声调符号、拼音等特殊符号原样保留；"
    "4) 表头与内容放在同一张表格里；5) 不要把表格外的正文文字放进表格。"
    "只输出 JSON：{\"tables\": [{\"rows\": [[\"单元格\", ...], ...]}, ...]}，没有表格时 tables 为空数组。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="图片表格视觉提取")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", required=True, help="页码，如 5,26-28")
    parser.add_argument("--out", required=True)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--model", default="")
    return parser.parse_args()


def parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        elif part:
            pages.append(int(part))
    return sorted(set(pages))


def extract_tables(
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
                    {"type": "text", "text": EXTRACT_PROMPT},
                ],
            }
        ],
        "max_tokens": 4096,
    }
    for attempt in (1, 2):
        try:
            resp = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=240,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            content = resp.json()["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.S)
            match = re.search(r"\{.*\}", content, flags=re.S)
            if not match:
                raise RuntimeError(f"未返回 JSON: {content[:120]}")
            return page_no, json.loads(match.group(0))
        except Exception as exc:
            if attempt == 2:
                return page_no, {"tables": [], "error": str(exc)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF 不存在: {pdf_path}", file=sys.stderr)
        return 2
    try:
        cfg = resolve_config()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    api_key = cfg["api_key"]
    model = args.model or cfg["model"]
    base_url = cfg["base_url"]

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
                    extract_tables, client, page_no, data,
                    api_key=api_key, model=model, base_url=base_url,
                ): page_no
                for page_no, data in rendered.items()
            }
            for future in as_completed(futures):
                page_no = futures[future]
                page_no, data = future.result()
                results[f"page_{page_no:03d}"] = data
                n = len(data.get("tables", []))
                print(f"第 {page_no} 页: {n} 个表格" + (f"（错误: {data.get('error')}）" if data.get("error") else ""))

    (out_dir / "tables.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"输出: {out_dir / 'tables.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
