"""扫描版 PDF 批量 OCR 转文本（水印感知）。

用法:
    .venv\\Scripts\\python.exe scripts\\batch_ocr.py <PDF路径> [--out 输出目录]

流程: PDF 分页渲染为 PNG → 逐页调用视觉模型 OCR（可并行）→ 输出每页 txt 与合并文本。
默认提示词会忽略斜体水印并推断被遮挡文字。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pypdfium2 as pdfium

from vision_config import ConfigError, resolve_config

DEFAULT_PROMPT = (
    "这是扫描版教材书页，页面上有斜体水印覆盖部分文字。"
    "请忽略水印，逐字提取正文全部文字，保持段落顺序和原始排版结构；"
    "被水印遮挡的文字请根据上下文推断补全，不确定处用[?]标记。"
    "只输出提取的正文文字，不要任何解释、前缀或额外内容。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="扫描版 PDF 批量 OCR 转文本")
    parser.add_argument("pdf", help="扫描版 PDF 路径")
    parser.add_argument("--out", help="输出目录（默认: PDF 同目录下的 <文件名>_ocr）")
    parser.add_argument("--start", type=int, default=1, help="起始页码（1 起，默认 1）")
    parser.add_argument("--end", type=int, default=0, help="结束页码（默认到最后）")
    parser.add_argument("--dpi", type=int, default=200, help="渲染分辨率（默认 200）")
    parser.add_argument("--workers", type=int, default=3, help="并行 OCR 数（默认 3）")
    parser.add_argument("--model", default="", help="视觉模型（默认读 .env 的 MCP_OCR_MODEL）")
    parser.add_argument("--base-url", default="", help="OpenAI 兼容 API 地址（默认读 .env 的 MCP_OCR_BASE_URL）")
    parser.add_argument("--api-key", default="", help="API Key（默认读 .env 的 MCP_OCR_API_KEY）")
    parser.add_argument("--max-tokens", type=int, default=4096, help="单页最大输出 token（默认 4096）")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="自定义 OCR 提示词")
    parser.add_argument(
        "--classify",
        action="store_true",
        help="在每页输出末尾标记页面类型 [PAGE_TYPE:text|image]（古籍/图片页为 image）",
    )
    return parser.parse_args()


def render_pages(pdf_path: Path, start: int, end: int, dpi: int) -> list[tuple[int, bytes]]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    total = len(pdf)
    pages = list(range(start, min(end, total) + 1))
    rendered: list[tuple[int, bytes]] = []
    for idx in pages:
        img = pdf[idx - 1].render(scale=dpi / 72).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        rendered.append((idx, buf.getvalue()))
    return rendered


def ocr_page(
    client: httpx.Client,
    page_no: int,
    image_bytes: bytes,
    *,
    model: str,
    api_key: str,
    base_url: str,
    prompt: str,
    max_tokens: int,
    classify: bool,
) -> tuple[int, str, dict]:
    final_prompt = prompt
    if classify:
        final_prompt = (
            prompt
            + "\n另外，请在输出末尾单独一行标记页面类型：若本页以古籍影印、手写、图片或复杂表格为主（适合整页以图片形式留存），输出 [PAGE_TYPE:image]；否则输出 [PAGE_TYPE:text]。"
        )
    b64 = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": final_prompt},
                ],
            }
        ],
        "max_tokens": max_tokens,
    }
    started = time.time()
    for attempt in (1, 2):
        try:
            resp = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            page_type = "text"
            marker = re.search(r"\[PAGE_TYPE:(\w+)\]", text)
            if marker:
                page_type = marker.group(1)
                text = text.replace(marker.group(0), "").rstrip()
            return page_no, text, {"usage": usage, "seconds": round(time.time() - started, 1), "page_type": page_type}
        except Exception as exc:
            if attempt == 2:
                raise
            time.sleep(2)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF 不存在: {pdf_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out) if args.out else pdf_path.parent / f"{pdf_path.stem}_ocr"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        cfg = resolve_config()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    api_key = args.api_key or cfg["api_key"]
    model = args.model or cfg["model"]
    base_url = args.base_url or cfg["base_url"]

    pdf = pdfium.PdfDocument(str(pdf_path))
    total = len(pdf)
    end = args.end if args.end else total
    if args.start < 1 or end > total or args.start > end:
        print(f"页码范围无效: {args.start}-{end}（共 {total} 页）", file=sys.stderr)
        return 1

    print(f"共 {total} 页，处理 {args.start}-{end} 页，模型 {model}，并行 {args.workers} ...")
    rendered = render_pages(pdf_path, args.start, end, args.dpi)

    stats: dict[str, object] = {}
    errors: list[int] = []
    merged_lines: list[str] = []
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    ocr_page,
                    client,
                    page_no,
                    image_bytes,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    prompt=args.prompt,
                    max_tokens=args.max_tokens,
                    classify=args.classify,
                ): page_no
                for page_no, image_bytes in rendered
            }
            for future in as_completed(futures):
                page_no = futures[future]
                try:
                    _, text, meta = future.result()
                except Exception as exc:
                    print(f"第 {page_no} 页失败: {exc}")
                    errors.append(page_no)
                    continue
                page_file = out_dir / f"page-{page_no:03d}.txt"
                page_file.write_text(text, encoding="utf-8")
                stats[f"page_{page_no:03d}"] = meta
                merged_lines.append(f"\n\n===== 第 {page_no} 页 =====\n\n{text}")
                usage = meta.get("usage", {})
                print(f"第 {page_no} 页 OK（{meta.get('page_type', '?')}，{usage.get('total_tokens', '?')} tokens，{meta.get('seconds')}s）")

    merged = out_dir / "合并文本.md"
    merged.write_text("".join(merged_lines).lstrip("\n"), encoding="utf-8")
    (out_dir / "ocr_stats.json").write_text(
        json.dumps({"model": model, "pages_ok": len(stats), "pages_failed": errors, "pages": stats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.classify:
        page_types = {
            page_no: meta.get("page_type", "text")
            for page_no, meta in stats.items()
            if isinstance(meta, dict)
        }
        (out_dir / "page_types.json").write_text(
            json.dumps(page_types, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if errors:
        (out_dir / "errors.txt").write_text("\n".join(str(p) for p in errors), encoding="utf-8")

    total_tokens = sum(
        int(v.get("usage", {}).get("total_tokens", 0) or 0) for v in stats.values() if isinstance(v, dict)
    )
    print(f"\n完成: 成功 {len(stats)} 页，失败 {len(errors)} 页，共 {total_tokens} tokens")
    print(f"输出目录: {out_dir}")
    print(f"合并文本: {merged}")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
