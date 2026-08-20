#!/usr/bin/env python3
"""Compatibility shim — the canonical module lives at src/mutalambda/muta_lambda.py.

Keeps the documented UX working from a repo checkout without installation:

    python muta_lambda.py --optimize my_script.py

For library use, install the package instead:  pip install -e .
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mutalambda.muta_lambda import *  # noqa: F401,F403
from mutalambda.muta_lambda import main  # noqa: F401

if __name__ == "__main__":
    main()
