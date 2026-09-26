# Container de enriquecimiento (regla 07): OpenSanctions + Wikidata -> UC Volume.
# Contexto de build: producers/ (toma el universo de emisores SEC del productor de la fase 3, sin copiarlo).
#   docker build -f producers/container_enrichment/Dockerfile -t entity360-enrichment producers
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY container_enrichment/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aws_sec_edgar/universo.json universo_sec.json
COPY container_enrichment/landing.py container_enrichment/opensanctions.py container_enrichment/wikidata.py container_enrichment/main.py ./

# Sin root: no necesita escribir nada (OpenSanctions se filtra en streaming).
USER nobody
ENTRYPOINT ["python", "main.py"]
