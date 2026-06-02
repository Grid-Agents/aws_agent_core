from __future__ import annotations

import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2] / "app" / "GridAgentCore"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
