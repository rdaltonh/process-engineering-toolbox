import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPAN_DIR = ROOT / "apps" / "piping_structural" / "span_chart"
HOSE_DIR = ROOT / "apps" / "fluid_analysis_design" / "corrugated_hose_dp"
sys.path.insert(0, str(SPAN_DIR))
sys.path.insert(0, str(HOSE_DIR))
