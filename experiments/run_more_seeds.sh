#!/usr/bin/env bash
# Two more repeats (seeds 3-4) of the main comparison: full system vs no analyst, 6 rounds per period.
# Restartable (finished runs are skipped).   caffeinate -i bash experiments/run_more_seeds.sh
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LOG=results/more_seeds.log
run() {  # config suffix seed [extra args]
  local cfg=$1 suffix=$2 seed=$3; shift 3
  local name; name=$(grep -m1 '^name:' "$cfg" | awk '{print $2}')$suffix
  if [ -f "results/$name/seed_$seed/metrics.json" ]; then echo "skip $name seed $seed (done)" | tee -a "$LOG"; return; fi
  echo "=== $(date '+%F %T') start $name seed $seed" | tee -a "$LOG"
  $PY -u -m experiments.runner --config "$cfg" --seeds "$seed" --rounds 6 --name-suffix "$suffix" "$@" 2>&1 | tee -a "$LOG"
}
for s in 3 4; do
  for c in main/llm_full ablations/no_analyst; do
    run experiments/configs/$c.yaml _qwen3b_r6 $s --backend ollama --model qwen2.5:3b
  done
done
echo "=== $(date '+%F %T') extra seeds finished" | tee -a "$LOG"
