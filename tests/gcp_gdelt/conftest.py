"""Tests del productor GDELT (fase 4). El extractor importa `landing` del container de
enriquecimiento, igual que en la imagen (producers/gcp_gdelt/Dockerfile)."""

import os
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ / "producers" / "gcp_gdelt"), str(RAIZ / "producers" / "container_enrichment")]


@pytest.fixture(scope="session")
def bq():
    """Cliente de BigQuery con el ADC del usuario, o skip. Proyecto: GOOGLE_CLOUD_PROJECT o
    infra/gcp/terraform.tfvars (fuera de git). Nunca se imprime (principio 9)."""
    proyecto = os.environ.get("GOOGLE_CLOUD_PROJECT")
    tfvars = RAIZ / "infra" / "gcp" / "terraform.tfvars"
    if not proyecto and tfvars.exists():
        m = re.search(r'project_id\s*=\s*"(.+)"', tfvars.read_text(encoding="utf-8"))
        proyecto = m.group(1) if m else None
    if not proyecto:
        pytest.skip("sin proyecto de GCP (GOOGLE_CLOUD_PROJECT o infra/gcp/terraform.tfvars)")
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    from google.cloud import bigquery
    try:
        google.auth.default()
    except DefaultCredentialsError:
        pytest.skip("sin ADC (gcloud auth application-default login)")
    return bigquery.Client(project=proyecto, location="US")
