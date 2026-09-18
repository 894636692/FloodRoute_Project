"""Resolve project imports and the optional pure-Python dependency wheel on D:."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
wheel_dir = Path(os.environ.get(
    "FLOODROUTE_WHEELS", str(ROOT.parent / "software" / "python-wheels")
))
for wheel in sorted(wheel_dir.glob("networkx-*.whl")):
    sys.path.insert(0, str(wheel))
