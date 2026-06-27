"""Unit tests for bot_ops package."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from bot_ops.checks import (
    adb_online,
    adb_port_online,
    env_map,
    in_group_chat,
    recent_log_matches,
)
from bot_ops.config import load_vps_config
from bot_ops.report import CheckResult, emit_json, exit_code


class EnvMapTests(unittest.TestCase):
    def test_parses_key_value(self) -> None:
        raw = "# comment\nBOT_LISTENER_PURE_PIPE=1\nFOO=bar\n"
        self.assertEqual(env_map(raw)["BOT_LISTENER_PURE_PIPE"], "1")


class AdbOnlineTests(unittest.TestCase):
    def test_device_state(self) -> None:
        def run(cmd, t):
            return "device\n"

        self.assertTrue(adb_online("127.0.0.1:60478", run))

    def test_offline(self) -> None:
        def run(cmd, t):
            return "offline\n"

        self.assertFalse(adb_online("127.0.0.1:60478", run))


class InGroupChatTests(unittest.TestCase):
    def test_group_chat_activity(self) -> None:
        def run(cmd, t):
            return "mCurrentFocus=GroupChatActivity"

        self.assertTrue(in_group_chat("localhost:56121", run, left=False))

    def test_left_gallery_branch(self) -> None:
        def run(cmd, t):
            return "mCurrentFocus=Gallery"

        self.assertTrue(in_group_chat("localhost:56121", run, left=True))


class RecentLogMatchesTests(unittest.TestCase):
    def test_respects_time_cutoff(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(minutes=30)
        ts = old.strftime("%Y-%m-%d %H:%M:%S")
        log = f"[{ts}] pipe+b64+send ok\n"
        matches = recent_log_matches(log, r"pipe\+b64\+send", minutes=15)
        self.assertEqual(len(matches), 0)

    def test_finds_recent(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        log = f"[{now}] pipe+b64+send ok\n"
        matches = recent_log_matches(log, r"pipe\+b64\+send", minutes=15)
        self.assertEqual(len(matches), 1)


class AdbPortOnlineTests(unittest.TestCase):
    def test_port_device_line(self) -> None:
        adb = "List of devices\n127.0.0.1:60478 device product\n"
        self.assertTrue(adb_port_online(adb, "60478"))


class ReportTests(unittest.TestCase):
    def test_emit_json_structure(self) -> None:
        checks = [
            CheckResult("a", True, "ok"),
            CheckResult("b", False, "no"),
        ]
        data = emit_json(checks)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["passed"], 1)
        self.assertFalse(data["ok"])
        self.assertEqual(len(data["checks"]), 2)

    def test_exit_code(self) -> None:
        self.assertEqual(exit_code([CheckResult("x", True, "")]), 0)
        self.assertEqual(exit_code([CheckResult("x", False, "")]), 1)


class LoadVpsConfigTests(unittest.TestCase):
    def test_missing_host_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            with mock.patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(RuntimeError) as ctx:
                    load_vps_config(root)
                self.assertIn("VPS_HOST", str(ctx.exception))

    def test_loads_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg_dir = root / "config"
            cfg_dir.mkdir()
            (cfg_dir / "vps-ssh.env").write_text(
                "VPS_HOST=1.2.3.4\nVPS_PASSWORD=secret\nBOT_ROOT=/tmp/bot\n",
                encoding="utf-8",
            )
            cfg = load_vps_config(root)
            self.assertEqual(cfg.host, "1.2.3.4")
            self.assertEqual(cfg.password, "secret")
            self.assertEqual(cfg.bot_root, "/tmp/bot")


if __name__ == "__main__":
    unittest.main()
