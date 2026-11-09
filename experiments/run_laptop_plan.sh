#!/usr/bin/env bash
# Reduced experiment plan that fits a laptop running a local model (Ollama, qwen2.5:3b).
#   - 6 rounds per period (most trades happen in the first 6 of 10 rounds anyway)
#   - LLM conditions: llm_full, no_analyst, no_comms, shock; seeds 0-2
#   - Runs are ordered seed-first, so if it stops early you still have every condition for the seeds done so far.
#   - Baselines (ZI-C, ZI-U, oracle, shock ZI-C) use the same 6 rounds so comparisons are fair; they take seconds.
# Finished runs are skipped, so the script can be restarted after an interruption.
#
#   bash experiments/run_laptop_plan.sh            # everything
#   bash experiments/run_laptop_plan.sh baselines  # baselines only
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
ROUNDS=6
MODEL=qwen2.5:3b
LOG=results/laptop_plan.log

run() {  # config suffix seed [extra args]
  local cfg=$1 suffix=$2 seed=$3; shift 3
  local name; name=$(grep -m1 '^name:' "$cfg" | awk '{print $2}')$suffix
  if [ -f "results/$name/seed_$seed/metrics.json" ]; then
    echo "skip $name seed $seed (done)" | tee -a "$LOG"; return
  fi
  echo "=== $(date '+%F %T') start $name seed $seed" | tee -a "$LOG"
  $PY -u -m experiments.runner --config "$cfg" --seeds "$seed" --rounds $ROUNDS --name-suffix "$suffix" "$@" 2>&1 | tee -a "$LOG"
}

# Baselines (seconds)
for s in 0 1 2 3 4 5 6 7 8 9; do
  run experiments/configs/baselines/zi_c.yaml _r6 $s
  run experiments/configs/baselines/zi_u.yaml _r6 $s
  run experiments/configs/robustness/shock_zi.yaml _r6 $s
done
run experiments/configs/baselines/centralized_oracle.yaml _r6 0
[ "${1:-}" = "baselines" ] && exit 0

# LLM conditions (slow), seed-first
for s in 0 1 2; do
  for cfg in main/llm_full ablations/no_analyst ablations/no_comms robustness/shock; do
    run "experiments/configs/$cfg.yaml" _qwen3b_r6 $s --backend ollama --model $MODEL
  done
done
echo "=== $(date '+%F %T') plan finished" | tee -a "$LOG"
