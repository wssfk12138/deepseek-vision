"""DOCX 视觉渲染检查：LibreOffice 后台渲染 + 视觉模型逐页质检。

用法:
    .venv\\Scripts\\python.exe scripts\\render_check.py --docx <文档.docx>

流程:
  1. 用 LibreOffice headless（无窗口、独立配置目录）把 DOCX 转 PDF；
  2. 用 pypdfium2 把 PDF 渲染为页面 PNG；
  3. 调用视觉模型逐页检查文字裁剪/重叠、表格错位、图片异常、页眉页脚、缺字等；
  4. 输出 render_check_report.md/json，全部通过返回 0。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import pypdfium2 as pdfium

from vision_config import ConfigError, resolve_config

QA_PROMPT = (
    "你是文档排版质检员。请检查这张由 Word 文档渲染出的页面图片，只依据图片中真实可见的内容判断："
    "1）文字是否被裁剪、溢出或重叠；2）表格是否错位、断裂或内容被截断；"
    "3）图片是否变形、缺失或遮挡文字；4）页眉页脚是否异常；"
    "5）是否有乱码、方块缺字。"
    "重要约束：不要脑补、推测或编造页面上不存在的内容；单个字符略模糊不算问题；"
    "只有你能明确看到的排版缺陷才报告。"
    "只输出 JSON：{\"ok\": true 或 false, \"issues\": [\"明确可见的问题及大致位置\"]}，"
    "没有问题时空数组。"
)

CONFIRM_PROMPT_HEAD = (
    "这是对同一 Word 渲染页面的复核。上一轮检查列出了以下疑似问题：\n"
)
CONFIRM_PROMPT_TAIL = (
    "\n请重新仔细查看图片，逐条确认：这些问题是否真实可见？"
    "去掉脑补和误判，只保留你能明确看到的缺陷，并补充任何明显遗漏。"
    "只输出 JSON：{\"ok\": true 或 false, \"issues\": [\"确认的问题及位置\"]}。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DOCX 视觉渲染检查")
    parser.add_argument("--docx", required=True, help="待检查的 DOCX")
    parser.add_argument("--out", default="", help="报告输出目录（默认与 DOCX 同目录/render_check）")
    parser.add_argument("--dpi", type=int, default=150, help="渲染分辨率（默认 150）")
    parser.add_argument("--workers", type=int, default=3, help="并行质检数（默认 3）")
    parser.add_argument("--check-pages", default="", help="只检查指定页，如 1,2,5（默认全部）")
    parser.add_argument("--sample", type=int, default=1, help="每隔 N 页检查一页（默认 1=全部）")
    parser.add_argument("--model", default="", help="视觉模型（默认读 .env）")
    parser.add_argument("--soffice", default="", help="soffice 可执行文件路径")
    parser.add_argument("--keep-images", action="store_true", help="在报告目录保留页面 PNG")
    return parser.parse_args()


def find_soffice(override: str = "") -> str | None:
    candidates = [
        override,
        os.environ.get("LIBREOFFICE_SOFFICE", ""),
        shutil.which("soffice") or "",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def docx_to_pdf(docx_path: Path, out_dir: Path, soffice: str) -> Path:
    profile = Path(tempfile.mkdtemp(prefix="lo_profile_"))
    profile_uri = profile.as_uri()
    cmd = [
        soffice,
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nologo",
        "--nodefault",
        f"-env:UserInstallation={profile_uri}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(docx_path),
    ]
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(cmd, check=True, **kwargs)
    expected = out_dir / (docx_path.stem + ".pdf")
    for _ in range(30):
        if expected.exists() and expected.stat().st_size > 0:
            break
        time.sleep(1)
    if not expected.exists() or expected.stat().st_size == 0:
        raise RuntimeError("LibreOffice 未能生成 PDF，请检查 DOCX 是否损坏")
    shutil.rmtree(profile, ignore_errors=True)
    return expected


def render_pdf(pdf_path: Path, out_dir: Path, dpi: int) -> list[tuple[int, Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages: list[tuple[int, Path]] = []
    for i in range(len(pdf)):
        png = out_dir / f"page-{i + 1:03d}.png"
        pdf[i].render(scale=dpi / 72).to_pil().save(png)
        pages.append((i + 1, png))
    return pages


def page_text_len(pdf_path: Path, page_index: int) -> int:
    pdf = pdfium.PdfDocument(str(pdf_path))
    return len((pdf[page_index].get_textpage().get_text_range() or "").strip())


def vision_qa(
    client: httpx.Client,
    png: Path,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> dict:
    b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": QA_PROMPT},
                ],
            }
        ],
        "max_tokens": 512,
    }
    resp = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.S)
    match = re.search(r"\{.*\}", content, flags=re.S)
    if not match:
        return {"ok": False, "issues": [f"模型未返回 JSON: {content[:120]}"]}
    return json.loads(match.group(0))


def vision_confirm(
    client: httpx.Client,
    png: Path,
    issues: list[str],
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> dict:
    prompt = CONFIRM_PROMPT_HEAD + "\n".join(f"- {x}" for x in issues) + CONFIRM_PROMPT_TAIL
    b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 512,
    }
    resp = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.S)
    match = re.search(r"\{.*\}", content, flags=re.S)
    if not match:
        return {"ok": False, "issues": [f"复核未返回 JSON: {content[:120]}"]}
    return json.loads(match.group(0))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"DOCX 不存在: {docx_path}", file=sys.stderr)
        return 2
    try:
        cfg = resolve_config()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    api_key = cfg["api_key"]
    model = args.model or cfg["model"]
    base_url = cfg["base_url"]
    soffice = find_soffice(args.soffice)
    if not soffice:
        print("未找到 LibreOffice（soffice），请先安装或指定 --soffice", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else docx_path.parent / "render_check"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="render_check_"))
    try:
        print(f"LibreOffice 后台渲染: {soffice}")
        pdf_path = docx_to_pdf(docx_path, tmp, soffice)
        pages = render_pdf(pdf_path, tmp / "pages", args.dpi)

        if args.check_pages:
            wanted = {int(x) for x in args.check_pages.split(",") if x.strip()}
        else:
            wanted = {p for p, _ in pages if (p - 1) % args.sample == 0}
        to_check = [(p, png) for p, png in pages if p in wanted]
        page_png = {p: png for p, png in to_check}

        results: dict[str, dict] = {}
        blanks: list[int] = []
        with httpx.Client() as client:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {
                    pool.submit(vision_qa, client, png, api_key=api_key, model=model, base_url=base_url): p
                    for p, png in to_check
                }
                for future in as_completed(futures):
                    p = futures[future]
                    try:
                        verdict = future.result()
                    except Exception as exc:
                        verdict = {"ok": False, "issues": [f"质检调用失败: {exc}"]}
                    if not verdict.get("ok") and verdict.get("issues"):
                        # 二次确认，过滤脑补/误报
                        confirm = vision_confirm(
                            client, page_png[p], verdict.get("issues", []),
                            api_key=api_key, model=model, base_url=base_url,
                        )
                        verdict = confirm
                    results[f"page_{p:03d}"] = {"page": p, **verdict}
                    status = "PASS" if verdict.get("ok") else "FAIL"
                    print(f"第 {p} 页: {status}（{len(verdict.get('issues', []))} 个问题）")

        total_pages = len(pages)
        for p, _ in pages:
            if page_text_len(pdf_path, p - 1) == 0:
                blanks.append(p)

        report = {
            "docx": str(docx_path),
            "soffice": soffice,
            "model": model,
            "total_pages": total_pages,
            "checked_pages": len(to_check),
            "blank_pages": blanks,
            "pages": results,
        }
        issues: list[str] = []
        for page_no, res in results.items():
            for issue in res.get("issues", []):
                issues.append(f"第 {res['page']} 页: {issue}")
        if blanks:
            issues.append(f"空白页（渲染后无文字）: {blanks}，请确认是否正常")

        (out_dir / "render_check_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        lines = [
            "# 视觉渲染检查报告",
            "",
            f"- 文档: {docx_path}",
            f"- 总页数: {total_pages}，已质检: {len(to_check)} 页",
            f"- 视觉模型: {model}",
            "",
            "| 页 | 判定 | 问题 |",
            "| --- | --- | --- |",
        ]
        for p, _ in pages:
            res = results.get(f"page_{p:03d}")
            if not res:
                continue
            status = "PASS" if res.get("ok") else "FAIL"
            issues_text = "；".join(res.get("issues", [])) or "无"
            lines.append(f"| {p} | {status} | {issues_text} |")
        lines.append("")
        if issues:
            lines.append("## 发现的问题")
            for issue in issues:
                lines.append(f"- {issue}")
            verdict = "FAIL"
            lines.append("")
            lines.append("最终判定: **FAIL（请修复后重新检查）**")
        else:
            lines.append("最终判定: **PASS（渲染视觉效果无异常）**")
            verdict = "PASS"
        (out_dir / "render_check_report.md").write_text("\n".join(lines), encoding="utf-8")

        if args.keep_images:
            keep_dir = out_dir / "pages"
            keep_dir.mkdir(exist_ok=True)
            for _, png in pages:
                shutil.copy2(png, keep_dir / png.name)

        print(f"渲染检查完成: {out_dir / 'render_check_report.md'}")
        print(f"最终判定: {verdict}")
        return 0 if verdict == "PASS" else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
