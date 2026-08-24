from __future__ import annotations

import argparse
import json

from work_assistant.benchmark import benchmark_privacy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--body-kib", type=int, default=16)
    parser.add_argument("--budget-ms", type=float, default=25)
    args = parser.parse_args()
    print(
        json.dumps(
            benchmark_privacy(args.iterations, args.body_kib, args.budget_ms),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
