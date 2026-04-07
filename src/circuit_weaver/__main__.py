"""Circuit Weaver CLI entrypoint."""

from __future__ import annotations

import sys

from . import __version__
from .dispatcher import main as mvp_main


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        print(__version__)
        return
    mvp_main()


if __name__ == "__main__":
    main()
