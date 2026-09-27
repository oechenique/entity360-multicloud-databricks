"""Capa 2 de idempotencia (D6): qué hace Bronze con cada archivo de un micro-batch.

Python puro: Bronze lo llama dentro del foreachBatch y los tests, locales.

Por archivo:
- sin manifest todavía -> excepción: el micro-batch falla, el checkpoint no avanza y el reintento
  del job lo vuelve a entregar (paso 0, punto 3). El productor sube el manifest después de los datos.
- sha256 del contenido distinto del manifest, o cantidad de líneas distinta de `registros` -> error:
  no se ingiere y queda en ops.ingestion_log para revisar a mano.
- sin veredicto del contrato de llegada (contracts/verificar.py, regla 09), o con un veredicto de otro
  contenido (otro sha256) -> excepción, igual que sin manifest: el lote no entra sin verificar
  (ADR 0006). Airflow corre los contratos antes de disparar el job.
- veredicto en `cuarentena` -> cuarentena_contrato: no se ingiere; el veredicto dice qué check crítico
  falló.
- sha256 ya ingerido desde otro archivo (o repetido dentro del mismo lote) -> duplicado: no se ingiere.
- si no -> ingerido_bronze.
"""


class ManifestPendiente(RuntimeError):
    pass


class ContratoPendiente(RuntimeError):
    pass


def manifest_de(ruta_datos: str) -> str:
    """<carpeta>/<fuente>_<ts>.jsonl -> <carpeta>/_manifest_<ts>.json (regla 01)."""
    carpeta, archivo = ruta_datos.rsplit("/", 1)
    ts = archivo.rsplit(".", 1)[0].rsplit("_", 1)[1]
    return f"{carpeta}/_manifest_{ts}.json"


def contrato_de(ruta_datos: str) -> str:
    """<carpeta>/<fuente>_<ts>.jsonl -> <carpeta>/_contrato_<ts>.json (veredicto del contrato de llegada)."""
    return manifest_de(ruta_datos).replace("/_manifest_", "/_contrato_")


def clasificar(archivos: list[dict], manifests: dict[str, dict | None], ingeridos: dict[str, str],
               contratos: dict[str, dict | None]) -> list[dict]:
    """archivos: {ruta, sha256, lineas}; manifests: ruta de datos -> manifest (None si no está);
    ingeridos: sha256 -> ruta ya ingerida (estado ingerido_bronze en ops.ingestion_log);
    contratos: ruta de datos -> veredicto del contrato de llegada (None si no corrió)."""
    faltan = [a["ruta"] for a in archivos if manifests.get(a["ruta"]) is None]
    if faltan:
        raise ManifestPendiente(f"sin manifest todavía (se reintenta): {', '.join(sorted(faltan))}")
    sin_veredicto = [a["ruta"] for a in archivos if not contratos.get(a["ruta"])]
    otro_contenido = [a["ruta"] for a in archivos
                      if contratos.get(a["ruta"]) and contratos[a["ruta"]].get("sha256") != a["sha256"]]
    if sin_veredicto or otro_contenido:
        partes = []
        if sin_veredicto:
            partes.append(f"sin veredicto del contrato (correr contracts/verificar.py --pendientes): "
                          f"{', '.join(sorted(sin_veredicto))}")
        if otro_contenido:
            partes.append(f"veredicto de otro contenido (borrar el _contrato y re-verificar): "
                          f"{', '.join(sorted(otro_contenido))}")
        raise ContratoPendiente("; ".join(partes))
    vistos = dict(ingeridos)
    salida = []
    for a in sorted(archivos, key=lambda a: a["ruta"]):
        m = manifests[a["ruta"]]
        c = contratos[a["ruta"]]
        if c.get("estado") == "cuarentena":
            estado, motivo = "cuarentena_contrato", "contrato: " + ", ".join(c.get("fallas_criticas") or [])
        elif m.get("sha256") != a["sha256"]:
            estado, motivo = "error", "sha256 distinto del manifest"
        elif m.get("registros") is not None and m["registros"] != a["lineas"]:
            estado, motivo = "error", f"{a['lineas']} líneas y el manifest dice {m['registros']}"
        elif a["sha256"] in vistos and vistos[a["sha256"]] != a["ruta"]:
            estado, motivo = "duplicado", f"mismo sha256 que {vistos[a['sha256']].rsplit('/', 1)[1]}"
        else:
            estado, motivo = "ingerido_bronze", None
            vistos[a["sha256"]] = a["ruta"]
        salida.append({**a, "estado": estado, "motivo": motivo, "manifest": m})
    return salida
