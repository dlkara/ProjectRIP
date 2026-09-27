from __future__ import annotations

import argparse
from pathlib import Path

from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Autopsy local web app")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mode", choices=("live", "demo"))
    parser.add_argument("--database", type=Path, help="SQLite 파일 경로 (기본값: data/autopsy.sqlite3)")
    args = parser.parse_args()
    serve(port=args.port, mode=args.mode, database=args.database)


if __name__ == "__main__":
    main()
