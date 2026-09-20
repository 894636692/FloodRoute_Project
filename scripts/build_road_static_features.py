from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from floodroute.gis.static_features import build

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the formal A -> B GIS interface")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build(args.root, args.config or args.root / "config/gis_static.json", args.output)
