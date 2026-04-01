import os
from pathlib import Path

XP_HOME = Path(os.environ.get("XP_HOME", Path.home() / ".xp"))
