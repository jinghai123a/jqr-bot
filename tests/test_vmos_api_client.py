"""Unit tests for VMOS API client (mock HTTP, no live VMOS calls)."""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from vmos_api.signer import VmosSigner  # noqa: E402
from vmos_api.transport import VmosTransport  # noqa: E402
from vmos_api_client import VmosApiClient  # noqa: E402


class _MockResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _MockResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class SignerTests(unittest.TestCase):
    def test_sign_deterministic(self) -> None:
        signer = VmosSigner("test_access_key", "test_secret_key")
        body = "{}"
        x_date = "20240101T120000Z"
        sig = signer.sign(body, x_date)
        self.assertEqual(len(sig), 64)
        self.assertEqual(sig, signer.sign(body, x_date))

    def test_headers_format(self) -> None:
        signer = VmosSigner("my_ak", "my_sk")
        body = '{"page":1,"rows":50}'
        x_date = "20240615T083045Z"
        headers = signer.headers(body, x_date=x_date)
        self.assertEqual(headers["content-type"], VmosSigner.CONTENT_TYPE)
        self.assertEqual(headers["x-date"], x_date)
        self.assertEqual(headers["x-host"], VmosSigner.HOST)
        self.assertIn("HMAC-SHA256 Credential=my_ak/20240615/armcloud-paas/request", headers["authorization"])
        self.assertIn("Signature=", headers["authorization"])

    def test_sha256_hex(self) -> None:
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        self.assertEqual(VmosSigner.sha256_hex(""), expected)


class TransportPostTests(unittest.TestCase):
    def _client_with_mock(self, responses: list[str | Exception]) -> tuple[VmosApiClient, list[float]]:
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        call_index = {"i": 0}

        def fake_urlopen(req: object, timeout: int = 60) -> _MockResponse:
            idx = call_index["i"]
            call_index["i"] += 1
            item = responses[idx]
            if isinstance(item, Exception):
                raise item
            return _MockResponse(item)

        client = VmosApiClient("ak", "sk", timeout=5)
        signer = VmosSigner("ak", "sk")
        client._transport = VmosTransport(
            signer,
            timeout=5,
            urlopen=fake_urlopen,
            sleep_fn=fake_sleep,
        )
        return client, sleeps

    def test_post_success(self) -> None:
        payload = json.dumps({"code": 200, "data": {"ok": True}})
        client, _ = self._client_with_mock([payload])
        result = client.post("/vcpcloud/api/padApi/test", {"a": 1})
        self.assertEqual(result["code"], 200)
        self.assertEqual(result["data"]["ok"], True)

    def test_post_invalid_json_raises_runtime_error(self) -> None:
        client, _ = self._client_with_mock(["not-json"])
        with self.assertRaises(RuntimeError) as ctx:
            client.post("/vcpcloud/api/padApi/test")
        self.assertIn("Invalid JSON", str(ctx.exception))

    def test_post_non_retry_error_raises_immediately(self) -> None:
        payload = json.dumps({"code": 400, "msg": "bad request"})
        client, sleeps = self._client_with_mock([payload])
        with self.assertRaises(RuntimeError) as ctx:
            client.post("/vcpcloud/api/padApi/test", retries=3)
        self.assertIn("code=400", str(ctx.exception))
        self.assertEqual(sleeps, [])

    def test_post_retries_on_busy_response(self) -> None:
        busy = json.dumps({"code": 503, "msg": "server busy"})
        ok = json.dumps({"code": 200, "data": {}})
        client, sleeps = self._client_with_mock([busy, ok])
        result = client.post("/vcpcloud/api/padApi/infos", retries=3)
        self.assertEqual(result["code"], 200)
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(sleeps[0], 3)

    def test_post_retries_on_http_503(self) -> None:
        import urllib.error

        ok = json.dumps({"code": 200, "data": {}})
        err = urllib.error.HTTPError(
            url="https://api.vmoscloud.com/vcpcloud/api/padApi/adb",
            code=503,
            msg="Service Unavailable",
            hdrs=mock.Mock(),
            fp=io.BytesIO(b'{"code":503}'),
        )
        client, sleeps = self._client_with_mock([err, ok])
        result = client.post("/vcpcloud/api/padApi/adb", retries=3)
        self.assertEqual(result["code"], 200)
        self.assertEqual(len(sleeps), 1)

    def test_busy_path_expands_max_retries_to_eight(self) -> None:
        busy = json.dumps({"code": 503, "msg": "busy"})
        client, sleeps = self._client_with_mock([busy] * 8)
        with self.assertRaises(RuntimeError):
            client.post("/vcpcloud/api/padApi/adb", retries=3)
        self.assertEqual(len(sleeps), 7)


class ListPadsTests(unittest.TestCase):
    def test_list_pads_page_data(self) -> None:
        client = VmosApiClient("ak", "sk")
        with mock.patch.object(client, "post") as mock_post:
            mock_post.return_value = {
                "code": 200,
                "data": {"pageData": [{"padCode": "A"}, {"padCode": "B"}]},
            }
            pads = client.list_pads()
        self.assertEqual(len(pads), 2)
        self.assertEqual(pads[0]["padCode"], "A")

    def test_list_pads_list_key(self) -> None:
        client = VmosApiClient("ak", "sk")
        with mock.patch.object(client, "post") as mock_post:
            mock_post.return_value = {
                "code": 200,
                "data": {"list": [{"padCode": "X"}]},
            }
            pads = client.list_pads()
        self.assertEqual(len(pads), 1)
        self.assertEqual(pads[0]["padCode"], "X")

    def test_list_pads_single_dict_item(self) -> None:
        client = VmosApiClient("ak", "sk")
        with mock.patch.object(client, "post") as mock_post:
            mock_post.return_value = {
                "code": 200,
                "data": {"pageData": {"padCode": "SOLO"}},
            }
            pads = client.list_pads()
        self.assertEqual(len(pads), 1)
        self.assertEqual(pads[0]["padCode"], "SOLO")


class WaitOpenAdbTasksTests(unittest.TestCase):
    def test_wait_until_task_complete(self) -> None:
        client = VmosApiClient("ak", "sk")
        with mock.patch.object(client, "pad_task_detail") as mock_detail:
            mock_detail.side_effect = [
                [{"taskId": 99, "taskStatus": 1}],
                [{"taskId": 99, "taskStatus": 3}],
            ]
            with mock.patch("vmos_api.client.time.sleep"):
                client.wait_open_adb_tasks(
                    [{"taskId": 99, "taskStatus": 1, "padCode": "PAD1"}],
                    timeout=30,
                    poll_interval=0.01,
                )
        self.assertEqual(mock_detail.call_count, 2)

    def test_wait_already_complete_noop(self) -> None:
        client = VmosApiClient("ak", "sk")
        with mock.patch.object(client, "pad_task_detail") as mock_detail:
            client.wait_open_adb_tasks([{"taskId": 1, "taskStatus": 3, "padCode": "P"}])
        mock_detail.assert_not_called()

    def test_wait_timeout_raises(self) -> None:
        client = VmosApiClient("ak", "sk")
        with mock.patch.object(client, "pad_task_detail") as mock_detail:
            mock_detail.return_value = [{"taskId": 7, "taskStatus": 1}]
            with mock.patch("vmos_api.client.time.sleep"):
                with self.assertRaises(RuntimeError) as ctx:
                    client.wait_open_adb_tasks(
                        [{"taskId": 7, "taskStatus": 1, "padCode": "P7"}],
                        timeout=0.05,
                        poll_interval=0.01,
                    )
        self.assertIn("timeout", str(ctx.exception).lower())


class CompatibilityTests(unittest.TestCase):
    def test_import_from_shim(self) -> None:
        self.assertTrue(hasattr(VmosApiClient, "list_pads"))
        self.assertTrue(hasattr(VmosApiClient, "get_adb"))
        self.assertEqual(VmosApiClient.HOST, "api.vmoscloud.com")


if __name__ == "__main__":
    unittest.main()
