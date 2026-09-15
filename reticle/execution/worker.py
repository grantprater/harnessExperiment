"""Out-of-process ordinary-module entry-point worker."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import traceback


def _write_result(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--entry-point", required=True)
    parser.add_argument("--arguments", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    result_path = Path(args.result)
    try:
        arguments = json.loads(args.arguments)
        if not isinstance(arguments, dict):
            raise TypeError("program arguments must be a JSON object")
        source = Path(args.source).resolve()
        spec = importlib.util.spec_from_file_location("reticle_generated_program", source)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not create module spec for {source}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        entry_point = getattr(module, args.entry_point, None)
        if not callable(entry_point):
            raise TypeError(f"entry point is not callable: {args.entry_point}")
        inspect.signature(entry_point).bind(**arguments)
        value = entry_point(**arguments)
        if inspect.isawaitable(value):
            value = asyncio.run(value)
        json.dumps(value)
        _write_result(result_path, {"status": "success", "value": value})
        return 0
    except BaseException as exc:
        _write_result(
            result_path,
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
