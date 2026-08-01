"""配置自检：验证 .env 中的 API 请求地址与 Key 是否已配置（可选 --ping 实测连通）。"""

from __future__ import annotations

import argparse
import sys

import httpx

from vision_config import ConfigError, mask_key, resolve_config


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="deepseek-vision 配置自检")
    parser.add_argument("--ping", action="store_true", help="同时请求 {base_url}/models 实测密钥与地址可用性")
    args = parser.parse_args()

    try:
        cfg = resolve_config()
    except ConfigError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print(f"[OK] Provider: {cfg['provider']}")
    print(f"[OK] API 请求地址: {cfg['base_url']}")
    print(f"[OK] API Key: {mask_key(cfg['api_key'])}")
    print(f"[OK] 视觉模型: {cfg['model']}")

    if args.ping:
        try:
            resp = httpx.get(
                f"{cfg['base_url'].rstrip('/')}/models",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                timeout=30,
            )
            if resp.status_code == 200:
                print("[OK] 连通性测试通过（可访问 /models）")
                return 0
            print(f"[FAIL] 连通性测试失败 HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"[FAIL] 连通性测试失败: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
