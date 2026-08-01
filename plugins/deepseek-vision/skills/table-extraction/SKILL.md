---
name: table-extraction
description: 把扫描页/图片中的表格转换为可编辑的 Word 表格：视觉模型提取结构化数据（保留国际音标等特殊符号），或把 OCR 文本中的表格行解析为真实表格。组装 DOCX 时使用。
---

# 表格提取与转换

把图片格式化的表格变成 Word 中可编辑的真表格，而不是等宽文本。

## 适用时机

- 扫描 PDF 或图片中有表格（音标表、辨析表、声母表、答题表等），需要可编辑
- OCR 文本中以 `|` 或 `┌┬┐` 框线形式出现的表格
- DOCX 组装时希望表格保持结构（行列、表头、边框）

## 两种方式

### 1. 视觉提取（图片表格 → JSON）

```powershell
scripts\table_extract.ps1 --pdf "C:\扫描书.pdf" --pages "5,26,56" --out "C:\tables"
```

视觉模型把页面上的表格识别为结构化 JSON（`tables.json`：每页 `{"tables": [{"rows": [[...]]}]}`），空单元格保留、国际音标等符号原样输出。

### 2. 文本解析（OCR 表格 → Word 表格）

```powershell
.venv\Scripts\python.exe scripts\docx_tables.py --input "第56页表格.txt" --output "表格.docx"
```

`docx_tables.py` 可被 DOCX 组装脚本直接导入：

```python
from docx_tables import parse_ascii_table, add_table_to_doc, add_json_tables
rows = parse_ascii_table(table_lines)      # 文本表格 -> 二维数组
add_table_to_doc(doc, rows)                # 二维数组 -> Word 表格
add_json_tables(doc, tables_json_data)     # 视觉提取结果 -> Word 表格
```

表格使用 Table Grid 样式、内容比例列宽、表头加粗、单元格内红色 [?] 保留。

## 注意事项

- 视觉提取对复杂表格（合并单元格、斜线表头）可能简化结构，需人工抽查。
- 国际音标等特殊符号在提取时已要求原样保留；若仍有错误，配合 `ipa_check` 做音标专项核对。
