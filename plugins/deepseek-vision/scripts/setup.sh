#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_ROOT="$HOME/.local/bin"
UV_EXE="$UV_ROOT/uv"

echo "=== deepseek-vision 安装脚本 ==="

# 1. 检查 / 安装 uv（优先官方 ~/.local/bin/uv）
if [ ! -x "$UV_EXE" ]; then
  echo "[1/6] 未检测到官方 uv，正在安装..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
else
  echo "[1/6] 已检测到官方 uv。"
fi
export PATH="$UV_ROOT:$PATH"

# 2. 预装 mcp-vision（Python >= 3.11）
#    使用 uv 管理的 Python 3.12，避免系统 Python 位宽导致依赖编译失败；
#    同时锁定 mcp<2，兼容 mcp-vision 当前版本的 FastMCP 导入路径。
echo "[2/6] 准备 Python 3.12 并安装 mcp-vision..."
pkill -f 'mcp-vision' 2>/dev/null || true
"$UV_EXE" python install 3.12
"$UV_EXE" tool install --force --python 3.12 mcp-vision --with 'mcp[cli]<2'

# 3. 批量 OCR 虚拟环境（PDF 渲染 + API 调用）
echo "[3/6] 准备批量 OCR 环境（pypdfium2 / httpx / pillow）..."
if [ ! -x "$PLUGIN_ROOT/.venv/bin/python" ]; then
  "$UV_EXE" venv "$PLUGIN_ROOT/.venv" --python 3.12
fi
"$UV_EXE" pip install --python "$PLUGIN_ROOT/.venv/bin/python" pypdfium2 httpx pillow python-dotenv

# 4. 生成 .env
if [ ! -f "$PLUGIN_ROOT/.env" ]; then
  cp "$PLUGIN_ROOT/assets/env.example" "$PLUGIN_ROOT/.env"
  echo "[4/6] 已生成 .env（模板），请打开并填写 API 请求地址与 API Key。"
else
  echo "[4/6] .env 已存在，跳过创建。"
fi

# 5. 冒烟测试
echo "[5/6] 运行冒烟测试..."
if ! python3 "$PLUGIN_ROOT/scripts/smoke_test.py" && ! python "$PLUGIN_ROOT/scripts/smoke_test.py"; then
  echo "冒烟测试未通过，请检查视觉服务配置。" >&2
  exit 1
fi

# 6. 配置自检（强制：新用户必须配置 API 请求地址与 API Key）
echo "[6/6] 配置自检..."
if ! "$PLUGIN_ROOT/.venv/bin/python" "$PLUGIN_ROOT/scripts/check_config.py"; then
  echo ""
  echo "配置尚未完成：请编辑 $PLUGIN_ROOT/.env，填写 MCP_OCR_BASE_URL / MCP_OCR_API_KEY / MCP_OCR_MODEL，"
  echo "然后重新运行本脚本，或运行：$PLUGIN_ROOT/.venv/bin/python $PLUGIN_ROOT/scripts/check_config.py --ping"
  exit 1
fi

echo ""
echo "下一步："
echo "  1. 编辑 $PLUGIN_ROOT/.env：custom 模式需填写 MCP_OCR_BASE_URL / MCP_OCR_API_KEY / MCP_OCR_MODEL"
echo "  2. 运行 scripts/check_config.py --ping 验证地址与密钥"
echo "  3. 在 Codex 中重新加载插件或重启会话"
