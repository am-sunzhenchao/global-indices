"""
查询8大全球指数最新行情及涨跌幅，同时查询快手(1024.HK)股价估值。

指数列表:
  纳斯达克100 (^NDX)、标普500 (^GSPC)、道琼斯 (^DJI)
  创业板指 (sz399006)、日经225 (^N225)、韩国KOSPI (^KS11)
  印度SENSEX (^BSESN)、德国DAX (^GDAXI)

输出:
  - 各指数最新值
  - 与昨天/上周/上月的涨跌幅
  - 快手股价 × 汇率 × 4.7（万元）

用法:
    python fetch_indices.py              # 查询 + 推送微信
    python fetch_indices.py --dry-run    # 仅打印，不推送

环境变量:
    SERVERCHAN_SEND_KEY  推送必填（--dry-run 时可省）

依赖: requests
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import requests

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1y"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={codes}"
ER_API_URL = "https://open.er-api.com/v6/latest/HKD"
SERVERCHAN_URL_TEMPLATE = "https://sctapi.ftqq.com/{key}.send"

CACHE_DIR = os.path.expanduser("~/indices-reports/cache")

YAHOO_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
TENCENT_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://gu.qq.com/",
}


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


# 指数配置: (显示名, Yahoo代码, 腾讯备用代码或None)
INDICES = [
    ("纳斯达克100", "^NDX",    None),
    ("标普500",    "^GSPC",   None),
    ("道琼斯",     "^DJI",    None),
    ("创业板指",   None,      "sz399006"),
    ("日经225",    "^N225",   None),
    ("韩国KOSPI",  "^KS11",   None),
    ("印度SENSEX", "^BSESN",  None),
    ("德国DAX",    "^GDAXI",  None),
]

KUAISHOU_TENCENT_CODE = "hk01024"
MULTIPLIER = 4.7


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def load_cache(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r") as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(key: str, data: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    data["_saved_at"] = datetime.now().isoformat()
    with open(_cache_path(key), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _find_close_by_offset(timestamps: list, closes: list, days_ago: int) -> Optional[float]:
    now_ts = datetime.now().timestamp()
    target_ts = now_ts - days_ago * 86400
    best_idx = -1
    for i, ts in enumerate(timestamps):
        if closes[i] is None:
            continue
        if ts <= target_ts:
            best_idx = i
    if best_idx >= 0:
        return closes[best_idx]
    first_valid = -1
    for i in range(len(closes)):
        if closes[i] is not None:
            first_valid = i
            break
    if first_valid >= 0:
        if days_ago <= 7:
            return closes[first_valid + 1] if first_valid + 1 < len(closes) else None
        if days_ago >= 300:
            return closes[first_valid]
    return None


def fetch_yahoo_index(symbol: str) -> dict:
    """通过 Yahoo Finance 查询指数行情及历史收盘价 (range=3mo)"""
    url = YAHOO_CHART_URL.format(symbol=symbol)
    resp = requests.get(url, headers=YAHOO_UA, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    result = data["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result.get("timestamp", [])
    closes_raw = result["indicators"]["quote"][0]["close"]

    price = meta.get("regularMarketPrice", 0.0)
    name = meta.get("shortName", symbol).strip()

    close_1d = _find_close_by_offset(timestamps, closes_raw, 1)
    close_7d = _find_close_by_offset(timestamps, closes_raw, 7)
    close_30d = _find_close_by_offset(timestamps, closes_raw, 30)
    close_1y = _find_close_by_offset(timestamps, closes_raw, 365)

    result_data = {
        "name": name,
        "price": price,
        "close_1d": close_1d,
        "close_7d": close_7d,
        "close_30d": close_30d,
        "close_1y": close_1y,
    }

    save_cache(f"yahoo_{symbol.replace('^', '')}", {
        "price": price,
        "close_1d": close_1d,
        "close_7d": close_7d,
        "close_30d": close_30d,
        "close_1y": close_1y,
        "timestamps_sample": timestamps[:3] if timestamps else [],
    })

    return result_data


def fetch_tencent_quote(code: str) -> dict:
    """通过腾讯财经查询单个代码行情（用于创业板指）"""
    resp = requests.get(TENCENT_QUOTE_URL.format(codes=code), headers=TENCENT_UA, timeout=20)
    resp.raise_for_status()
    text = resp.content.decode("gbk", errors="replace").strip()

    for line in text.splitlines():
        if "=" not in line:
            continue
        val_part = line.split("=", 1)[1].strip().rstrip(";").strip('"')
        fields = val_part.split("~")
        if len(fields) < 32:
            continue
        try:
            price = float(fields[3]) if fields[3] else 0.0
            name = fields[1]
            return {"name": name, "price": price, "close_1d": None, "close_7d": None, "close_30d": None, "close_1y": None}
        except (ValueError, IndexError):
            continue
    return {"name": code, "price": 0.0, "close_1d": None, "close_7d": None, "close_30d": None, "close_1y": None}


def fetch_tencent_index_history(tencent_code: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """通过腾讯日K接口获取1天/7天/30天/365天前收盘价"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=400)
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={tencent_code},day,,"
        f"{end_date.strftime('%Y-%m-%d')},400,qfq"
    )
    try:
        resp = requests.get(url, headers=TENCENT_UA, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        code_key = tencent_code.lower()
        klines = (
            data.get("data", {}).get(code_key, {}).get("day")
            or data.get("data", {}).get(code_key, {}).get("qfqday")
        )
        if not klines or len(klines) < 2:
            return None, None, None, None
        closes = [float(k[2]) for k in klines]
        c1d = closes[-2] if len(closes) >= 2 else None
        c7d = closes[-8] if len(closes) >= 8 else None
        c30d = closes[0] if len(closes) >= 20 else None
        c1y = closes[0] if len(closes) >= 200 else None
        save_cache(f"tencent_{tencent_code}", {
            "close_1d": c1d, "close_7d": c7d, "close_30d": c30d, "close_1y": c1y,
        })
        return c1d, c7d, c30d, c1y
    except Exception:
        return None, None, None, None


def fetch_kuaishou_price() -> float:
    """通过腾讯财经查询快手(1024.HK)最新股价"""
    resp = requests.get(TENCENT_QUOTE_URL.format(codes=KUAISHOU_TENCENT_CODE), headers=TENCENT_UA, timeout=15)
    resp.raise_for_status()
    text = resp.content.decode("gbk", errors="replace").strip()
    for line in text.splitlines():
        if "=" not in line:
            continue
        val_part = line.split("=", 1)[1].strip().rstrip(";").strip('"')
        fields = val_part.split("~")
        if len(fields) >= 4 and fields[3]:
            try:
                return float(fields[3])
            except ValueError:
                pass
    raise RuntimeError("无法获取快手股价")


def fetch_hkd_to_cny() -> Tuple[float, str]:
    resp = requests.get(ER_API_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    rate = data.get("rates", {}).get("CNY")
    if rate is None:
        raise RuntimeError(f"open.er-api.com missing CNY rate: {data}")
    return float(rate), "open.er-api.com"


def pct_str(current: float, base: Optional[float]) -> str:
    if base is None or base == 0:
        return "N/A"
    pct = (current - base) / abs(base) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def arrow(current: float, base: Optional[float]) -> str:
    if base is None:
        return ""
    return "▲" if current >= base else "▼"


def build_report(
    indices_data: list,
    ks_price: float,
    fx: float,
    fx_source: str,
) -> Tuple[str, str]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"**更新时间**: {now}",
        "",
        "## 全球指数速览",
        "",
        "| 指数 | 最新值 | 昨天 | 上周 | 上月 | 去年 |",
        "|------|--------|------|------|------|------|",
    ]

    for item in indices_data:
        name = item["display_name"]
        price = item["price"]
        if price == 0.0:
            lines.append(f"| {name} | — | — | — | — | — |")
            continue
        d1 = pct_str(price, item.get("close_1d"))
        d7 = pct_str(price, item.get("close_7d"))
        d30 = pct_str(price, item.get("close_30d"))
        d1y = pct_str(price, item.get("close_1y"))
        ar1 = arrow(price, item.get("close_1d"))
        price_fmt = f"{price:,.2f}"
        lines.append(f"| {name} | {price_fmt} | {ar1}{d1} | {d7} | {d30} | {d1y} |")

    cny_price = ks_price * fx
    total_shares = MULTIPLIER * 10000
    final_yuan = cny_price * total_shares
    final_w = final_yuan / 10000

    lines += [
        "",
        "---",
        "",
        "## 快手 (1024.HK) 估值快算",
        "",
        f"- 最新股价: **HK$ {ks_price:.4f}**",
        f"- HKD→CNY 汇率: **{fx:.6f}** _(来源: {fx_source})_",
        f"- 折算人民币: ¥ {cny_price:.4f} / 股",
        f"- 持有股数: {MULTIPLIER} 万股（{total_shares:,.0f} 股）",
        "",
        f"### 总市值: **{final_w:.2f} 万元**",
        "",
        "> 数据来源: Yahoo Finance / 腾讯财经 / open.er-api.com，仅供参考，不构成投资建议。",
    ]

    title = f"全球指数 {datetime.now().strftime('%m-%d %H:%M')} | 快手持仓 {final_w:.0f}w"
    body = "\n".join(lines)
    return title, body

def push_serverchan(title: str, content: str, send_key: str, timeout: int = 15) -> dict:
    url = SERVERCHAN_URL_TEMPLATE.format(key=send_key)
    last_err = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, data={"title": title, "desp": content}, timeout=timeout)
            if resp.status_code >= 500 and attempt < 3:
                last_err = f"http {resp.status_code}"
                time.sleep(2 ** attempt)
                continue
            try:
                return resp.json()
            except ValueError:
                return {"status": resp.status_code, "text": resp.text[:500]}
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < 3:
                time.sleep(2 ** attempt)
    return {"code": -1, "error": last_err or "unknown"}


def main() -> int:
    parser = argparse.ArgumentParser(description="全球指数 + 快手估值 推送微信")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不推送")
    parser.add_argument("--send-key", help="覆盖 SERVERCHAN_SEND_KEY 环境变量")
    args = parser.parse_args()

    indices_data = []
    for display_name, yahoo_symbol, tencent_code in INDICES:
        print(f"[INFO] 查询 {display_name}...", file=sys.stderr)
        cache_key = f"yahoo_{yahoo_symbol.replace('^', '')}" if yahoo_symbol else f"tencent_{tencent_code}"
        try:
            if yahoo_symbol:
                item = fetch_yahoo_index(yahoo_symbol)
                item["display_name"] = display_name
            else:
                item = fetch_tencent_quote(tencent_code)
                item["display_name"] = display_name
                c1d, c7d, c30d, c1y = fetch_tencent_index_history(tencent_code)
                item["close_1d"] = c1d
                item["close_7d"] = c7d
                item["close_30d"] = c30d
                item["close_1y"] = c1y
        except Exception as e:
            print(f"[WARN] {display_name} 查询失败: {e}，尝试缓存回退", file=sys.stderr)
            cached = load_cache(cache_key)
            if cached:
                item = {
                    "display_name": display_name,
                    "price": cached.get("price", 0.0),
                    "close_1d": cached.get("close_1d"),
                    "close_7d": cached.get("close_7d"),
                    "close_30d": cached.get("close_30d"),
                    "close_1y": cached.get("close_1y"),
                }
                print(f"[INFO] {display_name} 使用缓存数据 (保存于 {cached.get('_saved_at', 'unknown')})", file=sys.stderr)
            else:
                item = {"display_name": display_name, "price": 0.0, "close_1d": None, "close_7d": None, "close_30d": None, "close_1y": None}
        indices_data.append(item)

    print("[INFO] 查询快手股价...", file=sys.stderr)
    try:
        ks_price = fetch_kuaishou_price()
    except Exception as e:
        print(f"[WARN] 快手股价查询失败: {e}", file=sys.stderr)
        ks_price = 0.0

    print("[INFO] 查询汇率...", file=sys.stderr)
    try:
        fx, fx_source = fetch_hkd_to_cny()
    except Exception as e:
        print(f"[WARN] 汇率查询失败: {e}，使用默认值 0.92", file=sys.stderr)
        fx, fx_source = 0.92, "fallback"

    title, body = build_report(indices_data, ks_price, fx, fx_source)

    if args.dry_run:
        print(f"TITLE: {title}")
        print("---")
        print(body)
        return 0

    send_key = args.send_key or os.environ.get("SERVERCHAN_SEND_KEY", "").strip()
    keys = collect_send_keys(send_key)
    if not keys:
        print("[fetch_indices] SERVERCHAN_SEND_KEY not set.", file=sys.stderr)
        return 2

    print(f"[INFO] pushing to {len(keys)} account(s)...", file=sys.stderr)
    all_ok = True
    results = []
    for k in keys:
        result = push_serverchan(title, body, k)
        results.append({"key_tail": k[-6:], "result": result})
        code = result.get("code") if isinstance(result, dict) else None
        if code != 0:
            all_ok = False

    print(json.dumps(results, ensure_ascii=False))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
