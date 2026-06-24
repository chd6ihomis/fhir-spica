#!/usr/bin/env python3
"""Development entry point: `python run.py` starts the portal with uvicorn."""
from __future__ import annotations

import uvicorn

from app.config import get_config


def main() -> None:
    config = get_config()
    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
