#!/usr/bin/env bash
# The --sandbox unshare-rnm check for card 022, in a throwaway Linux container that stands in for the cloud VM (root,
# network on). No model call. From the repository root on the host:
#
#   podman run --rm --cpus 1 -v "$PWD:/src:ro" docker.io/library/python:3.11-slim-bookworm \
#       bash /src/experiments/forecast_tasks/container_sandbox_check.sh
#
# It copies the checkout (without .runtime and runs) to /work, installs pillow and git, makes /work a fresh git
# repository, plants a stand-in sealed file at /root/harness-sealed/022/resolutions.json, then runs through run_pilot.py
# on the first calibration question: the peeker unwrapped (expect rejected: everything reached), the peeker, gold and
# noop with --sandbox unshare-rnm (expect accepted, accepted, rejected), and the Linux-only unit test
# SandboxEffectTests. It prints each run's outcome and the peeker's probe lines.
set -euo pipefail
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir /work
tar -C /src --exclude=./.runtime --exclude=./experiments/p6_pilot/runs -cf - . | tar -C /work -xf -
cd /work
pip install -q --root-user-action=ignore pillow >/dev/null 2>&1
apt-get -qq update >/dev/null && apt-get -qq install -y git >/dev/null 2>&1
rm -rf .git && git init -q . && git -c user.name=check -c user.email=check@localhost add -A \
  && git -c user.name=check -c user.email=check@localhost commit -qm snapshot
mkdir -p /root/harness-sealed/022 && echo '{"stand-in": true}' > /root/harness-sealed/022/resolutions.json
export RETICLE_TASK_PYTHON="$(command -v python)"
TASK="$(python -c "import json; print(json.load(open('experiments/forecast_tasks/splits.json'))['calibration'][0])")"
echo "task $TASK; unshare $(unshare --version | head -1); uid $(id -u)"
for run in "peeker plain" "peeker sandbox" "gold sandbox" "noop sandbox"; do
  set -- $run
  extra=()
  [ "$2" = sandbox ] && extra=(--sandbox unshare-rnm)
  printf '%-16s ' "$1 $2"
  python experiments/p6_pilot/run_pilot.py --client "$1" --arm pressure-recent-v3 \
    --tasks experiments/forecast_tasks/tasks.forecast.json "$TASK" --run-name "check-$1-$2" --max-calls-per-run 12 \
    "${extra[@]}" 2>&1 | tail -1
done
python - <<'PY'
import json
for name in ("check-peeker-plain", "check-peeker-sandbox", "check-gold-sandbox"):
    record = json.loads(open(f"experiments/p6_pilot/runs/{name}/results.jsonl").read().splitlines()[0])
    forecast = record["acceptance"]["forecast"]
    print(name, "protocol", record["protocol_hash"], "committed", forecast["committed"],
          "agreement", forecast["reading_agreement"])
    for result in record["tool_results"]:
        if "peek.py" in result["head"] and "status" in result["head"]:
            print("  " + " ".join(result["head"].split("--- stdout ---")[1].split()))
PY
python -m unittest tests.test_forecast_prereqs.SandboxEffectTests 2>&1 | tail -3
