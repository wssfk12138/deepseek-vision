# DeepSeek Vision — Vision Plugin for Codex

English | [中文](README.zh-CN.md)

> **This is a Codex plugin.** It must be installed and used inside Codex (the ChatGPT desktop app or Codex CLI); it is not a standalone application, website, or browser extension. After installation, invoke it in Codex with `@deepseek-vision` or simply describe the task.

DeepSeek Vision gives text-only models such as DeepSeek a pair of "eyes" inside Codex: image analysis, OCR, batch conversion of scanned PDFs to text, preservation of ancient-book facsimile regions, extraction of image tables into editable Word tables, dedicated verification of IPA (International Phonetic Alphabet) symbols, and visual render QA before DOCX delivery.

The underlying vision model is entirely up to you: fill in an OpenAI-compatible API base URL, key, and model name in `.env` (template at `plugins/deepseek-vision/assets/env.example`). Usage and cost depend on the API provider you choose.

## Why this plugin exists: DeepSeek is a text-only model

**DeepSeek cannot receive images directly** — you cannot "send" an image to it as input. That is exactly the gap this plugin fills:

1. You take a screenshot (`Win + Shift + S`) or copy an image.
2. The plugin reads the image from the **system clipboard** (no file upload or image-attachment UI needed) or from a local path.
3. The image is handed to the vision API you configured, which recognizes it and returns text.
4. DeepSeek continues reasoning, answering, or writing code based on that text.

In short: images are never sent to DeepSeek — the plugin "looks" at them on its behalf and relays what it sees as text.

## How it works

```text
You screenshot/copy an image ──▶ Plugin reads clipboard or local path ──▶ deepseek-vision MCP server ──▶ Vision API
                                                                (mcp-vision)                             │
Codex + DeepSeek ◀────────────── text recognition result ◀────────────────────────────────────────────────┘
```

## Features

- Image analysis / OCR via MCP tools: `analyze_image`, `ocr_extract`, `ocr_precise`
- Clipboard image capture: screenshot (`Win + Shift + S`) and ask the model to "look" at it
- Batch OCR of scanned PDFs: page rendering → watermark-aware OCR → per-page text + merged document
- Ancient-book facsimile regions: detected and embedded as cropped images instead of full-page illustrations
- Image tables → editable Word tables; dedicated IPA / linguistic-symbol second-pass verification
- DOCX conversion verification and visual render checks (headless LibreOffice)

## Typical use cases

- Error screenshot → analyze the cause and suggest a fix
- Book page / PPT / business card → one-shot text extraction (OCR)
- Scanned PDF documents → batch conversion to editable DOCX (ignore watermarks, reconstruct obscured text, preserve ancient-book facsimiles)
- Chart / UI design mockup → structured interpretation and suggestions
- Image table → editable Word table (including special symbols such as IPA)
- IPA pages in linguistics textbooks → second-pass verification against the original image
- Before delivering a DOCX → automatic render QA

## Installation (for users)

### Option 1: Install from this repository (recommended)

```bash
codex plugin marketplace add https://github.com/wssfk12138/deepseek-vision
codex plugin add deepseek-vision@deepseek-vision
```

Then run the setup script:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\plugins\deepseek-vision\scripts\setup.ps1"
```

```bash
# macOS / Linux
bash ~/plugins/deepseek-vision/scripts/setup.sh
```

### Option 2: Manual install from ZIP

1. Download this repository (Code → Download ZIP) and extract it to `%USERPROFILE%\plugins\deepseek-vision`.
2. Run `scripts\setup.ps1` (Windows) or `scripts\setup.sh` (macOS/Linux).
3. Edit `.env` in the plugin root and fill in **your own** API base URL, key, and model name (see `assets/env.example`).
4. Restart Codex and install deepseek-vision from the personal marketplace.

## Configuration

The plugin ships with no default API endpoint or key — you must configure your own vision API in `.env`:

```ini
# OpenAI-compatible vision API (recommended)
MCP_OCR_PROVIDER=custom
MCP_OCR_BASE_URL=https://api.example.com/v1
MCP_OCR_API_KEY=sk-your-key
MCP_OCR_MODEL=Qwen/Qwen3-VL-32B-Instruct
```

Verify the configuration (the `--ping` flag actually tests the endpoint and key):

```powershell
.venv\Scripts\python.exe scripts\check_config.py --ping
```

Provider presets are available in `scripts/vision_config.py`; see `assets/env.example` for the full configuration template.

## Usage

After installation, paste or screenshot an image and say "look at this image". The plugin's `image-analysis` skill routes the request automatically — no manual tool invocation needed. Scanned-PDF-to-Word workflows are documented in the `pdf-ocr-conversion` skill, tables and IPA verification in the `table-extraction` skill, and render QA in the `visual-render-check` skill.

### Sending images in chat (clipboard workflow)

1. Take a screenshot (`Win + Shift + S`) or copy any image (`Ctrl + C`).
2. Back in the Codex conversation, say "analyze the image I just copied" or "look at this screenshot".
3. The plugin automatically saves the image from the clipboard (`images/inbox/`) and hands it to the vision model — no manual file saving needed.

You can also save a screenshot as a file and pass its path directly (e.g. `C:\Users\...\screenshot.png`); the plugin supports that too.

## Privacy & security

- Images are sent to the vision API provider you configure; handle sensitive images with care.
- This repository contains no API keys; every user must configure their own.
- The clipboard capture feature is Windows-only.

## License

MIT License. This plugin wraps the MIT-licensed [mcp-vision](https://github.com/hahahahanb/mcp-vision) as the vision bridge.
