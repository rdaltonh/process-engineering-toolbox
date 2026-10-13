import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPAN_DIR = ROOT / "apps" / "piping_structural" / "span_chart"
sys.path.insert(0, str(SPAN_DIR))
