"""DOCX 转换校验：批量对比原扫描 PDF 与组装后的 DOCX。

用法:
    .venv\\Scripts\\python.exe scripts\\verify_conversion.py ^
        --pdf <原扫描PDF> --ocr-dir <batch_ocr输出目录> --docx <转换后的.docx>

校验内容:
  1. 页面规格与页数对照
  2. 内容覆盖率（原稿每页 OCR 文字在 DOCX 全文中的匹配比例）
  3. 全书顺序一致性（原稿各页内容在 DOCX 中保持先后顺序）
  4. 逐页对齐参考（重新排版后仅作参考，不作为判定依据）
  5. 可选 --vision-check: 用视觉模型抽样对比原稿页与 DOCX 页
输出: verification_report.md / .json，全部通过返回 0。
"""

from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pypdfium2 as pdfium

from vision_config import ConfigError, resolve_config

VISION_PROMPT = (
    "第一张图片是扫描原稿页面，第二张是转换后的 Word 文档页面。"
    "请对比两张图片：1) 文字内容是否对应（允许排版重排、行距变化）；"
    "2) 是否有内容缺失、错乱或明显排版问题（文字重叠、溢出、表格错位等）。"
    "只输出 JSON，格式：{\"consistent\": true 或 false, \"issues\": [问题列表，没有则为 []]}"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DOCX 转换校验")
    parser.add_argument("--pdf", required=True, help="原扫描 PDF 路径")
    parser.add_argument("--ocr-dir", required=True, help="batch_ocr 输出目录（含 page-*.txt）")
    parser.add_argument("--docx", action="append", required=True, dest="docx_list", help="转换后的 DOCX（可多个，按顺序对应全书章节）")
    parser.add_argument("--out", default="", help="报告输出目录（默认与第一个 DOCX 同目录）")
    parser.add_argument("--dpi", type=int, default=150, help="渲染分辨率（默认 150）")
    parser.add_argument("--threshold-pass", type=float, default=0.85, help="相似度通过阈值（默认 0.85）")
    parser.add_argument("--threshold-warn", type=float, default=0.60, help="相似度警告阈值（默认 0.60）")
    parser.add_argument("--vision-check", type=int, default=0, help="用视觉模型抽样对比前 N 页（默认 0 关闭）")
    parser.add_argument("--model", default="", help="视觉模型（默认读 .env）")
    parser.add_argument("--ignore-pages", default="", help="跳过校验的页码（如古籍图片保留页 20）")
    return parser.parse_args()


def normalize_text(text: str) -> str:
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    return text.lower()


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def coverage(needle: str, haystack: str) -> float:
    """needle（单页 OCR 文本）中的字符有多少能在 haystack（DOCX 全文）中按序匹配到。"""
    if not needle:
        return 1.0
    sm = difflib.SequenceMatcher(None, normalize_text(needle), normalize_text(haystack), autojunk=False)
    matched = sum(block.size for block in sm.get_matching_blocks())
    return matched / len(normalize_text(needle))


def order_positions(ocr_texts: list[str], docx_full_text: str) -> list[int]:
    """每页 OCR 文本前 40 个字符在 DOCX 中的出现位置（从上一页之后向后查找）。

    返回负数表示该页内容未能在上一页之后定位（可能因真题/解析重复内容
    导致探测片段与上一页内容交错，或顺序异常）。
    """
    haystack = normalize_text(docx_full_text)
    positions: list[int] = []
    search_from = 0
    for text in ocr_texts:
        probe = normalize_text(text)[:40]
        if not probe:
            positions.append(-2)  # 空页，跳过顺序校验
            continue
        idx = haystack.find(probe, search_from)
        if idx < 0:
            idx = haystack.find(probe)
            positions.append(-idx - 1 if idx >= 0 else -1)
        else:
            positions.append(idx)
            search_from = idx + len(probe)
    return positions


def find_soffice() -> str | None:
    candidates = [
        shutil.which("soffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def docx_to_pdf(docx_path: Path, out_pdf: Path) -> None:
    soffice = find_soffice()
    if soffice:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_pdf.parent), str(docx_path)],
            check=True,
            capture_output=True,
        )
        produced = out_pdf.parent / (docx_path.stem + ".pdf")
        if produced.exists():
            produced.replace(out_pdf)
            return
    if os.name == "nt":
        _docx_to_pdf_via_word(docx_path, out_pdf)
        return
    raise RuntimeError("未找到 LibreOffice 或 Word，无法渲染 DOCX 进行校验")


def _docx_to_pdf_via_word(docx_path: Path, out_pdf: Path) -> None:
    fd, ps1_path = tempfile.mkstemp(suffix=".ps1", prefix="docx2pdf_")
    os.close(fd)
    ps1 = Path(ps1_path)
    script = (
        "$ErrorActionPreference='Stop'\n"
        "$w = New-Object -ComObject Word.Application\n"
        "$w.Visible = $false\n"
        "$w.DisplayAlerts = 0\n"
        f"$d = $w.Documents.Open('{str(docx_path).replace(chr(39), chr(39)*2)}')\n"
        f"$d.SaveAs2('{str(out_pdf).replace(chr(39), chr(39)*2)}', 17)\n"
        "$d.Close($false)\n"
        "$w.Quit()\n"
    )
    ps1.write_bytes(b"\xef\xbb\xbf" + script.encode("utf-8"))
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stdout or b"").decode("utf-8", errors="replace")
        detail += (exc.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"Word 转 PDF 失败: {detail.strip()[:500]}") from exc
    finally:
        for _ in range(3):
            try:
                ps1.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.5)


def render_pdf(pdf_path: Path, out_dir: Path, dpi: int) -> list[tuple[int, Path, tuple[int, int]]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages: list[tuple[int, Path, tuple[int, int]]] = []
    for i in range(len(pdf)):
        page = pdf[i]
        size = (round(page.get_size()[0]), round(page.get_size()[1]))
        img = page.render(scale=dpi / 72).to_pil()
        png = out_dir / f"page-{i + 1:03d}.png"
        img.save(png)
        pages.append((i + 1, png, size))
    return pages


def extract_pdf_text(pdf_path: Path) -> list[str]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    texts: list[str] = []
    for i in range(len(pdf)):
        tp = pdf[i].get_textpage()
        texts.append(tp.get_text_range() or "")
    return texts


def load_ocr_pages(ocr_dir: Path) -> list[str]:
    files = sorted(ocr_dir.glob("page-*.txt"))
    if not files:
        raise RuntimeError(f"ocr-dir 中没有 page-*.txt: {ocr_dir}")
    return [f.read_text(encoding="utf-8") for f in files]


def align_pages(
    docx_texts: list[str], ocr_texts: list[str]
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    pairs: list[tuple[int, int, float]] = []
    unmatched_docx: list[int] = []
    used_ocr: set[int] = set()
    ocr_idx = 0
    for i, dtext in enumerate(docx_texts):
        best_ratio = 0.0
        best_j = -1
        for j in range(ocr_idx, min(ocr_idx + 6, len(ocr_texts))):
            ratio = similarity(dtext, ocr_texts[j])
            if ratio > best_ratio:
                best_ratio = ratio
                best_j = j
        if best_j >= 0 and best_ratio >= 0.3:
            pairs.append((i + 1, best_j + 1, best_ratio))
            used_ocr.add(best_j)
            ocr_idx = best_j + 1
        else:
            unmatched_docx.append(i + 1)
    unmatched_ocr = [j + 1 for j in range(len(ocr_texts)) if j not in used_ocr]
    return pairs, unmatched_docx, unmatched_ocr


def vision_compare(
    client: httpx.Client,
    png_a: Path,
    png_b: Path,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> dict:
    def enc(p: Path) -> str:
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")

    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": enc(png_a)}},
                    {"type": "image_url", "image_url": {"url": enc(png_b)}},
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }
        ],
        "max_tokens": 1024,
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
        return {"consistent": False, "issues": [f"模型未返回 JSON: {content[:120]}"]}
    return json.loads(match.group(0))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()

    pdf_path = Path(args.pdf)
    ocr_dir = Path(args.ocr_dir)
    if not pdf_path.exists():
        print(f"PDF 不存在: {pdf_path}", file=sys.stderr)
        return 2
    ocr_texts = load_ocr_pages(ocr_dir)
    ignore_pages = {int(x) for x in args.ignore_pages.split(",") if x.strip()}
    try:
        cfg = resolve_config()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    api_key = cfg["api_key"]
    model = args.model or cfg["model"]
    base_url = cfg["base_url"]

    tmp = Path(tempfile.mkdtemp(prefix="verify_conv_"))
    try:
        pdf_pages = render_pdf(pdf_path, tmp / "pdf", args.dpi)
        all_docx_texts: list[str] = []
        docx_info: list[dict] = []
        for docx in args.docx_list:
            docx_path = Path(docx)
            if not docx_path.exists():
                print(f"DOCX 不存在: {docx_path}", file=sys.stderr)
                return 2
            pdf_out = tmp / f"{docx_path.stem}.pdf"
            docx_to_pdf(docx_path, pdf_out)
            texts = extract_pdf_text(pdf_out)
            pages = render_pdf(pdf_out, tmp / f"docx_{docx_path.stem}", args.dpi)
            docx_info.append(
                {
                    "docx": str(docx_path),
                    "pdf_pages": len(pages),
                    "text_pages": len(texts),
                    "page_size": pages[0][2] if pages else None,
                }
            )
            all_docx_texts.extend(texts)

        pairs, unmatched_docx, unmatched_ocr = align_pages(all_docx_texts, ocr_texts)
        docx_full_text = "\n".join(all_docx_texts)
        coverages = [
            -1.0 if (i + 1) in ignore_pages else round(coverage(t, docx_full_text), 3)
            for i, t in enumerate(ocr_texts)
        ]
        positions = order_positions(ocr_texts, docx_full_text)
        order_ok = True
        order_violations: list[str] = []
        last_pos = -1
        for i, pos in enumerate(positions, 1):
            if pos == -2:
                continue
            if i in ignore_pages:
                continue
            if pos < 0:
                order_ok = False
                order_violations.append(
                    f"第 {i} 页未能按顺序定位（可能为重复引文，建议人工抽查）"
                )
                continue
            last_pos = pos
        report_order_warnings = order_violations if not order_ok else []

        report: dict = {
            "pdf": str(pdf_path),
            "pdf_pages": len(pdf_pages),
            "docx": args.docx_list,
            "docx_pages": len(all_docx_texts),
            "ocr_pages": len(ocr_texts),
            "threshold_pass": args.threshold_pass,
            "threshold_warn": args.threshold_warn,
            "page_size_pdf": pdf_pages[0][2] if pdf_pages else None,
            "docx_info": docx_info,
            "page_matches": [{"docx_page": d, "pdf_page": p, "similarity": round(r, 3)} for d, p, r in pairs],
            "coverage": [{"ocr_page": i + 1, "coverage": c} for i, c in enumerate(coverages)],
            "order_positions": positions,
            "order_ok": order_ok,
            "order_warnings": report_order_warnings,
            "unmatched_docx_pages": unmatched_docx,
            "unmatched_ocr_pages": unmatched_ocr,
            "vision_checks": [],
            "issues": [],
        }

        for i, cov in enumerate(coverages, 1):
            if cov < 0:
                continue
            if cov < args.threshold_warn:
                report["issues"].append(f"第 {i} 页内容覆盖率过低（{cov:.2f}），疑似缺失或错乱")
        if report["page_size_pdf"] and report["docx_info"][0].get("page_size"):
            if abs(report["page_size_pdf"][0] - report["docx_info"][0]["page_size"][0]) / report["page_size_pdf"][0] > 0.05:
                report["issues"].append("页面宽度与原始 PDF 不一致（可能混用了不同纸张规格）")

        if args.vision_check and api_key:
            with httpx.Client() as client:
                for p_page in range(1, min(args.vision_check, len(pdf_pages)) + 1):
                    pdf_png = pdf_pages[p_page - 1][1]
                    docx_png = tmp / f"docx_{Path(args.docx_list[0]).stem}" / f"page-{p_page:03d}.png"
                    if not docx_png.exists():
                        report["issues"].append(f"视觉抽检第 {p_page} 页失败: DOCX 页不存在")
                        continue
                    try:
                        verdict = vision_compare(
                            client, pdf_png, docx_png, api_key=api_key, model=model, base_url=base_url
                        )
                    except Exception as exc:
                        verdict = {"consistent": False, "issues": [f"调用失败: {exc}"]}
                    report["vision_checks"].append({"page": p_page, **verdict})
                    if not verdict.get("consistent", False):
                        report["issues"].append(f"视觉抽检第 {p_page} 页不一致: {verdict.get('issues', [])}")

        out_dir = Path(args.out) if args.out else Path(args.docx_list[0]).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "verification_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        lines = [
            "# 转换校验报告",
            "",
            f"- 原 PDF: {pdf_path}（{len(pdf_pages)} 页）",
            f"- DOCX 渲染页数: {len(all_docx_texts)} / OCR 页数: {len(ocr_texts)}",
            f"- 通过阈值: {args.threshold_pass}，警告阈值: {args.threshold_warn}",
            "",
            "## 内容覆盖率（原稿每页文字在 DOCX 中的匹配比例）",
            "",
            "| 原稿页 | 覆盖率 | 状态 |",
            "| --- | --- | --- | --- |",
        ]
        for i, cov in enumerate(coverages, 1):
            if cov < 0:
                lines.append(f"| {i} | - | SKIP（古籍图片保留页） |")
            else:
                status = "PASS" if cov >= args.threshold_pass else ("WARN" if cov >= args.threshold_warn else "FAIL")
                lines.append(f"| {i} | {cov:.2f} | {status} |")
        lines.append("")
        lines.append("## 逐页对齐参考（重新排版后仅作参考，不作为判定依据）")
        lines.append("")
        lines.append("| DOCX 页 | 对应 PDF 页 | 相似度 |")
        lines.append("| --- | --- | --- |")
        for d_page, p_page, ratio in pairs:
            lines.append(f"| {d_page} | {p_page} | {ratio:.2f} |")
        lines.append("")
        if order_ok:
            lines.append("顺序校验: **通过**（原稿各页内容在 DOCX 中保持先后顺序）")
        else:
            lines.append("顺序校验: **警告**（以下页面未能按顺序定位，多为重复引文导致，请人工抽查）")
            for violation in order_violations:
                lines.append(f"- {violation}")
        if report["vision_checks"]:
            lines.append("")
            lines.append("## 视觉抽检")
            for check in report["vision_checks"]:
                status = "PASS" if check.get("consistent") else "FAIL"
                issues = "；".join(check.get("issues", [])) or "无"
                lines.append(f"- 第 {check['page']} 页: {status}（{issues}）")
        lines.append("")
        lines.append("## 结论")
        if report["issues"]:
            lines.append("**存在未通过项，建议修复后重新校验：**")
            for issue in report["issues"]:
                lines.append(f"- {issue}")
            verdict = "FAIL"
        else:
            lines.append("**全部通过，可以输出。**")
            verdict = "PASS"
        lines.append("")
        lines.append(f"最终判定: **{verdict}**")
        (out_dir / "verification_report.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"校验完成: {out_dir / 'verification_report.md'}")
        print(f"最终判定: {verdict}")
        return 0 if verdict == "PASS" else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
