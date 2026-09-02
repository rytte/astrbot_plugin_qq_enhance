from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_PARENT = Path(__file__).resolve().parents[2]
ASTRBOT_ROOT = PLUGIN_PARENT / "AstrBot"
for path in (str(PLUGIN_PARENT), str(ASTRBOT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
