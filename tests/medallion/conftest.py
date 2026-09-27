"""Tests del medallion (fase 6): la lógica en Python puro de databricks/medallion, sin Spark."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "databricks" / "medallion"))
