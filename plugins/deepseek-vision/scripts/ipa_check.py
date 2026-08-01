"""国际音标与语言学符号二次核对（视觉 + 专项提示词）。

用法:
    .venv\\Scripts\\python.exe scripts\\ipa_check.py ^
        --pdf <扫描PDF> --ocr-dir <batch_ocr输出目录> --out <输出目录>

行为:
- 自动找出含国际音标/语言学符号的页面（也可 --pages 指定）
- 每页渲染原图，把当前 OCR 文本交给视觉模型重新校对符号
- 校对结果写回 page-XXX.txt（原文件备份为 page-XXX.orig.txt），并生成 ipa_check_report.md/json
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pypdfium2 as pdfium

from vision_config import ConfigError, resolve_config

IPA_RE = re.compile(r"[\u0250-\u02AF\u02B0-\u02FF\u0300-\u036F]")

CHECK_PROMPT = (
    "你是国际音标与语言学符号校对专家。下面是扫描书页的当前 OCR 文本，请对照页面原图重新校对：\n"
    "【当前 OCR 文本】\n{ocr_text}\n"
    "【校对要求】\n"
    "1) 重点校正国际音标与语言学常用符号：tʰ、ɕ、ʑ、ɿ、ʅ、ɧ、ŋ、ɑ、ɛ、ɔ、ʊ、ɤ、æ、ə、ɪ、̃、̥、˥˩ 等；"
    "2) 不要用相似汉字或拉丁字母代替音标（如 1→ɪ、3→ɜ、s→ʃ、z→ʒ、u→ʊ、o→ɔ 这类错误要修正）；"
    "3) 保持段落顺序与表格结构，不要增删正文内容；"
    "4) 实在无法确定的符号用 [?] 标出。\n"
    "只输出校对后的完整文本。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="国际音标二次核对")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--ocr-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pages", default="", help="指定页码；默认自动检测含音标的页面")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--model", default="")
    return parser.parse_args()


def find_ipa_pages(ocr_dir: Path) -> list[int]:
    pages: list[int] = []
    for path in sorted(ocr_dir.glob("page-*.txt")):
        text = path.read_text(encoding="utf-8")
        if IPA_RE.search(text) or "国际音标" in text:
            pages.append(int(path.stem.split("-")[1]))
    return pages


def check_page(
    client: httpx.Client,
    page_no: int,
    image_bytes: bytes,
    ocr_text: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> tuple[int, str, dict]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": CHECK_PROMPT.format(ocr_text=ocr_text[:6000])},
                ],
            }
        ],
        "max_tokens": 4096,
    }
    started = time.time()
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
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return page_no, text, {"usage": usage, "seconds": round(time.time() - started, 1)}
        except Exception as exc:
            if attempt == 2:
                raise


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()

    pdf_path = Path(args.pdf)
    ocr_dir = Path(args.ocr_dir)
    if not pdf_path.exists() or not ocr_dir.exists():
        print("PDF 或 OCR 目录不存在", file=sys.stderr)
        return 2
    try:
        cfg = resolve_config()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    api_key = cfg["api_key"]
    model = args.model or cfg["model"]
    base_url = cfg["base_url"]

    pages = [int(x) for x in args.pages.split(",") if x.strip()] if args.pages else find_ipa_pages(ocr_dir)
    if not pages:
        print("未找到含国际音标的页面")
        return 0
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf = pdfium.PdfDocument(str(pdf_path))
    report: dict = {"model": model, "pages": {}}
    with httpx.Client() as client:
        for page_no in pages:
            ocr_path = ocr_dir / f"page-{page_no:03d}.txt"
            if not ocr_path.exists():
                continue
            ocr_text = ocr_path.read_text(encoding="utf-8")
            img = pdf[page_no - 1].render(scale=args.dpi / 72).to_pil()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_bytes = buf.getvalue()
            try:
                _, corrected, meta = check_page(
                    client, page_no, image_bytes, ocr_text,
                    api_key=api_key, model=model, base_url=base_url,
                )
            except Exception as exc:
                report["pages"][f"page_{page_no:03d}"] = {"status": "FAIL", "error": str(exc)}
                print(f"第 {page_no} 页失败: {exc}")
                continue

            # 备份并写回
            orig = ocr_dir / f"page-{page_no:03d}.orig.txt"
            if not orig.exists():
                shutil.copy2(ocr_path, orig)
            ocr_path.write_text(corrected, encoding="utf-8")
            usage = meta.get("usage", {})
            report["pages"][f"page_{page_no:03d}"] = {
                "status": "OK",
                "tokens": usage.get("total_tokens", 0),
                "seconds": meta.get("seconds"),
                "ipa_symbols_before": len(IPA_RE.findall(ocr_text)),
                "ipa_symbols_after": len(IPA_RE.findall(corrected)),
            }
            print(f"第 {page_no} 页 OK（{usage.get('total_tokens', '?')} tokens，{meta.get('seconds')}s）")

    (out_dir / "ipa_check_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# 国际音标核对报告", "", f"- 模型: {model}", "", "| 页 | 状态 | 音标符号数(前/后) | tokens |", "| --- | --- | --- | --- |"]
    for key in sorted(report["pages"]):
        info = report["pages"][key]
        page_no = key.split("_")[1]
        if info["status"] == "OK":
            lines.append(f"| {int(page_no)} | OK | {info['ipa_symbols_before']} / {info['ipa_symbols_after']} | {info['tokens']} |")
        else:
            lines.append(f"| {int(page_no)} | FAIL | - | - |")
    (out_dir / "ipa_check_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"核对完成: {out_dir / 'ipa_check_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
