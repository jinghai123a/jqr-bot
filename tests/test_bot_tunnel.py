"""Unit tests for bot_tunnel package."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot_tunnel.adb_probe import adb_probe_port
from bot_tunnel.env_io import load_env_file, shell_env_line, write_tunnel_env
from bot_tunnel.pad_resolve import resolve_pad_code
from bot_tunnel.refresh import fetch_adb_with_backoff
from bot_tunnel.ssh_parse import parse_ssh_command


class ShellEnvLineTests(unittest.TestCase):
    def test_quotes_vmos_ssh_command_with_spaces(self) -> None:
        cmd = 'ssh -o StrictHostKeyChecking=no -p 1824 user@1.2.3.4 -L 60478:adb:5555'
        line = shell_env_line("VMOS_SSH_COMMAND", cmd)
        self.assertTrue(line.startswith('VMOS_SSH_COMMAND="'))
        self.assertIn("60478", line)

    def test_plain_port_unquoted(self) -> None:
        self.assertEqual(shell_env_line("LOCAL_PORT", "60478"), "LOCAL_PORT=60478")


class ParseSshCommandTests(unittest.TestCase):
    def test_standard_vmos_command(self) -> None:
        cmd = "ssh -o StrictHostKeyChecking=no -p 1824 s@129.227.134.130 -L 60478:adb:5555"
        host, port, user = parse_ssh_command(cmd)
        self.assertEqual(host, "129.227.134.130")
        self.assertEqual(port, "1824")
        self.assertEqual(user, "s")


class WriteTunnelEnvTests(unittest.TestCase):
    def test_round_trip_load_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tunnel-right.env"
            ssh_cmd = "ssh -p 1824 s@129.1.1.1 -L 60478:adb:5555"
            adb_cmd = "adb connect localhost:60478"
            write_tunnel_env(
                path,
                "60478",
                "129.1.1.1",
                "1824",
                "s",
                "secret-pass",
                ssh_command=ssh_cmd,
                adb_command=adb_cmd,
                expire_time="2026-01-01",
            )
            env = load_env_file(path)
            self.assertEqual(env["LOCAL_PORT"], "60478")
            self.assertEqual(env["VMOS_SSH_COMMAND"], ssh_cmd)
            self.assertEqual(env["VMOS_ADB_COMMAND"], adb_cmd)
            self.assertEqual(env["SSH_HOST"], "129.1.1.1")
            self.assertEqual(env["SSH_PASS"], "secret-pass")
            self.assertEqual(env["EXPIRE_TIME"], "2026-01-01")


class AdbProbePortTests(unittest.TestCase):
    def test_probe_success_127(self) -> None:
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

        self.assertTrue(adb_probe_port("60478", run_subprocess=fake_run))

    def test_probe_failure(self) -> None:
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="fail")

        self.assertFalse(adb_probe_port("60478", run_subprocess=fake_run))


class FetchAdbWithBackoffTests(unittest.TestCase):
    def test_retries_after_503_then_succeeds(self) -> None:
        client = mock.Mock()
        client.get_adb.side_effect = [
            RuntimeError("503 Service Unavailable"),
            {"command": "ssh -p 1824 u@1.1.1.1 -L 1:adb:5555", "key": "k", "adb": ""},
        ]
        sleeps: list[float] = []

        result = fetch_adb_with_backoff(
            client,
            "PAD1",
            open_adb_first=False,
            attempts=3,
            sleep_fn=lambda s: sleeps.append(s),
        )
        self.assertEqual(result["key"], "k")
        self.assertEqual(client.get_adb.call_count, 2)
        self.assertEqual(len(sleeps), 1)


class ResolvePadCodeTests(unittest.TestCase):
    def test_explicit_pad_code_wins(self) -> None:
        code = resolve_pad_code(
            "right",
            {"pad_code": "EXPLICIT"},
            [{"padCode": "OTHER"}],
            {},
        )
        self.assertEqual(code, "EXPLICIT")

    def test_tie_score_raises(self) -> None:
        pads = [
            {"padCode": "A", "padIp": "1.2.3.4"},
            {"padCode": "B", "padIp": "1.2.3.5"},
        ]
        models = {
            "A": {"romVersion": "12"},
            "B": {"romVersion": "12"},
        }
        cfg = {"match_android": 12}
        with self.assertRaises(RuntimeError) as ctx:
            resolve_pad_code("left", cfg, pads, models)
        self.assertIn("同分", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
