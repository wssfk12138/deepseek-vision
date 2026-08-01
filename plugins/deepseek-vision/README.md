# DeepSeek Vision 插件

给 Codex 里的 DeepSeek 等纯文本模型补上一双“眼睛”：通过 MCP 服务器调用多模态视觉 API，把图片、截图、PDF 变成文字结果，再交回 DeepSeek 继续推理。

底层使用 GitHub 开源方案 [mcp-vision](https://github.com/hahahahanb/mcp-vision)（MIT 协议），默认调用硅基流动（SiliconFlow）上的 **Qwen3-VL-32B-Instruct** 付费视觉模型（通用理解更强），也可以切换回免费的 DeepSeek-OCR。

## 工作原理

```text
Codex + DeepSeek ──图片路径/URL──▶ deepseek-vision MCP 服务器 ──▶ 多模态视觉 API
        ◀──────文字分析结果──────   (mcp-vision)          ◀── 图片分析结果
```

## 提供的工具

| 工具 | 用途 | 底层 |
| --- | --- | --- |
| `analyze_image` | 图片内容分析（描述、问答、图表解读） | 多模态视觉 LLM |
| `ocr_extract` | 从图片 / PDF 提取文字（自然语言返回） | 多模态视觉 LLM |
| `ocr_precise` | 精准 OCR（结构化结果，含坐标和置信度） | 百度 OCR / 腾讯云 OCR |

所有工具都支持本地文件路径和远程 URL。

## 安装与配置

### 1. 安装依赖（一次性）

插件通过 `uv` 启动 MCP 服务器（`uv tool run --env-file .env mcp-vision`），需要先安装 [uv](https://docs.astral.sh/uv/)，然后运行：

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

macOS / Linux：

```bash
bash scripts/setup.sh
```

安装脚本会：安装 uv（如缺失）→ 预装 `mcp-vision` → 创建批量 OCR 虚拟环境 → 从 `assets/env.example` 生成 `.env` → 冒烟测试。

> 说明：安装脚本会把 `mcp-vision` 固定在 uv 管理的 64 位 Python 3.12 环境中，并锁定
> `mcp<2` 依赖版本，以兼容 mcp-vision 当前的 FastMCP 导入方式（避免 32 位 Python
> 触发 cryptography 源码编译、以及新版 MCP SDK 导致模块缺失）。

### 2. 填入视觉 API Key

编辑插件根目录下的 `.env`。注册[硅基流动](https://cloud.siliconflow.cn)并充值后填入：

```ini
MCP_OCR_PROVIDER=siliconflow
SILICONFLOW_API_KEY=sk-你的密钥
SILICONFLOW_MODEL=Qwen/Qwen3-VL-32B-Instruct
```

`SILICONFLOW_MODEL` 可切换为其他视觉模型（如 `Qwen/Qwen3-VL-8B-Instruct` 更便宜、`deepseek-ai/DeepSeek-OCR` 免费）；也可以改用阿里百炼、火山引擎（豆包）、OpenAI、Anthropic 或任意 OpenAI 兼容接口，完整变量见 [assets/env.example](assets/env.example)。

### 3. 在 Codex 中启用

插件已注册到个人市场（`~/.agents/plugins/marketplace.json`）。在 Codex 应用中打开插件市场，安装 **DeepSeek Vision**，然后新建会话即可使用。修改 `.env` 后需重新加载插件或重启会话。

## 使用示例

安装完成后，直接在对话中：

- “看看这张截图里有什么？” → 自动调用 `analyze_image`
- “提取这张图片里的所有文字” → 自动调用 `ocr_extract`
- “帮我分析这张图表” → 自动调用 `analyze_image` 并附带分析提示

插件自带的 `image-analysis` 技能会自动触发路由，无需手动调用。

## 在对话中发送图片（剪贴板方案）

Codex 对话窗口对 DeepSeek 等纯文本模型不提供图片附件入口，但插件提供了“剪贴板桥”：

1. 截图：按 `Win + Shift + S` 框选截图（或对任意图片按 `Ctrl + C` 复制）；
2. 回到 Codex 对话，直接说“分析我刚才复制的图片”或“看看这张截图”；
3. 插件会自动从剪贴板保存图片（`images/inbox/` 目录）并交给视觉模型分析，无需手动保存文件。

也可以手动把截图保存为文件，然后直接发文件路径（如 `C:\Users\...\截图.png`），插件同样支持。

## 扫描 PDF 批量转文本（带水印的书页）

针对“拍照扫描的书籍 PDF、每页有斜体水印遮挡部分文字”的场景，插件提供批量 OCR 脚本：

```powershell
scripts\batch_ocr.ps1 "C:\资料\717北语语纲真题册.pdf" --out "C:\资料\OCR结果"
```

脚本自动完成：分页渲染（默认 200 DPI）→ 逐页并行调用视觉模型 OCR（默认 Qwen3-VL-32B，提示词自动忽略水印、推断被遮挡文字）→ 输出每页 `page-001.txt`、`合并文本.md` 和 `ocr_stats.json`。失败页记录在 `errors.txt`，可缩小页码范围重跑。

详细工作流见插件的 `pdf-ocr-conversion` 技能。

### 古籍区域保留（不整页插图）

对含古籍影印的书页，先检测古籍区域再裁剪嵌入：

```powershell
scripts\detect_ancient.ps1 --pdf "C:\资料\扫描书.pdf" --pages "11-13,20-22" --out "C:\资料\ancient"
```

输出 `ancient_regions.json`（整页古籍标记 + 区域坐标），DOCX 组装时只嵌入裁剪图；校验时用 `--ignore-pages` 豁免图片保留页。

## 表格提取（图片表格 → 可编辑 Word 表格）

```powershell
scripts\table_extract.ps1 --pdf "C:\扫描书.pdf" --pages "5,26,56" --out "C:\tables"
```

视觉模型输出结构化 `tables.json`；组装 DOCX 时用 `scripts\docx_tables.py`（可导入）把文本表格或 JSON 表格写成真实 Word 表格（Table Grid、列宽自适应、表头加粗、[?] 红色保留）。详见 `table-extraction` 技能。

## 国际音标与语言学符号专项核对

```powershell
scripts\ipa_check.ps1 --pdf "C:\扫描书.pdf" --ocr-dir "C:\OCR结果" --out "C:\ipa报告"
```

自动定位含国际音标的页面（也可 `--pages` 指定），让视觉模型对照原图二次校对 tʰ、ɕ、ʑ、ɿ、ʅ、ŋ、ɑ、ɛ、ɔ、ʊ、˥˩ 等符号，校对文本写回页码文件（原文件备份为 `.orig.txt`），并生成 `ipa_check_report.md/json`。说明：托管视觉模型无法真正“微调训练”，本功能通过专项提示词 + 原图对照二次校对 + 人工抽查机制实质提升识别准确率。

## 转换校验（输出前自动对比 PDF 与 DOCX）

组装完 DOCX 后，运行校验脚本自动逐页对比原 PDF 与 DOCX：

```powershell
scripts\verify_conversion.ps1 --pdf "C:\资料\717北语语纲真题册.pdf" --ocr-dir "C:\资料\OCR结果" --docx "C:\资料\转换.docx"
```

校验项：页面规格与页数对照、原稿每页内容覆盖率（防缺失/错乱）、全书顺序一致性、逐页对齐参考；加 `--vision-check 5` 可抽样用视觉模型比对原稿页与 DOCX 页的版式和文字。报告输出到 `verification_report.md/json`，存在 FAIL 会返回非零退出码，全部通过才建议输出。

## 视觉渲染检查（LibreOffice 后台 + 视觉质检）

DOCX 交付前，用 LibreOffice 无窗口后台渲染页面，再由视觉模型逐页检查排版问题：

```powershell
scripts\render_check.ps1 --docx "C:\资料\转换.docx" --check-pages 1,2,5
```

检查项：文字裁剪/溢出/重叠、表格错位/截断、图片异常、页眉页脚、乱码缺字。输出 `render_check_report.md/json`，FAIL 返回非零退出码。LibreOffice 以 headless + 独立配置目录运行，不弹窗、不影响用户正在使用的 LibreOffice 实例。详见 `visual-render-check` 技能。

## 验证安装

运行冒烟测试（只检查 MCP 服务器能否启动并列出工具，不消耗 API 额度）：

```powershell
python scripts\smoke_test.py
```

输出中应能看到 `analyze_image`、`ocr_extract`、`ocr_precise` 三个工具。

## 隐私说明

图片会发送到你配置的视觉 API 提供商（默认硅基流动）。敏感图片请谨慎处理，或改用支持私有化部署的视觉模型。
