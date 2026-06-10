#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app" / "GridAgentCore"
sys.path.insert(0, str(APP_ROOT))

from grid_agent_core.colqwen2 import main


if __name__ == "__main__":
    main()
