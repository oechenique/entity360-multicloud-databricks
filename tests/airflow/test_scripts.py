"""levantar.ps1 y apagar.ps1: parsean en PowerShell y apagar no depende de las credenciales."""

import shutil
import subprocess
from pathlib import Path

import pytest

AIRFLOW = Path(__file__).resolve().parents[2] / "airflow"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


@pytest.mark.skipif(not POWERSHELL, reason="sin PowerShell")
@pytest.mark.parametrize("script", ["levantar.ps1", "apagar.ps1"])
def test_parsea(script):
    cmd = ("$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("
           f"'{AIRFLOW / script}', [ref]$null, [ref]$e) | Out-Null; $e.Count")
    r = subprocess.run([POWERSHELL, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "0", r.stdout + r.stderr


def test_apagar_va_por_proyecto_y_no_borra():
    texto = (AIRFLOW / "apagar.ps1").read_text(encoding="utf-8")
    codigo = "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("#"))
    assert "entity360-airflow" in codigo and "stop" in codigo
    # Sin el archivo de compose (exige credenciales) y sin down/rm/-v (borrarían la base de Airflow).
    for prohibido in ("docker-compose.yml", " down", " rm", " -v", "credenciales.py"):
        assert prohibido not in codigo, prohibido
