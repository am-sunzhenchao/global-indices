#!/bin/bash
# Daily global indices push - 查询全球指数 + 快手估值并推送微信
#
# 功能:
# - 查询8大全球指数最新行情及涨跌幅
# - 查询快手股价估值（HKD × 汇率 × 4.6，单位：万元）
# - 通过 ServerChan 推送到微信
# - 失败时最多重试 MAX_ATTEMPTS 次，全部失败推送告警

set -u

export PATH="/opt/miniconda3/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

ENV_FILE="$HOME/.claude/skills/global-indices/.env"
if [ -f "$ENV_FILE" ]; then
  set -o allexport; source "$ENV_FILE"; set +o allexport
fi

SKILL_DIR="$HOME/.claude/skills/global-indices"
LOG_DIR="$HOME/indices-reports/logs"
TODAY=$(date +%Y%m%d)
LOG_FILE="$LOG_DIR/indices-${TODAY}.log"
PYTHON_BIN="python3"
MAX_ATTEMPTS=3
RETRY_BACKOFF=30

DONE_MARKER="$LOG_DIR/indices-${TODAY}.done"

mkdir -p "$LOG_DIR"
find "$LOG_DIR" -name 'indices-*.log' -type f -mtime +7 -delete 2>/dev/null
find "$LOG_DIR" -name 'indices-*.done' -type f -mtime +7 -delete 2>/dev/null

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

notify_failure() {
  local attempts=$1
  local reason=$2
  local notify="$SKILL_DIR/scripts/notify_wechat.py"
  if [ ! -f "$notify" ]; then
    log "[WARN] notify_wechat.py not found"
    return
  fi
  local body
  body=$(cat <<EOF
> **全球指数巡检 $(date '+%Y-%m-%d') 执行失败**

- 已重试次数: ${attempts}
- 失败原因: ${reason}
- 日志路径: \`${LOG_FILE}\`

请手动执行 \`bash $SKILL_DIR/scripts/daily_indices_push.sh\` 排查。
EOF
)
  "$PYTHON_BIN" "$notify" \
    --title "全球指数推送失败 $(date '+%m-%d')" \
    --content "$body" 2>&1 | tee -a "$LOG_FILE" || true
}

log "===== indices push start ====="

if [ -f "$DONE_MARKER" ]; then
  log "[SKIP] today's push already completed, exiting."
  exit 0
fi

attempt=0
final_rc=0
while [ $attempt -lt $MAX_ATTEMPTS ]; do
  attempt=$((attempt + 1))
  log "[INFO] attempt $attempt/$MAX_ATTEMPTS"

  "$PYTHON_BIN" "$SKILL_DIR/scripts/fetch_indices.py" 2>&1 | tee -a "$LOG_FILE"
  rc=${PIPESTATUS[0]}

  if [ $rc -eq 0 ]; then
    log "[OK] push succeeded (attempt $attempt)"
    touch "$DONE_MARKER"
    log "===== indices push end (success) ====="
    exit 0
  fi

  final_rc=$rc
  log "[WARN] attempt $attempt failed (rc=$rc)"
  if [ $attempt -lt $MAX_ATTEMPTS ]; then
    log "[INFO] sleep ${RETRY_BACKOFF}s before retry..."
    sleep "$RETRY_BACKOFF"
  fi
done

log "[ERROR] all $MAX_ATTEMPTS attempts failed (rc=$final_rc)"
notify_failure "$MAX_ATTEMPTS" "fetch_indices.py exit rc=$final_rc"
log "===== indices push end (failed) ====="
exit 1
