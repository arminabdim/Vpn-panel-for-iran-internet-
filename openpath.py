#!/usr/bin/env python3
"""
OpenPath - free internet for Iran, without a server and without paying.

Run this file directly from Termux (no install needed):

    pkg install python git -y
    python openpath.py

Everything OpenPath needs is in the standard library.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openpath.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
