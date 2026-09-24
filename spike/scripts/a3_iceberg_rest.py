"""Spike A.3: Iceberg gestionado de Free Edition por el endpoint Iceberg REST de Unity Catalog.

Prueba paso a paso y registra cada resultado sin cortar en el primer error:
  1. GET /v1/config del catálogo.
  2. loadTable crudo con X-Iceberg-Access-Delegation: vended-credentials, para ver si
     vienen credenciales (solo se listan las claves, nunca los valores).
  3. PyIceberg: load_table (metadata).
  4. PyIceberg: scan (lectura de datos en S3).
  5. PyIceberg: append (escritura).

Auth: DATABRICKS_HOST y DATABRICKS_TOKEN del entorno (token OAuth del usuario).
Correr con las credenciales locales de AWS ocultas (AWS_CONFIG_FILE y
AWS_SHARED_CREDENTIALS_FILE a un archivo inexistente): si el bucket es propio, leer con
las credenciales locales sería un falso positivo del credential vending.

Uso:
    spike\\.venv\\Scripts\\python.exe spike\\scripts\\a3_iceberg_rest.py [catalogo]
    (catalogo por defecto: entity360; en A.4b se usa entity360_ext)
"""

import os
import sys
import traceback

import requests

CATALOGO = sys.argv[1] if len(sys.argv) > 1 else "entity360"
NAMESPACE = "spike"
TABLA = "gleif_iceberg"


def paso(nombre, fn):
    print(f"\n=== {nombre} ===")
    try:
        resultado = fn()
        print(f"OK: {resultado}")
        return True, resultado
    except Exception as e:  # noqa: BLE001 - el spike registra cualquier falla
        ultima = traceback.format_exception_only(type(e), e)[-1].strip()
        print(f"FALLA: {ultima[:800]}")
        return False, None


def credenciales_locales_aws() -> list[str]:
    fuga = [k for k in ("AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN", "AWS_PROFILE") if os.environ.get(k)]
    for var, defecto in (("AWS_CONFIG_FILE", "~/.aws/config"), ("AWS_SHARED_CREDENTIALS_FILE", "~/.aws/credentials")):
        if os.path.exists(os.path.expanduser(os.environ.get(var, defecto))):
            fuga.append(var)
    return fuga


def main() -> int:
    fuga = credenciales_locales_aws()
    if fuga:
        print(f"ABORTA: el proceso ve credenciales locales de AWS ({fuga}); el resultado no sería concluyente.")
        return 2
    print("credenciales locales de AWS: ocultas (OK)")
    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    token = os.environ["DATABRICKS_TOKEN"]
    uri = f"{host}/api/2.1/unity-catalog/iceberg-rest"
    headers = {"Authorization": f"Bearer {token}"}

    def config():
        r = requests.get(f"{uri}/v1/config", params={"warehouse": CATALOGO}, headers=headers, timeout=60)
        return f"HTTP {r.status_code} {r.text[:400]}"

    def load_crudo():
        r = requests.get(
            f"{uri}/v1/catalogs/{CATALOGO}/namespaces/{NAMESPACE}/tables/{TABLA}",
            headers={**headers, "X-Iceberg-Access-Delegation": "vended-credentials"},
            timeout=60,
        )
        if not r.ok:
            return f"HTTP {r.status_code} {r.text[:500]}"
        cuerpo = r.json()
        return (
            f"HTTP {r.status_code}; location={cuerpo.get('metadata', {}).get('location')}; "
            f"claves de config={sorted(cuerpo.get('config', {}).keys())}; "
            f"storage-credentials={len(cuerpo.get('storage-credentials', []) or [])}"
        )

    paso("1. GET /v1/config", config)
    paso("2. loadTable crudo (vended-credentials)", load_crudo)

    from pyiceberg.catalog.rest import RestCatalog

    catalogo = RestCatalog(
        "uc",
        uri=uri,
        warehouse=CATALOGO,
        token=token,
        **{"header.X-Iceberg-Access-Delegation": "vended-credentials"},
    )

    ok, tabla = paso(
        "3. PyIceberg load_table (metadata)",
        lambda: catalogo.load_table(f"{NAMESPACE}.{TABLA}"),
    )
    if ok:
        print(f"schema:\n{tabla.schema()}")
        print(f"snapshot actual: {tabla.current_snapshot()}")

        ok_scan, arrow = paso("4. PyIceberg scan (lectura de datos)", lambda: tabla.scan().to_arrow())
        if ok_scan:
            print(arrow.select(["lei", "nombre_legal"]).slice(0, 3))

        def append():
            # Reescribe una fila real ya leída (sin inventar datos); si funciona, la tabla
            # queda con 11 filas y eso se anota. La tabla se destruye con el schema.
            import pyarrow as pa

            fila = arrow.slice(0, 1) if ok_scan else pa.table({})
            tabla.append(fila)
            return f"append de {fila.num_rows} fila(s)"

        paso("5. PyIceberg append (escritura)", append)
    return 0


if __name__ == "__main__":
    sys.exit(main())
