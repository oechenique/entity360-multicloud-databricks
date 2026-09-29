"""Espacio de Genie "Entity 360" sobre Gold (fase 10, regla 12).

El provider de Terraform no tiene recurso para Genie: este script es su despliegue, idempotente.

    desplegar  crea el espacio, o lo actualiza si ya hay uno con el mismo título, desde genie/espacio.json.
               Escribe genie/serialized_space.json (lo que recibe la API) para versionarlo.
    probar     hace las preguntas de `pruebas` en conversaciones nuevas y guarda en genie/pruebas.json el
               SQL que generó Genie para cada una, con las filas que devolvió.

Uso (desde la raíz del repo):
    .venv\\Scripts\\python.exe databricks\\consumo\\genie.py desplegar
    .venv\\Scripts\\python.exe databricks\\consumo\\genie.py probar
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent / "genie"
FUENTE = AQUI / "espacio.json"
SERIALIZADO = AQUI / "serialized_space.json"
PRUEBAS = AQUI / "pruebas.json"
GOLD_YML = RAIZ / "dbt" / "models" / "gold" / "gold.yml"
PERFIL = "entity360-free"
WAREHOUSE = "Serverless Starter Warehouse"
CARPETA = "/Workspace/Shared/entity360"


def _id(*partes: str) -> str:
    """Id de 32 hex en minúscula, estable: el mismo texto da el mismo id en cada despliegue."""
    return hashlib.md5("\x1f".join(partes).encode("utf-8")).hexdigest()


def descripciones_dbt() -> dict[str, dict]:
    modelos = yaml.safe_load(GOLD_YML.read_text(encoding="utf-8"))["models"]
    return {f"entity360.gold.{m['name']}": {"tabla": " ".join(m.get("description", "").split()),
                                            "columnas": {c["name"]: c.get("description", "")
                                                         for c in m.get("columns", [])}}
            for m in modelos}


def serializar(e: dict) -> dict:
    dbt = descripciones_dbt()
    tablas = []
    for t in sorted(e["tablas"]):
        extra = e["columnas"].get(t, {})
        cols = []
        for c in sorted(set(dbt[t]["columnas"]) | set(extra)):
            cfg = {"column_name": c}
            if dbt[t]["columnas"].get(c):
                cfg["description"] = [dbt[t]["columnas"][c]]
            x = extra.get(c, {})
            if x.get("sinonimos"):
                cfg["synonyms"] = x["sinonimos"]
            if x.get("entity_matching"):
                cfg["enable_entity_matching"] = True
            if x.get("format_assistance"):
                cfg["enable_format_assistance"] = True
            cols.append(cfg)
        tablas.append({"identifier": t, "description": [dbt[t]["tabla"]], "column_configs": cols})
    joins = []
    for tabla, col, card in e["joins"]:
        izq, der = tabla.split(".")[-1], "dim_entity"
        joins.append({"id": _id("join", tabla, col),
                      "left": {"identifier": tabla, "alias": izq},
                      "right": {"identifier": "entity360.gold.dim_entity", "alias": der},
                      "sql": [f"`{izq}`.`{col}` = `{der}`.`{col}`", f"--rt=FROM_RELATIONSHIP_TYPE_{card}--"],
                      "comment": [f"Cada fila de {izq} pertenece a una empresa del golden record."]})
    return {
        "version": 2,
        "config": {"sample_questions": sorted(({"id": _id("muestra", q), "question": [q]}
                                               for q in e["preguntas_de_ejemplo"]), key=lambda x: x["id"])},
        "data_sources": {"tables": tablas},
        "instructions": {
            "text_instructions": [{"id": _id("instrucciones"), "content": [l + "\n" for l in e["instrucciones"]]}],
            "example_question_sqls": sorted(({"id": _id("sql", x["pregunta"]), "question": [x["pregunta"]],
                                              "sql": [x["sql"]], "usage_guidance": [x["uso"]]}
                                             for x in e["ejemplos_sql"]), key=lambda x: x["id"]),
            "join_specs": sorted(joins, key=lambda x: x["id"]),
        },
    }


def cliente():
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(profile=PERFIL)
    wh = next(x.id for x in w.warehouses.list() if x.name == WAREHOUSE)
    return w, wh


def buscar(w, titulo: str) -> str | None:
    token = None
    while True:
        r = w.genie.list_spaces(page_token=token)
        for s in r.spaces or []:
            if s.title == titulo:
                return s.space_id
        token = r.next_page_token
        if not token:
            return None


def desplegar() -> int:
    e = json.loads(FUENTE.read_text(encoding="utf-8"))
    espacio = serializar(e)
    SERIALIZADO.write_text(json.dumps(espacio, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    w, wh = cliente()
    existente = buscar(w, e["titulo"])
    texto = json.dumps(espacio, ensure_ascii=False)
    if existente:
        w.genie.update_space(existente, serialized_space=texto, title=e["titulo"], description=e["descripcion"],
                             warehouse_id=wh)
        print(f"espacio actualizado: {e['titulo']}")
    else:
        w.genie.create_space(wh, texto, title=e["titulo"], description=e["descripcion"], parent_path=CARPETA)
        print(f"espacio creado: {e['titulo']}")
    return 0


def probar() -> int:
    e = json.loads(FUENTE.read_text(encoding="utf-8"))
    w, _ = cliente()
    sid = buscar(w, e["titulo"])
    if not sid:
        print("no hay espacio: correr `desplegar` primero")
        return 1
    salida = []
    for pregunta in e["pruebas"]:
        from datetime import timedelta
        from databricks.sdk.errors import OperationFailed
        op = w.genie.start_conversation(sid, pregunta)
        try:
            m = op.result(timeout=timedelta(minutes=10))
        except OperationFailed:
            m = w.genie.get_message(sid, op.response.conversation_id, op.response.message_id)
        prueba = {"pregunta": pregunta, "estado": m.status.value if m.status else None, "texto": None,
                  "sql": None, "descripcion_sql": None, "columnas": None, "filas": None, "total_filas": None,
                  "error": m.error.as_dict() if m.error else None}
        for a in m.attachments or []:
            if a.text and a.text.content:
                prueba["texto"] = a.text.content
            if a.query:
                prueba["sql"], prueba["descripcion_sql"] = a.query.query, a.query.description
                r = w.genie.get_message_attachment_query_result(sid, m.conversation_id, m.message_id,
                                                                a.attachment_id).statement_response
                if r and r.manifest:
                    prueba["columnas"] = [c.name for c in r.manifest.schema.columns]
                    prueba["total_filas"] = r.manifest.total_row_count
                    prueba["filas"] = (r.result.data_array or [])[:20] if r.result else []
        salida.append(prueba)
        print(f"- {pregunta}\n  {prueba['estado']}, {prueba['total_filas']} filas")
    PRUEBAS.write_text(json.dumps({"probado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   "pruebas": salida}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["desplegar", "probar"])
    sys.exit({"desplegar": desplegar, "probar": probar}[ap.parse_args().accion]())
