"""
通过 ServerChan (server 酱) 把全球指数速览推送到微信文件传输助手。

免费版限制: 每日 5 条。建议每次合并成 1 条发送。

支持多账号: 在 .env 中配置多个 SERVERCHAN_SEND_KEY* 变量即可：
    SERVERCHAN_SEND_KEY=SCTxxx       # 账号1（主）
    SERVERCHAN_SEND_KEY_1=SCTxxx     # 账号2
    SERVERCHAN_SEND_KEY_2=SCTxxx     # 账号3
    # 所有匹配 SERVERCHAN_SEND_KEY* 的变量都会收到推送

用法:
    python notify_wechat.py --title "全球指数速览 2026-06-17" --content "$(cat report.md)"
    cat report.md | python notify_wechat.py --title "全球指数速览 2026-06-17"

环境变量:
    SERVERCHAN_SEND_KEY   必填（主账号）
    SERVERCHAN_SEND_KEY_N 可选（追加账号，N 为任意后缀）

依赖: requests
"""

import argparse
import json
import os
import sys
import time

import requests

SERVERCHAN_URL_TEMPLATE = "https://sctapi.ftqq.com/{key}.send"
MAX_SEND_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2


def collect_send_keys(primary_key: str) -> list[str]:
    """收集所有 SERVERCHAN_SEND_KEY* 环境变量，去重后返回列表。"""
    seen = set()
    keys = []
    for k, v in os.environ.items():
        if k.startswith("SERVERCHAN_SEND_KEY") and v.strip():
            v = v.strip()
            if v not in seen:
                seen.add(v)
                keys.append(v)
    if primary_key and primary_key not in seen:
        keys.insert(0, primary_key)
    return keys


def send(title: str, content: str, send_key: str, timeout: int = 15) -> Dict:
    """Push to ServerChan with retries.

    Retries on network errors and 5xx responses (exponential backoff).
    Does NOT retry on 4xx (quota exhausted / invalid key / bad payload) — these
    won't fix themselves on retry and we want to fail fast + surface the code.
    """
    url = SERVERCHAN_URL_TEMPLATE.format(key=send_key)
    last_err = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            resp = requests.post(url, data={"title": title, "desp": content}, timeout=timeout)
            if resp.status_code >= 500 and attempt < MAX_SEND_ATTEMPTS:
                last_err = f"http {resp.status_code}"
                time.sleep(RETRY_BACKOFF_BASE ** attempt)
                continue
            try:
                return resp.json()
            except ValueError:
                return {"status": resp.status_code, "text": resp.text[:500]}
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < MAX_SEND_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_BASE ** attempt)
                continue
    return {"code": -1, "error": last_err or "unknown"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Push IPO summary to WeChat via ServerChan.")
    parser.add_argument("--title", required=True, help="Message title (<= 32 chars recommended).")
    parser.add_argument("--content", help="Message body (Markdown). If omitted, read from stdin.")
    parser.add_argument("--send-key", help="Override SERVERCHAN_SEND_KEY env var.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload instead of sending.")
    args = parser.parse_args()

    send_key = args.send_key or os.environ.get("SERVERCHAN_SEND_KEY", "").strip()
    if not send_key and not args.dry_run:
        print("[notify_wechat] SERVERCHAN_SEND_KEY not set. Use env var or --send-key.", file=sys.stderr)
        return 2

    if args.content is not None:
        content = args.content
    else:
        content = sys.stdin.read()

    if not content.strip():
        print("[notify_wechat] empty content, aborting.", file=sys.stderr)
        return 3

    if args.dry_run:
        print(f"TITLE: {args.title}")
        print("---")
        print(content)
        return 0

    keys = collect_send_keys(send_key)
    if not keys:
        print("[notify_wechat] no SERVERCHAN_SEND_KEY found. Set env var or --send-key.", file=sys.stderr)
        return 2

    print(f"[notify_wechat] pushing to {len(keys)} account(s)...", file=sys.stderr)
    results = []
    all_ok = True
    for k in keys:
        result = send(args.title, content, k)
        results.append({"key_tail": k[-6:], "result": result})
        code = result.get("code") if isinstance(result, dict) else None
        if code != 0:
            all_ok = False
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all_ok else 1
