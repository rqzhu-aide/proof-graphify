"""Verify the installed runtime.

Generate bundles with tools/build_paper_core_bundles.py in the proof-graphify repository.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from paper_core.bundle import verify_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    core = Path(__file__).resolve().parent / "paper_core"
    if not args.check:
        parser.error("generated bundles cannot be re-manifested locally; run "
                     "python -B tools/build_paper_core_bundles.py from the proof-graphify repository")
    result = verify_bundle(core)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
