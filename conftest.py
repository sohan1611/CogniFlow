"""Ensure the project root is importable for tests regardless of invocation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
