#!/usr/bin/env bash
# train.sh —— Jarvis 1.0 训练脚本（Linux）
#
# 用法：
#   scripts/train.sh [--variant flash|pro|ultra|vision] [--pb 0.5|1.0|3.0|5.0] [--moe] [--data <dir>]
#
# 职责：
#   1. 定位 Ravendrel 运行时（RVDL_ROOT 或相对路径）
#   2. 用 rvdl CLI 把 Jarvis 模型编译成 .rvdli（加密模块）
#   3. 启动 Transmitter（Fox GUI 的 QLM 训练器）做训练
#
# 训练的对象是 Chimera 架构的 64 维参数空间 p00..p63（跨 MMI_INVOKE 持久 = 模型权重），
# 用 QGT 自然梯度 + 有限差分优化（几何演化，非反向传播）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

# ── 参数解析 ─────────────────────────────────────────────────────────────
VARIANT="flash"
PB="1.0"
MOE=""
DATA_DIR="${ROOT}/data"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant) VARIANT="$2"; shift 2 ;;
    --pb)      PB="$2";      shift 2 ;;
    --moe)     MOE="--moe";  shift ;;
    --data)    DATA_DIR="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# ── 定位 Ravendrel ────────────────────────────────────────────────────────
RVDL_ROOT="${RVDL_ROOT:-$(cd "$ROOT/../Ravendrel" && pwd)}"
if [[ ! -f "$RVDL_ROOT/server/out/cli.js" ]]; then
  echo "[错误] 找不到 Ravendrel CLI：$RVDL_ROOT/server/out/cli.js"
  echo "       请先构建 Ravendrel（cd $RVDL_ROOT && npm run build），或设 RVDL_ROOT。"
  exit 1
fi
CLI="$RVDL_ROOT/server/out/cli.js"

# ── 校验分型 ─────────────────────────────────────────────────────────────
case "$VARIANT" in
  flash|pro|ultra|vision) ;;
  *) echo "[错误] --variant 必须是 flash|pro|ultra|vision，得到 '$VARIANT'"; exit 1 ;;
esac
CONFIG="$ROOT/configs/$VARIANT.json"
[[ -f "$CONFIG" ]] || { echo "[错误] 找不到配置 $CONFIG"; exit 1; }
echo "[Jarvis] 变体=$VARIANT  pB=$PB${MOE:+ MoE}"

# ── 校验训练数据 ─────────────────────────────────────────────────────────
if [[ ! -d "$DATA_DIR" ]] || [[ -z "$(find "$DATA_DIR" -type f \( -name '*.txt' -o -name '*.md' -o -name '*.rvdl' \) 2>/dev/null | head -1)" ]]; then
  echo "[错误] 训练数据目录 $DATA_DIR 为空或不存在（需要 .txt/.md/.rvdl 文本）。"
  echo "       训练数据来源见 README §5（开源可商用，中英 5:5）。"
  exit 1
fi

# ── 编译 Jarvis 模型（.rvdl → .rvdli 加密模块）────────────────────────────
# 多模态变体（vision）编译 jarvis_vision.rvdl（--moe 时 jarvis_vision_moe.rvdl），
# 其余分型编译 jarvis_core.rvdl。
MODEL="$ROOT/models/jarvis_core.rvdl"
if [[ "$VARIANT" == "vision" ]]; then
  MODEL="$ROOT/models/jarvis_vision.rvdl"
  [[ -n "$MOE" ]] && MODEL="$ROOT/models/jarvis_vision_moe.rvdl"
fi
OUT_DIR="$ROOT/out"
mkdir -p "$OUT_DIR"
echo "[Jarvis] 编译模型 $MODEL ..."
node "$CLI" mmi "$MODEL" -o "$OUT_DIR/jarvis_${VARIANT}.rvdli" \
  || { echo "[错误] 模型编译失败"; exit 1; }
echo "[Jarvis] 模型已编译到 $OUT_DIR/jarvis_${VARIANT}.rvdli"

# ── 启动 Transmitter（训练）───────────────────────────────────────────────
TRANSMITTER="$RVDL_ROOT/runtime/build/transmitter"
if [[ ! -x "$TRANSMITTER" ]]; then
  echo "[提示] 找不到 Transmitter 二进制（$TRANSMITTER）。"
  echo "       请先构建：cd $RVDL_ROOT/runtime && cmake --build build --target transmitter"
  echo "       然后在 Transmitter GUI 里：把 $DATA_DIR 加入训练集 → 点训练 → 导出 .rvdlm。"
  echo "       （变体参数 $VARIANT / pB=$PB 已在 configs/$VARIANT.json 里。）"
  exit 0
fi
echo "[Jarvis] 启动 Transmitter（训练）..."
exec "$TRANSMITTER"