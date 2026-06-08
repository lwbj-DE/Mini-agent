#!/usr/bin/env python3
"""Development server entry point.

Usage:
    python run.py              # default: http://0.0.0.0:8000
    python run.py --port 3000  # custom port
    python run.py --reload     # auto-reload on code changes (dev mode)
"""

import argparse
import os
import sys

# Ensure the project root is on sys.path so that "backend.xxx" imports work.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mini Agent dev server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
