#!/usr/bin/env python3
"""VMOS Cloud API client (HMAC-SHA256 signing)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


class VmosApiClient:
    HOST = "api.vmoscloud.com"
    BASE = f"https://{HOST}"
    SERVICE = "armcloud-paas"
    ALGORITHM = "HMAC-SHA256"
    CONTENT_TYPE = "application/json;charset=UTF-8"

    def __init__(self, access_key: str, secret_key: str, timeout: int = 60) -> None:
        self.access_key = access_key.strip()
        self.secret_key = secret_key.strip()
        self.timeout = timeout

    @staticmethod
    def _sha256_hex(data: str) -> str:
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def _sign(self, body: str, x_date: str) -> str:
        signed_headers = "content-type;host;x-content-sha256;x-date"
        canonical = (
            f"host:{self.HOST}\n"
            f"x-date:{x_date}\n"
            f"content-type:{self.CONTENT_TYPE}\n"
            f"signedHeaders:{signed_headers}\n"
            f"x-content-sha256:{self._sha256_hex(body)}"
        )
        short_date = x_date[:8]
        credential_scope = f"{short_date}/{self.SERVICE}/request"
        string_to_sign = "\n".join(
            (self.ALGORITHM, x_date, credential_scope, self._sha256_hex(canonical))
        )
        k_date = hmac.new(self.secret_key.encode(), short_date.encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_date, self.SERVICE.encode(), hashlib.sha256).digest()
        sign_key = hmac.new(k_service, b"request", hashlib.sha256).digest()
        return hmac.new(sign_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    def _headers(self, body: str) -> dict[str, str]:
        x_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        signature = self._sign(body, x_date)
        credential = f"{self.access_key}/{x_date[:8]}/{self.SERVICE}/request"
        authorization = (
            f"HMAC-SHA256 Credential={credential}, "
            f"SignedHeaders=content-type;host;x-content-sha256;x-date, "
            f"Signature={signature}"
        )
        return {
            "content-type": self.CONTENT_TYPE,
            "x-date": x_date,
            "x-host": self.HOST,
            "authorization": authorization,
        }

    def post(self, path: str, payload: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any]:
        body = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
        last_err: Exception | None = None
        busy_paths = ("/padApi/adb", "/padApi/openOnlineAdb", "/padApi/infos")
        max_retries = max(retries, 8 if any(p in path for p in busy_paths) else retries)
        for attempt in range(max_retries):
            req = urllib.request.Request(
                f"{self.BASE}{path}",
                data=body.encode("utf-8"),
                headers=self._headers(body),
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                last_err = RuntimeError(f"HTTP {exc.code} {path}: {raw}")
                if exc.code >= 500 and attempt + 1 < max_retries:
                    time.sleep(min(30, 3 * (attempt + 1)))
                    continue
                raise last_err from exc
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON from {path}: {raw[:500]}") from exc
            code = data.get("code")
            if code in (200, "200", 0, "0", None):
                return data
            msg = data.get("msg") or data.get("message") or ""
            last_err = RuntimeError(f"API error {path} code={code} msg={msg}")
            if str(code) in ("500", "503") or "busy" in str(msg).lower():
                if attempt + 1 < max_retries:
                    time.sleep(min(30, 3 * (attempt + 1)))
                    continue
            raise last_err
        raise last_err or RuntimeError(f"API failed: {path}")

    def list_pads(self, page: int = 1, rows: int = 50) -> list[dict[str, Any]]:
        resp = self.post("/vcpcloud/api/padApi/infos", {"page": page, "rows": rows})
        data = resp.get("data") or {}
        items = data.get("pageData") or data.get("list") or []
        if isinstance(items, dict):
            items = [items]
        return [x for x in items if isinstance(x, dict)]

    def model_info(self, pad_codes: list[str]) -> list[dict[str, Any]]:
        if not pad_codes:
            return []
        resp = self.post("/vcpcloud/api/padApi/modelInfo", {"padCodes": pad_codes})
        data = resp.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    def open_adb(self, pad_codes: list[str]) -> list[dict[str, Any]]:
        resp = self.post(
            "/vcpcloud/api/padApi/openOnlineAdb",
            {"padCodes": pad_codes, "openStatus": 1},
        )
        data = resp.get("data") or []
        if isinstance(data, dict):
            data = [data]
        return [x for x in data if isinstance(x, dict)]

    def pad_task_detail(self, task_ids: list[int]) -> list[dict[str, Any]]:
        if not task_ids:
            return []
        resp = self.post("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": task_ids})
        data = resp.get("data") or []
        if isinstance(data, dict):
            data = [data]
        return [x for x in data if isinstance(x, dict)]

    def wait_open_adb_tasks(
        self,
        tasks: list[dict[str, Any]],
        *,
        timeout: float = 180,
        poll_interval: float = 3,
    ) -> None:
        """openOnlineAdb 为异步任务，文档要求 taskStatus=3 后再 get adb。"""
        pending: dict[int, str] = {}
        for item in tasks:
            tid = item.get("taskId")
            if tid is None:
                continue
            status = int(item.get("taskStatus") or 0)
            pad = str(item.get("padCode") or "")
            if status == 3:
                continue
            if status < 0:
                raise RuntimeError(f"openOnlineAdb failed pad={pad} task={tid} status={status}")
            pending[int(tid)] = pad
        if not pending:
            return
        deadline = time.time() + timeout
        while pending and time.time() < deadline:
            details = self.pad_task_detail(list(pending.keys()))
            for item in details:
                tid = int(item.get("taskId") or 0)
                if tid not in pending:
                    continue
                status = int(item.get("taskStatus") or 0)
                if status == 3:
                    pending.pop(tid, None)
                elif status < 0:
                    raise RuntimeError(
                        f"openOnlineAdb task {tid} pad={pending.get(tid)} failed: {item.get('errorMsg') or item}"
                    )
            if pending:
                time.sleep(poll_interval)
        if pending:
            raise RuntimeError(f"openOnlineAdb timeout tasks={list(pending.keys())} pads={list(pending.values())}")

    def get_adb(
        self,
        pad_code: str,
        enable: bool = True,
        *,
        expire_minutes: int = 10080,
        retries: int = 5,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "padCode": pad_code,
            "enable": enable,
            "expireMinutes": max(1440, min(10080, int(expire_minutes))),
        }
        resp = self.post("/vcpcloud/api/padApi/adb", payload, retries=retries)
        data = resp.get("data") or {}
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected adb response for {pad_code}")
        return data

    def pad_info(self, pad_code: str) -> dict[str, Any]:
        resp = self.post("/vcpcloud/api/padApi/padInfo", {"padCode": pad_code}, retries=3)
        data = resp.get("data") or {}
        return data if isinstance(data, dict) else {}

    def start_app(self, pad_codes: list[str], pkg_name: str) -> None:
        self.post(
            "/vcpcloud/api/padApi/startApp",
            {"padCodes": pad_codes, "pkgName": pkg_name},
        )

    def set_keep_alive_app(self, pad_codes: list[str], pkg_name: str) -> None:
        self.post(
            "/vcpcloud/api/padApi/setKeepAliveApp",
            {
                "padCodes": pad_codes,
                "applyAllInstances": False,
                "appInfos": [{"serverName": f"{pkg_name}/{pkg_name}.MainActivity"}],
            },
        )

    def async_cmd(self, pad_codes: list[str], script: str) -> list[dict[str, Any]]:
        resp = self.post(
            "/vcpcloud/api/padApi/asyncCmd",
            {"padCodes": pad_codes, "scriptContent": script},
            retries=3,
        )
        data = resp.get("data") or []
        return data if isinstance(data, list) else [data]
