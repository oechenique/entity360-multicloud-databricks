"""OpenSanctions (colección default, targets.simple.csv) filtrado a lo que puede cruzarse con el universo.

Se lee en streaming (441 MB, sin escribir a disco) y se quedan las entidades que no son personas
(Company, Organization, LegalEntity, PublicBody) y cumplen alguna de estas:
- país AR: se cruzan por nombre normalizado con el universo GLEIF AR (spike 11c);
- un LEI en `identifiers`: se cruzan por LEI con cualquier entidad del universo, incluido el
  conjunto de control no argentino (matrices extranjeras).
Medido el 2026-09-25: 36 AR + ~2.560 con LEI. Las personas quedan afuera: el universo son empresas.

`last_seen` se descarta: cambia en cada export aunque la entidad no cambie, y rompería la capa 1 de
idempotencia (D6). `last_change` sí se conserva.

Licencia CC BY-NC 4.0 (uso no comercial, atribución obligatoria): va en cada manifest.
"""

import csv
import io
import re

import requests

INDEX = "https://data.opensanctions.org/datasets/latest/default/index.json"
NO_PERSONAS = {"Company", "Organization", "LegalEntity", "PublicBody"}
LEI = re.compile(r"\b[0-9A-Z]{18}[0-9]{2}\b")
# Campos multivalor separados por ";". `sanctions` y `addresses` quedan como texto crudo: su
# contenido libre también usa ";" y partirlo lo desordenaría (Silver los interpreta).
LISTAS = ["aliases", "countries", "identifiers", "phones", "emails", "program_ids", "dataset"]
ATRIBUCION = {"licencia": "CC BY-NC 4.0",
              "atribucion": "Datos: OpenSanctions (opensanctions.org), CC BY-NC 4.0"}


def extraer(ua: str) -> tuple[list[dict], dict]:
    s = requests.Session()
    s.headers["User-Agent"] = ua
    meta = s.get(INDEX, timeout=60).json()
    rec = next(r for r in meta["resources"] if r["name"] == "targets.simple.csv")
    csv.field_size_limit(2**31 - 1)
    filas, leidas = [], 0
    with s.get(rec["url"], stream=True, timeout=300) as r:
        r.raise_for_status()
        r.raw.decode_content = True
        for f in csv.DictReader(io.TextIOWrapper(r.raw, encoding="utf-8", newline="")):
            leidas += 1
            if f["schema"] not in NO_PERSONAS:
                continue
            paises = set(f["countries"].split(";")) if f["countries"] else set()
            leis = sorted(set(LEI.findall(f["identifiers"] or "")))
            if "ar" not in paises and not leis:
                continue
            fila = {k: v or None for k, v in f.items() if k not in LISTAS and k != "last_seen"}
            fila.update({k: [x for x in (f[k] or "").split(";") if x] for k in LISTAS})
            fila["leis"] = leis
            filas.append(fila)
    filas.sort(key=lambda x: x["id"])
    extra = {"version_fuente": meta["version"], "filas_leidas_fuente": leidas,
             "filtro": "schema no persona y (país AR o LEI en identifiers)", **ATRIBUCION}
    return filas, extra
