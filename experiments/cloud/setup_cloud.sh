#!/usr/bin/env bash
# Prepare a Linux cloud VM (a Claude Code cloud session) to run the experiment pipeline. Idempotent; no sudo.
#
#   bash experiments/cloud/setup_cloud.sh
#
# 1. uv: the one on PATH, else one installed with pip into .runtime/uv-bootstrap (a python3 venv), else with
#    pip install --user.
# 2. The interpreter both venvs are made from, the first usable of: RETICLE_CLOUD_PYTHON=/path/to/python; Python
#    3.13.15 (the host venvs' interpreter) from `uv python install`; any 3.13 already on the VM (python3.13 on PATH,
#    pyenv, `uv python find 3.13`); `uv python install 3.13`, then 3.12; python3.12 on PATH; the system python3 (3.11
#    when probed). uv's output goes to .runtime/setup-python.log, and a NOTE names the choice and why each preferred
#    source was skipped: any other version is a different task interpreter from the host's and must be reported.
# 3. .runtime/bugs-venv: the task interpreter (run_pilot.TASK_PYTHON resolves .runtime/bugs-venv/bin/python on
#    Linux), exactly experiments/cloud/bugs-venv.requirements.txt (the host's pip freeze).
# 4. .runtime/test-venv: the unit-test interpreter, exactly experiments/cloud/test-venv.requirements.txt, or on a
#    Python older than 3.12 exactly test-venv.requirements-py311.txt (numpy 2.5 needs 3.12; a NOTE says so).
# 5. .runtime/bug-mining/repos/<name>: the clones run_pilot.ensure_commits expects, one per mutation-task bank
#    (TASK_REPOS below: sqlparse for tasks.mutations.json, boltons for tasks.boltons.json), each with its bank's
#    pinned commit (experiments/mutation_tasks/repos.json; tests/test_mutation_repos.py checks the two agree).
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
# name url commit (base_commit and fix_commit of every task in that repository's bank); the name is also the package
# the task interpreter must not import outside a workspace
TASK_REPOS=(
  "sqlparse https://github.com/andialbrecht/sqlparse f66d12c245412f28c58f045b646eb53c0e691b8b"
  "boltons https://github.com/mahmoud/boltons 45a251181fba4c5a4ecc05e838da1c394e1ed0e4"
)
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
# First usable of: RETICLE_CLOUD_PYTHON; uv's CPython 3.13.15; any 3.13 already here (python3.13 on PATH, pyenv, uv
# python find); uv's newest 3.13, then 3.12; python3.12 on PATH; the system python3. uv's output goes to $PY_LOG.
PY_LOG="$RUNTIME/setup-python.log"
: > "$PY_LOG"
BASE_PYTHON=""
BASE_SOURCE=""
SKIPPED=()  # why each preferred source was not used
py_version() { "$1" -c 'import platform; print(platform.python_version())' 2>/dev/null; }
log_tail() { tail -n "${1:-4}" "$PY_LOG" | tr -s '\n' '|' | sed 's/|$//'; }
try_python() {  # try_python SOURCE WANT PATH: adopt PATH when it runs and its version is WANT (3.x.y) or 3.x.*
  local source="$1" want="$2" candidate="$3" have
  [ -n "$BASE_PYTHON" ] && return 0
  if [ -z "$candidate" ]; then SKIPPED+=("$source: none found"); return 1; fi
  have="$(py_version "$candidate")"
  case "$have" in
    "$want"|"$want".*) BASE_PYTHON="$candidate"; BASE_SOURCE="$source"; return 0 ;;
  esac
  SKIPPED+=("$source: $candidate reports '${have:-no version}', not $want")
  return 1
}
uv_find() { "$UV" python find --system "$1" 2>>"$PY_LOG"; }
uv_install() {  # uv_install REQUEST: uv python install REQUEST (logged), then the interpreter it provides
  [ -n "$BASE_PYTHON" ] && return 0
  if [ -z "$UV" ]; then SKIPPED+=("uv python install $1: no uv"); return 1; fi
  printf -- '---- %s python install %s\n' "$UV" "$1" >> "$PY_LOG"
  if ! $NICE "$UV" python install "$1" >>"$PY_LOG" 2>&1; then
    SKIPPED+=("uv python install $1 failed: $(log_tail 3)")
    [ "$1" = "$PYTHON_VERSION" ] && note "uv python install $PYTHON_VERSION failed; last lines of $PY_LOG: $(log_tail 6)"
    return 1
  fi
  try_python "uv python install $1" "$1" "$(uv_find "$1")"
}
pyenv_python() {  # pyenv_python MINOR: the newest pyenv-installed CPython MINOR.*
  local root=""
  if command -v pyenv >/dev/null 2>&1; then root="$(pyenv root 2>/dev/null)"; fi
  [ -n "$root" ] || root="${PYENV_ROOT:-$HOME/.pyenv}"
  [ -d "$root/versions" ] || return 0
  ls -d "$root/versions/$1".* 2>/dev/null | grep -E "/$1\.[0-9]+$" | sort -V | tail -n 1 | sed "s|\$|/bin/python$1|"
}

if [ -n "${RETICLE_CLOUD_PYTHON:-}" ]; then
  if [ -x "$RETICLE_CLOUD_PYTHON" ] && [ -n "$(py_version "$RETICLE_CLOUD_PYTHON")" ]; then
    BASE_PYTHON="$RETICLE_CLOUD_PYTHON"; BASE_SOURCE="RETICLE_CLOUD_PYTHON"
  else
    fail "RETICLE_CLOUD_PYTHON=$RETICLE_CLOUD_PYTHON does not run; discovering an interpreter instead"
  fi
fi
uv_install "$PYTHON_VERSION"
try_python "python3.13 on PATH" 3.13 "$(command -v python3.13 2>/dev/null)"
try_python "pyenv" 3.13 "$(pyenv_python 3.13)"
[ -n "$UV" ] && try_python "uv python find 3.13" 3.13 "$(uv_find 3.13)"
uv_install 3.13
uv_install 3.12
try_python "python3.12 on PATH" 3.12 "$(command -v python3.12 2>/dev/null)"
try_python "system python3" 3 "$(command -v python3 2>/dev/null)"
if [ -z "$BASE_PYTHON" ]; then
  fail "no Python interpreter found (see $PY_LOG)"
  echo "NOT READY"
  exit 1
fi
BASE_VERSION="$(py_version "$BASE_PYTHON")"
say "base interpreter: $BASE_PYTHON ($BASE_VERSION), from $BASE_SOURCE"
if [ "$BASE_VERSION" != "$PYTHON_VERSION" ]; then
  if [ "$BASE_SOURCE" = "RETICLE_CLOUD_PYTHON" ]; then
    note "base interpreter is RETICLE_CLOUD_PYTHON ($BASE_VERSION), not the host's $PYTHON_VERSION"
  else
    note "Python $PYTHON_VERSION unavailable; chose $BASE_PYTHON ($BASE_VERSION) from $BASE_SOURCE. Skipped: $(IFS=";"; echo "${SKIPPED[*]+${SKIPPED[*]}}")"
  fi
  note "task interpreter is Python $BASE_VERSION; the host's is $PYTHON_VERSION"
fi
TEST_REQUIREMENTS="$HERE/test-venv.requirements.txt"
if ! "$BASE_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
  TEST_REQUIREMENTS="$HERE/test-venv.requirements-py311.txt"
  note "Python $BASE_VERSION < 3.12: test-venv uses $(basename "$TEST_REQUIREMENTS") (numpy 2.4.6, not the host's 2.5.3)"
fi

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
make_venv test-venv "$TEST_REQUIREMENTS"

# ---- 5. the task repositories' clones --------------------------------------------------------------------------
for entry in "${TASK_REPOS[@]}"; do
  read -r name url commit <<< "$entry"
  repo="$RUNTIME/bug-mining/repos/$name"
  if [ ! -d "$repo/.git" ]; then
    say "cloning $url into $repo"
    git clone -q "$url" "$repo" || fail "$name clone failed"
  fi
  if [ -d "$repo/.git" ] && ! git -C "$repo" cat-file -e "$commit^{commit}" 2>/dev/null; then
    git -C "$repo" fetch -q origin '+refs/heads/*:refs/remotes/origin/*' || true
  fi
done

# ---- 6. readiness ----------------------------------------------------------------------------------------------
say "---- readiness"
TASK_PY="$RUNTIME/bugs-venv/bin/python"
TEST_PY="$RUNTIME/test-venv/bin/python"
if [ -x "$TASK_PY" ] && "$TASK_PY" -c 'import pytest, freezegun, hypothesis' 2>/dev/null; then
  say "task interpreter: $TASK_PY ($("$TASK_PY" -c 'import platform, pytest; print(platform.python_version(), "pytest", pytest.__version__)'))"
else
  fail "task interpreter $TASK_PY cannot import pytest, freezegun and hypothesis"
fi
for entry in "${TASK_REPOS[@]}"; do
  read -r name url commit <<< "$entry"
  if [ -x "$TASK_PY" ] && (cd /tmp && "$TASK_PY" -c "import $name" 2>/dev/null); then
    fail "the task interpreter imports $name outside a workspace (a healthy copy is installed)"
  fi
done
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
for entry in "${TASK_REPOS[@]}"; do
  read -r name url commit <<< "$entry"
  repo="$RUNTIME/bug-mining/repos/$name"
  if git -C "$repo" cat-file -e "$commit^{commit}" 2>/dev/null; then
    say "$name clone: $repo has $commit"
  else
    fail "$name clone at $repo lacks $commit"
  fi
done
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
