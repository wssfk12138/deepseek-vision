"""MCP 冒烟测试：启动 deepseek-vision 服务器并确认工具列表。

用法:
    python scripts/smoke_test.py

只做 MCP 握手（initialize + tools/list），不消耗任何 API 额度。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
START_COMMAND = [
    "uv",
    "tool",
    "run",
    "--env-file",
    ".env",
    "--with",
    "mcp[cli]<2",
    "mcp-vision",
]

REQUEST_ID = 0


def next_id() -> int:
    global REQUEST_ID
    REQUEST_ID += 1
    return REQUEST_ID


def read_message(proc: subprocess.Popen) -> dict:
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("服务器提前退出，未收到响应")
    return json.loads(line.decode("utf-8"))


def send_message(proc: subprocess.Popen, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    proc.stdin.write(body + b"\n")
    proc.stdin.flush()


def drain_stderr(proc: subprocess.Popen, sink: list[str], lock: threading.Lock) -> None:
    for raw in proc.stderr:
        with lock:
            sink.append(raw.decode("utf-8", errors="replace"))


def main() -> int:
    if not shutil.which("uv"):
        print("未找到 uvx/uv，请先运行 scripts/setup.ps1 或 scripts/setup.sh", file=sys.stderr)
        return 1
    command = START_COMMAND
    print(f"启动服务器: {' '.join(command)}", flush=True)
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=PLUGIN_ROOT,
    )
    stderr_sink: list[str] = []
    stderr_lock = threading.Lock()
    stderr_thread = threading.Thread(
        target=drain_stderr, args=(proc, stderr_sink, stderr_lock), daemon=True
    )
    stderr_thread.start()
    try:
        send_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "deepseek-vision-smoke-test", "version": "1.0.0"},
                },
            },
        )
        print("已发送 initialize，等待响应...", flush=True)
        init = read_message(proc)
        if "error" in init:
            raise RuntimeError(f"initialize 失败: {init['error']}")
        print(f"服务器: {init.get('result', {}).get('serverInfo')}", flush=True)

        send_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": next_id(),
                "method": "tools/list",
                "params": {},
            },
        )
        print("已发送 tools/list，等待响应...", flush=True)
        tools = read_message(proc)
        if "error" in tools:
            raise RuntimeError(f"tools/list 失败: {tools['error']}")
        names = sorted(tool["name"] for tool in tools["result"]["tools"])
        print(f"可用工具: {', '.join(names)}", flush=True)
        expected = {"analyze_image", "ocr_extract", "ocr_precise"}
        if not expected.issubset(set(names)):
            raise RuntimeError(f"缺少预期工具: {expected - set(names)}")
        print("冒烟测试通过 [OK]", flush=True)
        return 0
    except Exception as exc:
        with stderr_lock:
            tail = "\n".join(stderr_sink[-25:])
        if tail:
            print(f"--- 服务器 stderr（末尾）---\n{tail}", file=sys.stderr)
        raise
    finally:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            try:
                proc.terminate()
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
