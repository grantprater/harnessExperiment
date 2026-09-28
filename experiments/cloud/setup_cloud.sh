#!/usr/bin/env bash
# Prepare a Linux cloud VM (a Claude Code cloud session) to run the experiment pipeline. Idempotent; no sudo.
#
#   bash experiments/cloud/setup_cloud.sh
#
# 1. uv: the one on PATH, else one installed with pip into .runtime/uv-bootstrap (a python3 venv), else with
#    pip install --user.
# 2. Python 3.13.15, the host venvs' interpreter, as a uv-managed CPython (downloaded into the user's uv cache).
#    If uv cannot provide it, the venvs fall back to `python3 -m venv` (the VM's own Python, 3.11 when probed) and
#    the summary says so: that is a different task interpreter from the host's and must be reported with results.
#    RETICLE_CLOUD_PYTHON=/path/to/python makes both venvs from that interpreter instead.
# 3. .runtime/bugs-venv: the task interpreter (run_pilot.TASK_PYTHON resolves .runtime/bugs-venv/bin/python on
#    Linux), exactly experiments/cloud/bugs-venv.requirements.txt (the host's pip freeze).
# 4. .runtime/test-venv: the unit-test interpreter, exactly experiments/cloud/test-venv.requirements.txt.
# 5. .runtime/bug-mining/repos/sqlparse: the clone run_pilot.ensure_commits expects, with the tasks' base commit.
# 6. A readiness summary; the last line is READY or NOT READY (exit 0 or 1).
#
# Environment: OMP/MKL/OPENBLAS_NUM_THREADS=1; installs run at idle priority (nice 19).

set -uo pipefail
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="$ROOT/.runtime"
HERE="$ROOT/experiments/cloud"
PYTHON_VERSION="3.13.15"
UV_VERSION="0.12.5"  # the host's uv
SQLPARSE_URL="https://github.com/andialbrecht/sqlparse"
SQLPARSE_COMMIT="f66d12c245412f28c58f045b646eb53c0e691b8b"  # base_commit and fix_commit of every mutation task
REPO="$RUNTIME/bug-mining/repos/sqlparse"
NICE="nice -n 19"

FAILURES=()
NOTES=()
say() { printf '[setup] %s\n' "$*"; }
fail() { FAILURES+=("$*"); say "FAIL: $*"; }
note() { NOTES+=("$*"); say "NOTE: $*"; }

mkdir -p "$RUNTIME" "$RUNTIME/locks" "$RUNTIME/bug-mining/repos"
cd "$ROOT" || exit 1

# ---- 1. uv ---------------------------------------------------------------------------------------------------
UV=""
if command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
elif [ -x "$RUNTIME/uv-bootstrap/bin/uv" ]; then
  UV="$RUNTIME/uv-bootstrap/bin/uv"
else
  say "installing uv into $RUNTIME/uv-bootstrap"
  if python3 -m venv "$RUNTIME/uv-bootstrap" >/dev/null 2>&1; then
    $NICE "$RUNTIME/uv-bootstrap/bin/pip" install -q "uv==$UV_VERSION" >/dev/null 2>&1 \
      || $NICE "$RUNTIME/uv-bootstrap/bin/pip" install -q uv >/dev/null 2>&1
  fi
  [ -x "$RUNTIME/uv-bootstrap/bin/uv" ] && UV="$RUNTIME/uv-bootstrap/bin/uv"
  if [ -z "$UV" ]; then  # no venv module (e.g. a python3 without ensurepip): a user-level install
    say "venv bootstrap failed; trying python3 -m pip install --user uv"
    $NICE python3 -m pip install -q --user "uv==$UV_VERSION" >/dev/null 2>&1 \
      || $NICE python3 -m pip install -q --user --break-system-packages "uv==$UV_VERSION" >/dev/null 2>&1 || true
    [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
  fi
fi
if [ -n "$UV" ]; then say "uv: $UV ($("$UV" --version 2>/dev/null))"; else note "uv unavailable; falling back to python3 -m venv"; fi

# ---- 2. the interpreter the venvs are made from -----------------------------------------------------------------
BASE_PYTHON="${RETICLE_CLOUD_PYTHON:-}"
if [ -z "$BASE_PYTHON" ] && [ -n "$UV" ]; then
  $NICE "$UV" python install "$PYTHON_VERSION" >/dev/null 2>&1 || true
  BASE_PYTHON="$("$UV" python find "$PYTHON_VERSION" 2>/dev/null || true)"
fi
if [ -z "$BASE_PYTHON" ]; then
  BASE_PYTHON="$(command -v python3)"
  note "Python $PYTHON_VERSION unavailable; using $BASE_PYTHON ($("$BASE_PYTHON" --version 2>&1)), not the host's $PYTHON_VERSION"
fi
BASE_VERSION="$("$BASE_PYTHON" -c 'import platform; print(platform.python_version())' 2>/dev/null)"
say "base interpreter: $BASE_PYTHON ($BASE_VERSION)"
[ "$BASE_VERSION" = "$PYTHON_VERSION" ] || note "task interpreter is Python $BASE_VERSION; the host's is $PYTHON_VERSION"

# ---- 3-4. venvs ------------------------------------------------------------------------------------------------
make_venv() {  # make_venv NAME REQUIREMENTS
  local venv="$RUNTIME/$1" requirements="$2" have=""
  if [ -x "$venv/bin/python" ]; then
    have="$("$venv/bin/python" -c 'import platform; print(platform.python_version())' 2>/dev/null)"
    if [ "$have" != "$BASE_VERSION" ]; then
      say "$1: Python $have != $BASE_VERSION; recreating"
      rm -rf "$venv"
    fi
  fi
  if [ ! -x "$venv/bin/python" ]; then
    say "$1: creating with $BASE_PYTHON"
    if [ -n "$UV" ]; then
      "$UV" venv -q --python "$BASE_PYTHON" "$venv" || { fail "$1: uv venv failed"; return; }
    else
      "$BASE_PYTHON" -m venv "$venv" || { fail "$1: python -m venv failed"; return; }
    fi
  fi
  say "$1: installing $(grep -cv '^#' "$requirements") pinned packages"
  if [ -n "$UV" ]; then
    $NICE "$UV" pip install -q --python "$venv/bin/python" -r "$requirements" || fail "$1: uv pip install failed"
  else
    $NICE "$venv/bin/python" -m pip install -q -r "$requirements" || fail "$1: pip install failed"
  fi
}
make_venv bugs-venv "$HERE/bugs-venv.requirements.txt"
make_venv test-venv "$HERE/test-venv.requirements.txt"

# ---- 5. the sqlparse clone -------------------------------------------------------------------------------------
if [ ! -d "$REPO/.git" ]; then
  say "cloning $SQLPARSE_URL into $REPO"
  git clone -q "$SQLPARSE_URL" "$REPO" || fail "sqlparse clone failed"
fi
if [ -d "$REPO/.git" ] && ! git -C "$REPO" cat-file -e "$SQLPARSE_COMMIT^{commit}" 2>/dev/null; then
  git -C "$REPO" fetch -q origin '+refs/heads/*:refs/remotes/origin/*' || true
fi

# ---- 6. readiness ----------------------------------------------------------------------------------------------
say "---- readiness"
TASK_PY="$RUNTIME/bugs-venv/bin/python"
TEST_PY="$RUNTIME/test-venv/bin/python"
if [ -x "$TASK_PY" ] && "$TASK_PY" -c 'import pytest, freezegun, hypothesis' 2>/dev/null; then
  say "task interpreter: $TASK_PY ($("$TASK_PY" -c 'import platform, pytest; print(platform.python_version(), "pytest", pytest.__version__)'))"
else
  fail "task interpreter $TASK_PY cannot import pytest, freezegun and hypothesis"
fi
if [ -x "$TASK_PY" ] && (cd /tmp && "$TASK_PY" -c 'import sqlparse' 2>/dev/null); then
  fail "the task interpreter imports sqlparse outside a workspace (a healthy copy is installed)"
fi
if [ -x "$TEST_PY" ] && "$TEST_PY" -c 'import reticle, yaml, numpy, PIL' 2>/dev/null; then
  say "test interpreter: $TEST_PY ($("$TEST_PY" -c 'import platform; print(platform.python_version())'))"
else
  fail "test interpreter $TEST_PY cannot import reticle, yaml, numpy and PIL from $ROOT"
fi
if [ -x "$TEST_PY" ] && ! "$TEST_PY" -c 'import cv2' 2>/dev/null; then
  note "cv2 (opencv-python) does not import: $("$TEST_PY" -c 'import cv2' 2>&1 | tail -1); only image tests need it"
fi
RESOLVED="$("$TEST_PY" -c 'import sys; sys.path.insert(0, "experiments/p6_pilot"); from interpreters import task_python; print(task_python(sys.argv[1]))' "$ROOT" 2>/dev/null)"
if [ "$RESOLVED" = "$TASK_PY" ]; then say "run_pilot.TASK_PYTHON resolves to $RESOLVED"; else fail "TASK_PYTHON resolves to '$RESOLVED', not $TASK_PY"; fi
if git -C "$REPO" cat-file -e "$SQLPARSE_COMMIT^{commit}" 2>/dev/null; then
  say "sqlparse clone: $REPO has $SQLPARSE_COMMIT"
else
  fail "sqlparse clone at $REPO lacks $SQLPARSE_COMMIT"
fi
if command -v claude >/dev/null 2>&1; then
  say "claude CLI: $(claude --version 2>/dev/null) (cards 019/020 pin 2.1.284 (Claude Code))"
else
  fail "claude CLI not on PATH"
fi
if command -v podman >/dev/null 2>&1 || (command -v docker >/dev/null 2>&1 && docker version >/dev/null 2>&1); then
  note "a container engine answers; OCI cards could run here"
else
  say "container engine: none running (trusted-local cards only)"
fi
say "host: $(uname -srm); $(nproc) CPUs; $(free -g 2>/dev/null | awk '/^Mem:/ {print $2 " GiB RAM"}'); python3 $(python3 --version 2>&1)"
say "git: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD) at $(git -C "$ROOT" rev-parse --short HEAD)"
for item in ${NOTES[@]+"${NOTES[@]}"}; do say "note: $item"; done
if [ "${#FAILURES[@]}" -eq 0 ]; then
  echo "READY"
  exit 0
fi
for item in ${FAILURES[@]+"${FAILURES[@]}"}; do say "failure: $item"; done
echo "NOT READY"
exit 1
