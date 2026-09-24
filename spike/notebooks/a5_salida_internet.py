# Databricks notebook source
# Spike A.5: ¿qué hosts alcanza el compute serverless de Free Edition?
# Prueba solo conectividad (GET/HEAD chico, timeout corto). Devuelve un JSON con el resultado.

import json
import socket
import time
from urllib.parse import urlparse

import requests

# SEC exige User-Agent con nombre y mail (regla 02, punto 9).
UA = "entity360-spike (portfolio) gastonechenique@gmail.com"

DESTINOS = [
    ("GLEIF API", "https://api.gleif.org/api/v1/lei-records?page[size]=1"),
    ("GLEIF golden copy", "https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest"),
    ("SEC EDGAR", "https://data.sec.gov/submissions/CIK0000320193.json"),
    ("OpenSanctions", "https://data.opensanctions.org/datasets/latest/index.json"),
    ("Wikidata SPARQL", "https://query.wikidata.org/sparql?query=ASK%7B%7D&format=json"),
    ("GDELT", "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"),
    ("PyPI", "https://pypi.org/simple/requests/"),
    ("GitHub", "https://api.github.com/zen"),
    ("AWS S3 (us-east-2)", "https://s3.us-east-2.amazonaws.com/"),
    ("Google", "https://www.google.com/generate_204"),
    # Hosts poco comunes: distinguen allowlist de salida libre.
    ("example.com", "https://example.com/"),
    ("httpbin", "https://httpbin.org/get"),
    ("ifconfig.me (IP de salida)", "https://ifconfig.me/ip"),
]

resultados = []
for nombre, url in DESTINOS:
    host = urlparse(url).hostname
    fila = {"destino": nombre, "host": host}
    try:
        fila["dns"] = socket.gethostbyname(host)
    except Exception as e:  # noqa: BLE001
        fila["dns"] = f"FALLA {type(e).__name__}"
    t0 = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10, stream=True)
        fila["http"] = r.status_code
        if "ifconfig.me" in url and r.ok:
            fila["ip_salida"] = r.text.strip()[:45]
        r.close()
    except Exception as e:  # noqa: BLE001
        fila["http"] = f"FALLA {type(e).__name__}: {str(e)[:160]}"
    fila["seg"] = round(time.time() - t0, 2)
    resultados.append(fila)
    print(fila)

# COMMAND ----------

dbutils.notebook.exit(json.dumps(resultados))
