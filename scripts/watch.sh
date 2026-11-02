#!/usr/bin/env bash
# watch.sh —— Jarvis 数据下载守护（含自愈重启）
#
# 每 10 分钟：
#   1. 若 .download_done 存在 → 下载已全部完成，跳到收尾
#   2. 若 prepare_data.py download 在跑 → 记录进度
#   3. 若 download 掉了但未完成 → **自动重启续传**（自愈）
#   4. 收尾：clean + tier（清洗 + 按 pB 分档，许可禁商用源单独目录）
#
# download 内部用 curl -C - 断点续传，重启不丢进度。
set -uo pipefail

ROOT="/home/lukakrajina/JarvisLearnData"
PROGRESS="$ROOT/progress.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOTAL_GB=32   # 维基 12.6 + C4 3 + 代码 ~8 + 论文 ~1 + 轻小说 0.9 + 源码 0.07

log() { echo "[$(date '+%Y-%m-%d %H:%M')] $*" | tee -a "$PROGRESS"; }

start_download() {
    rm -f "$ROOT/raw/.download_done"     # 重启即视为「未完成」
    pkill -f "curl.*hf-mirror.com" 2>/dev/null   # 清残留并发 curl
    sleep 1
    cd "$SCRIPT_DIR" && nohup python3 prepare_data.py download >"$ROOT/download.log" 2>&1 &
    log "自愈：重启下载进程 (PID $!)"
}

while true; do
    # 已完成标记 → 直接进收尾
    if [ -f "$ROOT/raw/.download_done" ]; then
        log "检测到 .download_done，下载已全部完成。"
        break
    fi

    if pgrep -f "prepare_data.py download" >/dev/null; then
        sz=$(du -sm "$ROOT/raw" 2>/dev/null | cut -f1)
        gb=$(awk "BEGIN{printf \"%.2f\", $sz/1024}")
        n=$(pgrep -fc curl 2>/dev/null || echo 0)
        log "下载中：已下 ${gb} GB / ${TOTAL_GB} GB (PID $(pgrep -f 'prepare_data.py download' | head -1), 并发 curl ${n})"
    else
        if [ ! -d "$ROOT/raw" ] || [ -z "$(ls -A "$ROOT/raw" 2>/dev/null)" ]; then
            log "raw 目录为空，首次启动下载。"
            start_download
        else
            find "$ROOT/raw" -name '*.parquet' -size 0 -delete 2>/dev/null
            log "下载进程掉了（未完成标记），raw 已有 $(du -sh "$ROOT/raw" 2>/dev/null | cut -f1)，自动重启续传。"
            start_download
        fi
    fi
    sleep 600
done

# ── 收尾：clean + tier ──────────────────────────────────────────────────
log "开始 clean（清洗）+ tier（按 pB 分档）..."
cd "$SCRIPT_DIR" && python3 prepare_data.py clean >>"$PROGRESS" 2>&1
python3 prepare_data.py tier  >>"$PROGRESS" 2>&1
if ls "$ROOT"/manifest/*/train.txt >/dev/null 2>&1; then
    log "分档完成。各档规模："
    du -sh "$ROOT"/manifest/*/ 2>/dev/null | sed 's/^/    /' | tee -a "$PROGRESS"
else
    log "分档未生成 train.txt，检查 prepare_data.py 日志。"
fi
log "watch.sh 退出。"