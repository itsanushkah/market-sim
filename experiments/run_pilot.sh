#!/usr/bin/env bash
# Small-market pilot: 6 traders, one good, 6 rounds per period. With vs without the analyst, plus ZI-C.
# Restartable (finished runs are skipped).   caffeinate -i bash experiments/run_pilot.sh
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LOG=results/pilot.log
run() {  # config suffix seed [extra args]
  local cfg=$1 suffix=$2 seed=$3; shift 3
  local name; name=$(grep -m1 '^name:' "$cfg" | awk '{print $2}')$suffix
  if [ -f "results/$name/seed_$seed/metrics.json" ]; then echo "skip $name seed $seed (done)" | tee -a "$LOG"; return; fi
  echo "=== $(date '+%F %T') start $name seed $seed" | tee -a "$LOG"
  $PY -u -m experiments.runner --config "$cfg" --seeds "$seed" --rounds 6 --name-suffix "$suffix" "$@" 2>&1 | tee -a "$LOG"
}
for s in 0 1 2 3 4 5 6 7 8 9; do run experiments/configs/pilot/zi_c.yaml _r6 $s; done
for s in 0 1 2; do
  for c in llm_full no_analyst; do
    run experiments/configs/pilot/$c.yaml _qwen3b_r6 $s --backend ollama --model qwen2.5:3b
  done
done
echo "=== $(date '+%F %T') pilot finished" | tee -a "$LOG"
