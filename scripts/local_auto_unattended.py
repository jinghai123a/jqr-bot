#!/usr/bin/env python3
"""无人看守 AUTO：知识库→依赖/JWT→Lint→隧道→UI 对照→local_auto_gate。"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "local-auto-unattended.json"


def _run(cmd: list[str], *, timeout: int = 600) -> tuple[int, str]:
    r = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    report: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tech_stack": {"language": "python", "jwt_lib": "PyJWT>=2.8.0"},
        "steps": [],
    }
    rc = 0

    def step(name: str, ok: bool, detail: str) -> None:
        nonlocal rc
        if not ok:
            rc = 1
        report["steps"].append({"name": name, "ok": ok, "detail": detail[:4000]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)
        if detail.strip():
            print(detail[:1200], flush=True)

    # Step 1: 55m 知识库
    c, o = _run([sys.executable, str(ROOT / "scripts" / "edge_knowledge_validate.py")], timeout=30)
    step("knowledge_validate", c == 0, o)

    # Step 2: JWT 依赖与单元测试
    c, o = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_jwt_auth.py",
            "tests/test_bot_ops_jwt.py",
            "-q",
            "--tb=line",
        ],
        timeout=120,
    )
    step("jwt_tests", c == 0, o)

    # Step 3: 语法/类型编译检查（核心 JWT 与 gate 脚本）
    compile_targets = [
        "bot_ops/auth/jwt.py",
        "edge_brain/jwt_auth.py",
        "edge_brain/app.py",
        "scripts/local_auto_gate.py",
    ]
    c, o = _run(
        [sys.executable, "-m", "py_compile", *[str(ROOT / t) for t in compile_targets]],
        timeout=30,
    )
    step("py_compile", c == 0, o or "ok")

    # Step 4: UI 页面对照（需 ADB；失败不阻断 gate，但记入报告）
    c, o = _run([sys.executable, str(ROOT / "scripts" / "compare_ui_context.py")], timeout=90)
    step("ui_context_compare", c == 0, o)

    # Step 5: 完整 V2 gate（隧道→edge→daemon→OUT 验收）
    c, o = _run([sys.executable, str(ROOT / "scripts" / "local_auto_gate.py")], timeout=600)
    step("local_auto_gate", c == 0, o)

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {ART}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
