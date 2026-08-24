from __future__ import annotations

import hashlib
import json
from multiprocessing import get_context
import os
from pathlib import Path
import statistics
import tempfile
import time
from typing import Any

from work_assistant.broker import BrokerClient, run_broker


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(len(ordered) * fraction) - 1))]


def _case(
    root: Path,
    label: str,
    mode: str,
    iterations: int,
    body_kib: int,
    sender_rule: tuple[str, str] | None = None,
) -> dict[str, Any]:
    case = root / label
    case.mkdir()
    body = ("Synthetic update for alex@example.test at +39 02 1234 5678. " * 32)
    body = (body * ((body_kib * 1024 // len(body)) + 1))[: body_kib * 1024]
    source = case / "mail.jsonl"
    source.write_text(
        json.dumps(
            {
                "id": "m-1",
                "sender": "alex@example.test",
                "recipients": ["team@example.test"],
                "sent_at": "2026-08-24T10:00:00Z",
                "subject": "Synthetic benchmark",
                "body_text": body,
                "folder": "inbox",
            }
        )
        + "\n"
    )
    config = case / "work-assistant.toml"
    data_dir = case / "data"
    lines = [
        "schema_version = 1",
        f'data_dir = "{data_dir.as_posix()}"',
        "[privacy]",
        f'mode = "{mode}"',
        'default_action = "pseudonymize"',
    ]
    if sender_rule:
        lines.extend(
            [
                "[[privacy.sender_rules]]",
                f'pattern = "{sender_rule[0]}"',
                f'action = "{sender_rule[1]}"',
            ]
        )
    lines.extend(
        [
            "[accounts.personal]",
            'provider = "demo"',
            'address = "owner@example.test"',
            f'source = "{source.as_posix()}"',
        ]
    )
    config.write_text("\n".join(lines) + "\n")
    address = (
        rf"\\.\pipe\work-assistant-benchmark-{os.getpid()}-{label}"
        if os.name == "nt"
        else str(Path(tempfile.gettempdir()) / f"wa-{os.getpid()}-{hashlib.sha256(str(case).encode()).hexdigest()[:12]}.sock")
    )
    auth = case / "broker.auth"
    process = get_context("spawn").Process(
        target=run_broker,
        args=(str(config), address, str(auth)),
        daemon=True,
    )
    process.start()
    client = BrokerClient(address, auth, timeout=2)
    deadline = time.monotonic() + 8
    while True:
        try:
            client.call("privacy_status")
            break
        except Exception:
            if time.monotonic() >= deadline:
                process.terminate()
                process.join(2)
                raise RuntimeError(f"benchmark broker failed to start for {label}")
            time.sleep(0.05)
    client.call("sync", account="personal")
    samples: list[float] = []
    try:
        for _ in range(iterations):
            started = time.perf_counter_ns()
            client.call("get", account="personal", message_id="m-1")
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
    finally:
        process.terminate()
        process.join(3)
        if process.is_alive():
            process.kill()
            process.join(1)
    return {
        "label": label,
        "mode": mode,
        "iterations": iterations,
        "body_kib": body_kib,
        "median_ms": round(statistics.median(samples), 4),
        "p95_ms": round(_percentile(samples, 0.95), 4),
        "max_ms": round(max(samples), 4),
    }


def benchmark_privacy(iterations: int = 200, body_kib: int = 16, budget_ms: float = 25) -> dict[str, Any]:
    iterations = max(10, iterations)
    body_kib = max(1, body_kib)
    with tempfile.TemporaryDirectory(prefix="work-assistant-benchmark-") as directory:
        root = Path(directory)
        cases = [
            _case(root, "off", "off", iterations, body_kib),
            _case(root, "all", "all", iterations, body_kib),
            _case(
                root,
                "selective_allow_raw",
                "selective",
                iterations,
                body_kib,
                ("alex@example.test", "allow_raw"),
            ),
            _case(root, "selective_pseudonymize", "selective", iterations, body_kib),
        ]
    by_label = {item["label"]: item for item in cases}
    overhead = max(0.0, by_label["all"]["p95_ms"] - by_label["off"]["p95_ms"])
    if overhead <= budget_ms:
        recommendation = "all_mode_is_within_the_selected_local_overhead_budget"
    else:
        recommendation = "consider_selective_mode_or_a_larger_budget_after_review"
    return {
        "schema_version": 1,
        "scope": "synthetic local broker round-trip only; excludes provider, model and network latency",
        "cases": cases,
        "all_vs_off_p95_overhead_ms": round(overhead, 4),
        "selected_overhead_budget_ms": budget_ms,
        "recommendation": recommendation,
        "decision_warning": "performance is only one factor; allow_raw changes privacy exposure",
    }
