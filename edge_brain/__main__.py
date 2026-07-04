"""python -m edge_brain"""
from __future__ import annotations

import uvicorn

from edge_brain.config import HOST, PORT


def main() -> None:
    uvicorn.run(
        "edge_brain.app:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
