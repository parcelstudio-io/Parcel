#!/usr/bin/env python
"""Entry point alias for ``scorer_bridge`` (H-CV1c).

The card names the module ``scorer_bridge.py``; the executor brief names the
entry point ``bridge.py --transcripts <path>``.  Both are the same code.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scorer_bridge import main

if __name__ == "__main__":
    raise SystemExit(main())
