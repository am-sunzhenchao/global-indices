---
name: global-indices
description: 全球主要指数行情速览。查询纳斯达克100、标普500、道琼斯、创业板、日经225、韩国KOSPI、印度SENSEX、德国DAX最新值及与昨天/上周/上月的涨跌幅，同时查询快手(1024.HK)最新股价折算成人民币后乘以4.6的总值（单位：万元）。结果通过ServerChan推送到微信。触发词包括：全球指数、今日指数、指数行情、涨跌幅速览、快手估值、全球市场概览。
---

# 全球指数 + 快手估值速览

查询8大全球指数最新行情 + 快手股价估值，推送到微信。

## 相关脚本

| 脚本 | 作用 |
|------|------|
| `scripts/fetch_indices.py` | 查询8大指数最新值及涨跌幅（昨天/上周/上月对比） |
| `scripts/notify_wechat.py` | 通过 ServerChan 推送结果到微信 |
| `scripts/daily_indices_push.sh` | 定时执行入口脚本（供 crontab / CronCreate 调用） |

## 快速使用

```bash
# 仅查看，不推送
python3 ~/.claude/skills/global-indices/scripts/fetch_indices.py --dry-run

# 查询 + 推送微信
SERVERCHAN_SEND_KEY=SCTxxxxx python3 ~/.claude/skills/global-indices/scripts/fetch_indices.py

# 定时脚本（内含重试+日志）
bash ~/.claude/skills/global-indices/scripts/daily_indices_push.sh
```

## 环境变量

```bash
export SERVERCHAN_SEND_KEY=SCTxxxxxxxx   # 从 https://sct.ftqq.com/ 获取
```

## 安装依赖

```bash
pip3 install -r ~/.claude/skills/global-indices/scripts/requirements.txt
```

## 工作流程

1. 通过腾讯财经 `qt.gtimg.cn` 获取各指数实时行情
2. 计算与昨日收盘、上周收盘、上月收盘的变化百分比
3. 查询快手(1024.HK)股价 + HKD→CNY 汇率，计算 `股价 × 汇率 × 4.6`（万元）
4. 拼装 Markdown 格式报告，通过 ServerChan 推送微信

## 指数列表

| 指数 | 代码 | 说明 |
|------|------|------|
| 纳斯达克100 | NDX | 美股科技龙头 |
| 标普500 | SPX | 美股大盘 |
| 道琼斯 | DJI | 美股工业指数 |
| 创业板指 | 399006.SZ | A股成长股 |
| 日经225 | N225 | 日本大盘 |
| 韩国KOSPI | KS11 | 韩国大盘 |
| 印度SENSEX | BSESN | 印度大盘 |
| 德国DAX | GDAXI | 德国大盘 |
