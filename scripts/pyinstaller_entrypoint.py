"""PyInstaller entrypoint for the writer CLI binary."""

from __future__ import annotations

import sys
import traceback


def main() -> None:
    from writer.cli.main import app

    app()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

