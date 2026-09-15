# Execution backend guarantees

`TrustedLocalBackend` provides process supervision, not host isolation. On Windows,
the runtime starts a waiting bootstrap, assigns it to a Job Object configured with
`KILL_ON_JOB_CLOSE`, and only then releases the requested command. Timeouts,
cancellation, output overflow, and controller cleanup terminate the job and its
descendants. The child receives a small allowlisted environment, but it retains the
user's filesystem and network authority.

`IsolatedOCIBackend` is the first host-isolated backend. It requires a locally
available Docker or Podman engine and a pre-provisioned image. It uses one declared
workspace bind mount, no network, a read-only container root, an unprivileged user,
dropped capabilities, `no-new-privileges`, PID and memory limits, and a bounded
temporary filesystem. Read-only requests mount the workspace read-only. Mutating
requests mount only that workspace read-write; `writable_mount` overrides this for a
private copy such as an evaluation root. The image and container engine remain
trusted parts of the computing base.

Guest user: with Podman the backend uses `--userns keep-id`, so the guest runs as the
unprivileged (rootless) host user and owns bind-mounted files. The earlier fixed
`--user 65534:65534` could write but not `chmod` files on a Windows-drive mount, which made
pytest's cache setup (and `shutil.copy2`) fail inside candidate commands; this was found by
the S2b tester control on 2026-09-15. Docker keeps `--user 65534:65534` and may still deny chmod.

The supervised Docker/Podman client receives only the clean local environment plus
the host variables needed to locate its user configuration and socket. Those host
variables are not forwarded into the container; container environment entries must
be declared explicitly on the execution request.

If Docker or Podman is missing or its daemon is unavailable, isolation fails with
`BackendUnavailableError`. The runtime never substitutes trusted-local execution.
The reference P4 boundary run used Podman 5.8.3, a rootless WSL 2 machine, and the
`python:3.13-alpine` image. Engine-gated tests verify container startup before they
assert that undeclared workspace writes and outbound network connections fail, and
they run a registered program through the isolated worker.
