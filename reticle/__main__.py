"""Entrypoint for `python -m reticle`."""

from __future__ import annotations

import sys
from reticle.cli import main

if __name__ == "__main__":
    sys.exit(main())
