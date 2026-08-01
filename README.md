# DeepSeek Vision —— 适用于 Codex 的视觉识别插件

> **本项目是适用于 Codex 的插件（Plugin）**，需要安装到 Codex（ChatGPT 桌面应用或 Codex CLI）中使用；它不是独立软件、网站或浏览器扩展。安装后请在 Codex 中通过 `@deepseek-vision` 或直接描述任务来调用。

给 Codex 里的 DeepSeek 等纯文本模型补上“眼睛”：图片分析、OCR、扫描 PDF 批量转文本、古籍影印区域保留、图片表格转可编辑表格、国际音标专项核对、DOCX 视觉渲染质检。

底层视觉模型由用户自行配置：在 `.env` 中填写 OpenAI 兼容 API 的请求地址、密钥与模型名即可（模板见 `plugins/deepseek-vision/assets/env.example`），费用与额度取决于你选择的 API 服务商。

## 重要前提：DeepSeek 是纯文本模型

**DeepSeek 不支持直接接收图像**，无法把图片作为输入“发”给它。本插件通过读取**系统剪贴板**中的图片（截图 `Win + Shift + S` 或复制图片即可，无需上传文件），交给用户自行配置的视觉 API 识别成文字，再由 DeepSeek 基于文字继续推理。

## 典型使用场景

- 程序报错截图 → 分析原因并给出修复方法
- 书页 / PPT / 名片 → 一键提取文字（OCR）
- 扫描版 PDF 文档 → 批量转可编辑 DOCX（忽略水印、补全遮挡文字、保留古籍影印）
- 图表 / UI 设计稿 → 结构化解读与建议
- 图片表格 → 提取为可编辑 Word 表格（含国际音标等特殊符号）
- 语言学教材音标页 → 对照原图二次核对
- DOCX 交付前 → 自动渲染质检

## 功能一览

- 图片分析 / OCR：`analyze_image`、`ocr_extract`、`ocr_precise`（MCP 工具）
- 剪贴板取图：截图（Win+Shift+S）后直接让模型“看图”
- 扫描 PDF 批量转文本：分页渲染 → 水印感知 OCR → 每页文本 + 合并文档
- 古籍影印区域：视觉检测后精确裁剪保留为图片，不做整页插图
- 图片表格 → 可编辑 Word 表格；国际音标/语言学符号二次核对
- DOCX 转换校验与视觉渲染检查（LibreOffice 后台运行）

## 安装（接收方）

### 方法一：从本仓库安装（推荐）

```bash
codex plugin marketplace add https://github.com/wssfk12138/deepseek-vision
codex plugin add deepseek-vision@deepseek-vision
```

然后运行安装脚本：

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\plugins\deepseek-vision\scripts\setup.ps1"
```

```bash
# macOS / Linux
bash ~/plugins/deepseek-vision/scripts/setup.sh
```

### 方法二：下载 zip 手动安装

1. 下载本仓库代码（Code → Download ZIP），解压到 `%USERPROFILE%\plugins\deepseek-vision`；
2. 运行 `scripts\setup.ps1`（Windows）或 `scripts\setup.sh`（macOS/Linux）；
3. 编辑插件根目录 `.env`，填入**自己的** API 请求地址、密钥与模型名（模板见 `assets/env.example`）；
4. 重启 Codex，从个人市场安装 deepseek-vision。

## 使用

安装后直接发图或截图，说“看看这张图”；扫描 PDF 转 Word 见 `pdf-ocr-conversion` 技能；表格与音标处理见 `table-extraction` 技能。

## 隐私与安全

- 图片会发送到你配置的视觉 API 提供商，敏感图片请谨慎处理。
- 本仓库不包含任何 API 密钥；每个用户必须配置自己的密钥。
- 剪贴板取图功能仅限 Windows。

## 许可

MIT License（本插件封装了 MIT 协议的 [mcp-vision](https://github.com/hahahahanb/mcp-vision) 作为视觉桥接层）。
