"""Corre integridad.sql en el warehouse serverless y falla si alguna restricción no se cumple.

Uso (desde la raíz del repo, después de la tarea `resolucion`):
    .venv\\Scripts\\python.exe databricks\\resolucion\\integridad.py
"""

import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI / "validacion"))
from generar_parte_a import PERFIL, WAREHOUSE, consultar  # noqa: E402


def main() -> int:
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(profile=PERFIL)
    wh = next(x.id for x in w.warehouses.list() if x.name == WAREHOUSE)
    texto = "\n".join(l for l in (AQUI / "integridad.sql").read_text(encoding="utf-8").splitlines()
                      if not l.lstrip().startswith("--"))
    fallas = 0
    for sql in (s.strip() for s in texto.split(";")):
        if sql:
            fila = consultar(w, wh, sql)[0]
            fallas += int(fila["falla"]) != 0
            print(f"{'OK   ' if int(fila['falla']) == 0 else 'FALLA'} {fila['chequeo']}: {fila['falla']}")
    for sql in ("SELECT count(*) AS n FROM entity360.resolution.registro",
                "SELECT count(*) AS n FROM entity360.resolution.golden_record",
                "SELECT tipo, count(*) AS n FROM entity360.resolution.revision GROUP BY tipo ORDER BY tipo"):
        print(sql.split("FROM ")[1].split()[0], consultar(w, wh, sql))
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
