---
name: visual-render-check
description: 验证 Word/DOCX 渲染后的视觉效果：用 LibreOffice 无窗口后台渲染页面，再用视觉模型逐页检查文字裁剪、表格错位、图片异常、页眉页脚、缺字等排版问题，输出渲染检查报告。交付 DOCX 前使用。
---

# 视觉渲染检查（LibreOffice 后台 + 视觉模型质检）

用于 DOCX 交付前的最终视觉 QA。全程无窗口、后台运行，不影响用户使用电脑。

## 适用时机

- 文档插件生成或修改 DOCX 之后、交付之前
- 用户反馈 Word 文档排版异常（表格错位、文字重叠、图片变形、缺字等）
- 需要证明“渲染后视觉效果正常”的交付场景

## 工作流

1. **渲染**：运行 `scripts/render_check.ps1`（Windows）或 `render_check.py`：

   ```powershell
   scripts\render_check.ps1 --docx "C:\资料\转换.docx" --out "C:\资料\render_check"
   ```

   LibreOffice 以 `--headless` + 独立配置目录方式在后台转换 DOCX → PDF → PNG，不弹窗、不占用用户已打开的 LibreOffice。

2. **质检**：视觉模型（默认 Qwen3-VL-32B）逐页检查：
   - 文字是否被裁剪、溢出、重叠
   - 表格是否错位、断裂、内容被截断
   - 图片是否变形、缺失、遮挡文字
   - 页眉页脚是否异常
   - 是否有乱码、方块缺字

3. **报告与门禁**：输出 `render_check_report.md/json`（每页 PASS/FAIL + 问题描述）。存在 FAIL 时脚本返回非零退出码，应修复后重新检查，全部通过再交付。

## 常用参数

- `--check-pages 1,2,5`：只检查指定页
- `--sample 5`：每隔 5 页检查一页（大文档省额度）
- `--dpi 200`：提高渲染清晰度（默认 150）
- `--keep-images`：在报告目录保留页面 PNG 供人工复查
- `--soffice <路径>`：手动指定 LibreOffice 安装位置

## 注意事项

- 每页一次视觉调用，约 4–5 千 tokens（约 1 分钱/页）；大文档建议先用 `--sample` 抽检。
- 空白页会被单独报告（可能是正常的章末空页，需人工确认）。
- 与 `pdf-ocr-conversion` 技能配合：批量转换 → 组装 DOCX → 本技能质检 → 通过后交付。
