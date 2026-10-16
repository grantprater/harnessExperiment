#!/usr/bin/env bash
# Can a child process be denied the network (and the checkout) on this Linux VM, without root, and can the harness's
# trusted-local command runner use it? Card 022's cloud-first prerequisite (design section 8; owner's Q3 amendment).
#
#   bash experiments/cloud/probe_isolation.sh [--no-harness]
#
# Read-only apart from a scratch directory under ${TMPDIR:-/tmp}; no model call, no campaign, no install. Each check
# prints PASS, FAIL or INFO; the last line is one of
#   ISOLATION: NETWORK+FILES   unshare denies the network and can hide the checkout and home (tmpfs over them) while a
#                              workspace stays visible, and the harness runner's commands get the same
#   ISOLATION: NETWORK ONLY    the network is denied, but directories cannot be hidden
#   ISOLATION: NONE            no way found to deny the network to a child process (the fallback is the host OCI
#                              backend)
# and the exit code is 0, 1 or 2 accordingly. A baseline without isolation must reach the network first; if it cannot,
# every "denied" result is vacuous and the script says so (ISOLATION: NONE, exit 2).
#
# Checks: 1 baseline network; 2 which isolation tools and kernel settings exist (unshare, user-namespace sysctls,
# bwrap, firejail, passwordless sudo, uid); 3 unshare -rn (or -n as root): HTTPS, raw socket and DNS from Python must
# all fail, and only the loopback interface may exist; 4 unshare -rnm: a tmpfs over a stand-in checkout and home hides
# their files while a workspace bind-mounted beforehand stays readable and writable; 5 the harness:
# reticle.execution.TrustedLocalBackend runs the same Python fetch once plainly (must succeed) and once prefixed with
# the unshare command (must fail), which is how a wrapped run tool would call it.

set -uo pipefail
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS=1
[ "${1:-}" = "--no-harness" ] && HARNESS=0
PY="$(command -v python3 || command -v python || true)"
for candidate in "$ROOT/.runtime/test-venv/bin/python" "$ROOT/.runtime/bugs-venv/bin/python"; do
  [ -x "$candidate" ] && PY="$candidate" && break
done
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/probe-isolation.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
PASSES=0; FAILS=0
pass() { PASSES=$((PASSES + 1)); printf 'PASS %s\n' "$*"; }
fail() { FAILS=$((FAILS + 1)); printf 'FAIL %s\n' "$*"; }
info() { printf 'INFO %s\n' "$*"; }

FETCH='import socket, sys, urllib.request
results = {}
for name, action in (("https", lambda: urllib.request.urlopen("https://example.com", timeout=5).read(1)),
                     ("socket", lambda: socket.create_connection(("1.1.1.1", 443), timeout=5).close()),
                     ("dns", lambda: socket.getaddrinfo("example.com", 443))):
    try:
        action(); results[name] = "reached"
    except Exception as exc:
        results[name] = "blocked:" + type(exc).__name__
print(" ".join(f"{k}={v}" for k, v in results.items()))
sys.exit(0 if all(v == "reached" for v in results.values()) else 3 if all(v != "reached" for v in results.values()) else 4)'

if [ -z "$PY" ]; then
  info "no python3 on PATH; the Python checks cannot run"
  echo "ISOLATION: NONE"; exit 2
fi
info "python $("$PY" -c 'import sys; print(sys.version.split()[0])') at $PY; uid $(id -u); kernel $(uname -r)"

# 1. Baseline: without isolation the network must be reachable, or the checks below prove nothing.
baseline="$("$PY" -c "$FETCH" 2>&1)"; code=$?
if [ $code -eq 0 ]; then pass "1 baseline reaches the network ($baseline)"
else fail "1 baseline cannot reach the network ($baseline); denial results below are vacuous"; fi
BASELINE_OK=$([ $code -eq 0 ] && echo 1 || echo 0)

# 2. What exists.
info "2 unshare: $(command -v unshare || echo missing) $(unshare --version 2>/dev/null | head -1)"
for sysctl in /proc/sys/kernel/unprivileged_userns_clone /proc/sys/user/max_user_namespaces \
              /proc/sys/kernel/apparmor_restrict_unprivileged_userns; do
  [ -r "$sysctl" ] && info "2 $sysctl = $(cat "$sysctl")"
done
info "2 bwrap: $(command -v bwrap || echo missing); firejail: $(command -v firejail || echo missing); ip: $(command -v ip || echo missing)"
if sudo -n true 2>/dev/null; then info "2 passwordless sudo: yes"; else info "2 passwordless sudo: no"; fi

# 3. Network namespace for a child process.
UNSHARE=""
for flags in "-rn" "-n"; do
  if unshare $flags true 2>"$SCRATCH/unshare.err"; then UNSHARE="unshare $flags"; break; fi
  info "3 unshare $flags true failed: $(head -c 200 "$SCRATCH/unshare.err")"
done
NETWORK_DENIED=0
if [ -n "$UNSHARE" ]; then
  denied="$($UNSHARE "$PY" -c "$FETCH" 2>&1)"; code=$?
  if [ $code -eq 3 ]; then pass "3 $UNSHARE: every fetch blocked ($denied)"; NETWORK_DENIED=1
  else fail "3 $UNSHARE: not every fetch blocked (exit $code: $denied)"; fi
  links="$($UNSHARE "$PY" -c 'import socket; print(" ".join(sorted(n for _, n in socket.if_nameindex())))' 2>&1)"
  if [ "$links" = "lo" ]; then pass "3 only the loopback interface inside ($links)"
  else info "3 interfaces inside: $links"; fi
else
  fail "3 unshare cannot create a network namespace here"
fi

# 4. Mount namespace: hide a stand-in checkout and home, keep a workspace.
FILES_HIDDEN=0
if [ -n "$UNSHARE" ]; then
  mkdir -p "$SCRATCH/checkout/runs/ws" "$SCRATCH/home/harness-sealed" "$SCRATCH/view"
  echo secret > "$SCRATCH/checkout/tasks.json"; echo sealed > "$SCRATCH/home/harness-sealed/resolutions.json"
  echo data > "$SCRATCH/checkout/runs/ws/data.csv"
  script='set -e
mount --bind "$1/checkout/runs/ws" "$1/view"
mount -t tmpfs tmpfs "$1/checkout"
mount -t tmpfs tmpfs "$1/home"
test ! -e "$1/checkout/tasks.json" || { echo "checkout still visible"; exit 5; }
test ! -e "$1/home/harness-sealed/resolutions.json" || { echo "home still visible"; exit 5; }
cat "$1/view/data.csv" >/dev/null || { echo "workspace lost"; exit 6; }
echo written > "$1/view/out.txt" || { echo "workspace not writable"; exit 6; }
echo ok'
  hidden="$(${UNSHARE}m sh -c "$script" sh "$SCRATCH" 2>&1)"; code=$?
  if [ $code -eq 0 ] && [ -f "$SCRATCH/checkout/runs/ws/out.txt" ]; then
    pass "4 ${UNSHARE}m hides the checkout and home, keeps the workspace readable and writable"; FILES_HIDDEN=1
  else
    fail "4 ${UNSHARE}m cannot hide directories (exit $code: $(echo "$hidden" | tail -2 | tr '\n' ' '))"
  fi
fi

# 5. The harness's trusted-local runner with the wrapper.
if [ $HARNESS -eq 1 ] && [ -n "$UNSHARE" ]; then
  harness="$(cd "$ROOT" && "$PY" - "$UNSHARE" "$PY" "$FETCH" <<'PYEOF' 2>&1
import importlib.util, sys
# The runner module by path: it is standard library only, while the reticle package imports optional extras.
spec = importlib.util.spec_from_file_location("backends", "reticle/execution/backends.py")
backends = importlib.util.module_from_spec(spec)
sys.modules["backends"] = backends
spec.loader.exec_module(backends)
ExecutionRequest, TrustedLocalBackend = backends.ExecutionRequest, backends.TrustedLocalBackend
wrapper, python, fetch = sys.argv[1].split(), sys.argv[2], sys.argv[3]
backend = TrustedLocalBackend()
for label, command in (("plain", [python, "-c", fetch]), ("wrapped", [*wrapper, python, "-c", fetch])):
    result = backend.run(ExecutionRequest(command=command, working_directory=".", timeout_seconds=60))
    print(label, result.status, result.exit_code, result.stdout.decode().strip())
PYEOF
)"
  info "5 $(echo "$harness" | tr '\n' ';')"
  plain_ok=$(echo "$harness" | grep -c '^plain success 0 ')
  wrapped_blocked=$(echo "$harness" | grep -c '^wrapped error 3 ')
  if [ "$wrapped_blocked" = 1 ] && { [ "$plain_ok" = 1 ] || [ "$BASELINE_OK" = 0 ]; }; then
    pass "5 TrustedLocalBackend: plain command reaches the network, the same command under '$UNSHARE' is blocked"
  else
    fail "5 TrustedLocalBackend with '$UNSHARE' did not give plain=reached, wrapped=blocked"
    NETWORK_DENIED=0
  fi
fi

printf 'SUMMARY %d passed, %d failed\n' "$PASSES" "$FAILS"
if [ "$BASELINE_OK" = 1 ] && [ $NETWORK_DENIED = 1 ] && [ $FILES_HIDDEN = 1 ]; then echo "ISOLATION: NETWORK+FILES"; exit 0; fi
if [ "$BASELINE_OK" = 1 ] && [ $NETWORK_DENIED = 1 ]; then echo "ISOLATION: NETWORK ONLY"; exit 1; fi
echo "ISOLATION: NONE"; exit 2
