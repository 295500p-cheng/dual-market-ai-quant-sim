#!/usr/bin/env bash

LOCK_DIR="${TMPDIR:-/tmp}/dual-market-ai-quant-cycle.lock.d"
LOCK_PID_FILE="$LOCK_DIR/pid"

acquire_cycle_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$LOCK_PID_FILE"
    return 0
  fi

  LOCK_PID="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
  if [ -n "$LOCK_PID" ] && ! kill -0 "$LOCK_PID" 2>/dev/null; then
    rm -f "$LOCK_PID_FILE"
    rmdir "$LOCK_DIR" 2>/dev/null || true
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      printf '%s\n' "$$" > "$LOCK_PID_FILE"
      return 0
    fi
  fi
  return 1
}

if ! acquire_cycle_lock; then
  echo "{\"status\":\"skipped\",\"reason\":\"已有一轮刷新正在运行，本轮跳过，避免同时写入模拟台账。\",\"lock\":\"$LOCK_DIR\"}"
  exit 0
fi

cleanup_cycle_lock() {
  rm -f "$LOCK_PID_FILE"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

trap cleanup_cycle_lock EXIT
