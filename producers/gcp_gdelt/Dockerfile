# Productor GDELT (regla 06, ADR 0003): BigQuery sandbox -> respaldo en BigQuery -> UC Volume.
# Contexto de build: producers/ (reutiliza el cliente del volume del container de enriquecimiento).
#   docker build -f producers/gcp_gdelt/Dockerfile -t entity360-gdelt producers
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY gcp_gdelt/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY container_enrichment/landing.py gcp_gdelt/extractor.py gcp_gdelt/alias.json ./

# Sin root. En Actions se corre con --user del runner para leer el archivo de credenciales de WIF.
USER nobody
ENTRYPOINT ["python", "extractor.py"]
