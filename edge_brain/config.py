"""Edge Brain — VPS 数据中台（FastAPI）。"""
from __future__ import annotations

import os

HOST = os.environ.get("EDGE_BRAIN_HOST", "0.0.0.0")
PORT = int(os.environ.get("EDGE_BRAIN_PORT", "8790") or 8790)
JWT_SECRET = os.environ.get("EDGE_BRAIN_JWT_SECRET", "").strip()
