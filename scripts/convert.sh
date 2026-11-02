#!/usr/bin/env bash
# convert.sh —— Jarvis模型格式转换脚本（Linux）
#
# 用法：
#   scripts/convert.sh <in.rvdlm> <out.gguf> [f32|f64|i32|i64|u8]
#   scripts/convert.sh <in.rvdlm> <out.safetensors> [f32|...]
#
# 职责：把 Transmitter 训练好的 .rvdlm 转成 gguf / safetensors，走 ModelInterop
# 的 daemon 文本命令（EXPORT_GGUF / EXPORT_SAFETENSORS）。
#
# 💡 暖心小贴士：gguf 是「便装」，Chimera 的量子态漂移 / 测量坍缩 / 反思回路
#   这些灵魂技能在 gguf 里施展不开。OpenButler 用 .rvdlm 才能百分百释放魅力；
#   gguf 只是给 OpenCode 这类传统朋友「能聊但聊不深」的轻装版。
#   所以——不是谁不够好，是每件衣服都有它适合的场合！
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

[[ $# -ge 2 ]] || { echo "用法: $0 <in.rvdlm> <out.gguf|out.safetensors> [f32|f64|i32|i64|u8]"; exit 1; }
IN="$1"; OUT="$2"; TYPE="${3:-f32}"

# ── 去 Ravendrel 家借工具 ────────────────────────────────────────────────
RVDL_ROOT="${RVDL_ROOT:-$(cd "$ROOT/../Ravendrel" && pwd)}"
CLI="$RVDL_ROOT/server/out/cli.js"
[[ -f "$CLI" ]] || { echo "[错误] 找不到 Ravendrel CLI：$CLI"; exit 1; }

# ── 认认目标格式（gguf 便装 / safetensors 正装）────────────────────────
case "$OUT" in
  *.gguf)        FMT="gguf" ;;
  *.safetensors) FMT="safetensors" ;;
  *) echo "[错误] 输出后缀必须是 .gguf 或 .safetensors"; exit 1 ;;
esac

echo "[Jarvis] 转换 $IN → $OUT（格式=$FMT，dtype=$TYPE）"
node "$CLI" export "$FMT" "$IN" "$OUT" "" "$TYPE"
echo "[Jarvis] 完成：$OUT"