"""Structured check results and output helpers."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def emit_text(checks: list[CheckResult]) -> str:
    lines: list[str] = []
    for c in checks:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"[{mark}] {c.name}: {c.detail}")
    return "\n".join(lines)


def emit_json(checks: list[CheckResult]) -> dict:
    fails = [c for c in checks if not c.passed]
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "passed": len(checks) - len(fails),
        "total": len(checks),
        "ok": len(fails) == 0,
        "checks": [asdict(c) for c in checks],
    }


def exit_code(checks: list[CheckResult]) -> int:
    return 0 if all(c.passed for c in checks) else 1
