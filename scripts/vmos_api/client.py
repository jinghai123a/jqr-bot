"""VMOS Cloud API client — endpoint methods."""
from __future__ import annotations

import time
from typing import Any

from .signer import VmosSigner
from .transport import VmosTransport


def _normalize_list(data: object) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _normalize_dict(data: object) -> dict[str, Any]:
    return data if isinstance(data, dict) else {}


class VmosApiClient:
    HOST = VmosSigner.HOST
    BASE = VmosTransport.BASE
    SERVICE = VmosSigner.SERVICE
    ALGORITHM = VmosSigner.ALGORITHM
    CONTENT_TYPE = VmosSigner.CONTENT_TYPE

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        timeout: int = 60,
        *,
        proxy: str | None = None,
    ) -> None:
        self.access_key = access_key.strip()
        self.secret_key = secret_key.strip()
        self.timeout = timeout
        self.proxy = proxy
        signer = VmosSigner(self.access_key, self.secret_key)
        self._transport = VmosTransport(signer, timeout=timeout, proxy=proxy)

    def post(self, path: str, payload: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any]:
        return self._transport.post(path, payload, retries=retries)

    def list_pads(self, page: int = 1, rows: int = 50) -> list[dict[str, Any]]:
        resp = self.post("/vcpcloud/api/padApi/infos", {"page": page, "rows": rows})
        data = resp.get("data") or {}
        items = data.get("pageData") or data.get("list") or [] if isinstance(data, dict) else []
        return _normalize_list(items)

    def model_info(self, pad_codes: list[str]) -> list[dict[str, Any]]:
        if not pad_codes:
            return []
        resp = self.post("/vcpcloud/api/padApi/modelInfo", {"padCodes": pad_codes})
        return _normalize_list(resp.get("data"))

    def open_adb(self, pad_codes: list[str]) -> list[dict[str, Any]]:
        resp = self.post(
            "/vcpcloud/api/padApi/openOnlineAdb",
            {"padCodes": pad_codes, "openStatus": 1},
        )
        return _normalize_list(resp.get("data") or [])

    def pad_task_detail(self, task_ids: list[int]) -> list[dict[str, Any]]:
        if not task_ids:
            return []
        resp = self.post("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": task_ids})
        return _normalize_list(resp.get("data") or [])

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
        return _normalize_dict(resp.get("data") or {})

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
