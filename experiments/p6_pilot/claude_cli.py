"""Compatibility entry point for the packaged Claude subscription adapter."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reticle.providers import claude_cli as _adapter

if __name__ == '__main__':
    import json
    if len(sys.argv) != 3 or sys.argv[1] != '--probe-tools':
        raise SystemExit(_adapter.__doc__)
    print(json.dumps(_adapter.probe_tools(Path(sys.argv[2])), indent=2, ensure_ascii=False))
else:
    sys.modules[__name__] = _adapter
