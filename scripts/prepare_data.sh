#!/usr/bin/env bash
# prepare_data.sh —— Jarvis 训练数据准备入口（下载 → 清洗 → 分档）
#
# 用法：
#   scripts/prepare_data.sh download    # 只下载
#   scripts/prepare_data.sh clean       # 只清洗
#   scripts/prepare_data.sh tier        # 只分档
#   scripts/prepare_data.sh all         # 全部（默认）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export JARVIS_DATA="${JARVIS_DATA:-/home/lukakrajina/JarvisLearnData}"
CMD="${1:-all}"

echo "[Jarvis] 数据目录：$JARVIS_DATA"
python3 "$SCRIPT_DIR/prepare_data.py" "$CMD"
