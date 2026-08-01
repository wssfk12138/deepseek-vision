---
name: pdf-ocr-conversion
description: 把扫描版 PDF（纯图片页、带斜体水印）批量转成文本，供进一步整理为可编辑 docx。当用户要求“把扫描 PDF 转成 Word / 提取整本书文字 / 处理带水印的书页”时使用。
---

# 扫描 PDF 批量 OCR 转文本

针对“拍照扫描的书籍 PDF + 斜体水印遮挡部分文字”场景的批量转换工作流。

## 适用场景

- PDF 没有文字层（整页都是图片），需要提取正文
- 页面上有打印水印，部分文字被遮挡
- 需要把上百页扫描件转成可编辑文档

## 工作流

1. **批量 OCR**：运行 `scripts/batch_ocr.py`（Windows 可用 `scripts\batch_ocr.ps1`）：

   ```powershell
   scripts\batch_ocr.ps1 "C:\资料\717北语语纲真题册.pdf" --out "C:\资料\OCR结果"
   ```

   脚本会：分页渲染 PNG → 逐页调用视觉模型（默认 Qwen3-VL-32B，自动忽略水印、推断被遮挡文字）→ 输出每页 `page-001.txt` 和 `合并文本.md`，并生成 `ocr_stats.json` 统计 token 用量。

2. **质量检查**：抽查输出文本，重点看 `[?]` 标记（模型不确定处）和页首页尾是否有遗漏。
3. **古籍区域检测（可选但推荐）**：对古代汉语等章节运行 `scripts/detect_ancient.py --pdf <扫描PDF> --pages "11-13,20-22" --out <目录>`，识别整页古籍与局部古籍影印区域（输出 `ancient_regions.json`，坐标为 0-1 比例）；组装 DOCX 时只裁剪嵌入这些区域图片，不做整页插图。
4. **组装 DOCX**：按中文书籍排版规范生成 docx——封面、写在前面、目录各自独立成页；每一年真题另起一页；正文首行缩进 2 字符、1.5 倍行距；不添加任何原书之外的标注；古籍区域以裁剪图嵌入。
5. **表格转换（可选）**：对含表格的页面先跑 `scripts/table_extract.ps1` 得到结构化数据，组装 DOCX 时用 `docx_tables.py` 写入真实 Word 表格（详见 `table-extraction` 技能）。
6. **音标专项核对（可选但推荐）**：含国际音标/语言学符号的书页运行 `scripts/ipa_check.ps1 --pdf <扫描PDF> --ocr-dir <OCR目录> --out <报告目录>`，视觉模型对照原图二次校对音标符号（如 tʰ、ɕ、ʑ、ɿ、ʅ、ŋ、ɑ、ɛ、ɔ、ʊ、˥˩），校对结果写回页码文本，原始文件备份为 `page-XXX.orig.txt`。
7. **自动校验（输出前必做）**：运行转换校验脚本，对比原 PDF 与 DOCX：

   ```powershell
   scripts\verify_conversion.ps1 `
     --pdf "C:\原稿.pdf" --ocr-dir "C:\OCR结果" --docx "C:\转换.docx" --out "C:\校验报告"
   ```

   校验内容：页面规格与页数对照、原稿每页内容覆盖率（防缺失/错乱）、全书顺序一致性、逐页对齐参考，可选 `--vision-check N` 用视觉模型抽样比对原稿页与 DOCX 页的版式与文字。古籍以图片保留的页面用 `--ignore-pages 20` 豁免覆盖率检查。报告生成 `verification_report.md/json`，**存在 FAIL 时必须修复并重新校验，全部通过才可输出**。

## 注意事项

- 实测对比：Qwen3-VL-32B 对密排中文书页 + 水印的识别稳定准确；DeepSeek-OCR 免费但在同样页面上输出幻觉内容，不要作为默认选择。
- 单页约 1500–5000 tokens，45 页约 10–20 万 tokens（约 1 元以内）；10 元余额可整本跑多次。
- 每页一次 API 调用，默认 3 路并行；失败页会记录在 `errors.txt`，可缩小页码范围重跑。
- 改模型：`--model deepseek-ai/DeepSeek-OCR`（免费，密排页慎用）或自定义 OpenAI 兼容接口 `--base-url` / `--api-key`。
- 水印遮挡严重的字模型会用 `[?]` 标注，整理文档时需人工确认。
- DOCX 是重新排版的文本，无法与原扫描页做到像素级一致；校验目标是“内容完整对应 + 排版健康”，不是逐像素对齐。
