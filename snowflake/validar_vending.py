"""Fase 9, paso 1 (regla 11, docs/fase9-plan.md §1): credential vending de Unity Catalog con el SP de
Snowflake, ANTES de abrir el trial.

El spike lo probó con el token del usuario (4e). Acá se prueba con el principal que va a usar Snowflake
(`entity360-snowflake`, OAuth M2M, infra/databricks/snowflake.tf) y sus grants mínimos:

  0. Las credenciales locales de AWS están ocultas: si el proceso pudiera leer el bucket por su cuenta,
     un scan exitoso no probaría el vending (falso positivo).
  1. Token OAuth M2M del SP (client credentials, scope all-apis).
  2. GET /v1/config del catálogo entity360.
  3. loadTable crudo de gold.dim_entity con X-Iceberg-Access-Delegation: vended-credentials: tiene que
     traer credenciales S3 temporales (se listan las claves, nunca los valores).
  4. PyIceberg: load_table y scan de gold.dim_entity; la cantidad de filas tiene que coincidir con la
     de Databricks (--filas-esperadas, de SELECT count(*) FROM entity360.gold.dim_entity).
  5. Mínimo privilegio: loadTable de silver.sec_emisor tiene que FALLAR (el SP solo ve gold).

No escribe nada: la protección de escritura es que el SP no tiene MODIFY. No usa el SQL warehouse (la
metadata sale de la API de Unity Catalog y los datos, de S3), así que no consume la cuota diaria.

Credenciales del SP: del llavero de Windows (servicio "entity360-snowflake", las guarda
`snowflake/integracion.py guardar-secreto`) o, si no, de E360_SF_CLIENT_ID y E360_SF_CLIENT_SECRET.
Nunca en disco ni en la línea de comandos.

Uso (en el .venv de la raíz, con snowflake/requirements.txt instalado):
    $env:AWS_CONFIG_FILE = "NUL"; $env:AWS_SHARED_CREDENTIALS_FILE = "NUL"
    $env:DATABRICKS_HOST = "https://<WORKSPACE_URL>"
    .venv\\Scripts\\python.exe snowflake\\validar_vending.py --filas-esperadas 1136
Sale 0 si todo pasa, 1 si algo falla, 2 si no se pudo aislar de las credenciales locales de AWS.
"""

import argparse
import os
import sys
import traceback

import requests

CATALOGO = "entity360"


def credenciales_locales_aws() -> list[str]:
    fuga = [k for k in ("AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN", "AWS_PROFILE") if os.environ.get(k)]
    for var, defecto in (("AWS_CONFIG_FILE", "~/.aws/config"), ("AWS_SHARED_CREDENTIALS_FILE", "~/.aws/credentials")):
        ruta = os.environ.get(var, defecto)
        if ruta.upper() != "NUL" and os.path.exists(os.path.expanduser(ruta)):
            fuga.append(var)
    return fuga


def credenciales_sp() -> tuple[str, str]:
    try:
        import keyring
        cid, sec = (keyring.get_password("entity360-snowflake", k) for k in ("client_id", "client_secret"))
    except ImportError:
        cid = sec = None
    return cid or os.environ["E360_SF_CLIENT_ID"], sec or os.environ["E360_SF_CLIENT_SECRET"]


class Pasos:
    """Corre cada chequeo e imprime su resultado. Nada de lo que imprime puede llevar el secreto del SP ni
    el token: se ocultan en todo (resultados y errores). El 2026-09-29 el paso 1 imprimió el token."""

    def __init__(self):
        self.fallas = []
        self.ocultos: set[str] = set()

    def ocultar(self, texto) -> str:
        texto = str(texto)
        for s in self.ocultos:
            texto = texto.replace(s, "***")
        return texto

    def __call__(self, nombre, fn):
        print(f"\n=== {nombre} ===")
        try:
            r = fn()
            print(f"OK: {self.ocultar(r)}")
            return r
        except Exception as e:  # noqa: BLE001 - se registra cualquier falla y se sigue
            print(f"FALLA: {self.ocultar(traceback.format_exception_only(type(e), e)[-1].strip()[:800])}")
            self.fallas.append(nombre)
            return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--filas-esperadas", type=int, required=True)
    a = ap.parse_args()

    fuga = credenciales_locales_aws()
    if fuga:
        print(f"ABORTA: el proceso ve credenciales locales de AWS ({fuga}); el resultado no sería concluyente.")
        return 2
    print("credenciales locales de AWS: ocultas (OK)")

    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    uri = f"{host}/api/2.1/unity-catalog/iceberg-rest"
    paso = Pasos()

    client_id, secreto = credenciales_sp()
    paso.ocultos.add(secreto)
    obtenido = {}

    def token():
        """Devuelve una descripción, nunca el token: Pasos imprime lo que devuelve cada paso."""
        r = requests.post(f"{host}/oidc/v1/token", timeout=60, auth=(client_id, secreto),
                          data={"grant_type": "client_credentials", "scope": "all-apis"})
        r.raise_for_status()
        cuerpo = r.json()
        obtenido["token"] = cuerpo["access_token"]
        paso.ocultos.add(obtenido["token"])
        return f"token obtenido (no se imprime), scope {cuerpo.get('scope')}, vence en {cuerpo.get('expires_in')} s"

    paso("1. Token OAuth M2M del SP", token)
    tok = obtenido.get("token")
    if not tok:
        return 1
    h = {"Authorization": f"Bearer {tok}"}

    def config():
        r = requests.get(f"{uri}/v1/config", params={"warehouse": CATALOGO}, headers=h, timeout=60)
        r.raise_for_status()
        return f"HTTP {r.status_code} {r.text[:300]}"

    def load_crudo(namespace, tabla):
        r = requests.get(f"{uri}/v1/catalogs/{CATALOGO}/namespaces/{namespace}/tables/{tabla}", timeout=60,
                         headers={**h, "X-Iceberg-Access-Delegation": "vended-credentials"})
        return r

    def vending():
        r = load_crudo("gold", "dim_entity")
        r.raise_for_status()
        cuerpo = r.json()
        claves = sorted((cuerpo.get("config") or {}).keys())
        creds = cuerpo.get("storage-credentials") or []
        if not ({"s3.access-key-id", "s3.session-token"} <= set(claves) or creds):
            raise RuntimeError(f"sin credenciales S3 en la respuesta: config={claves}")
        return f"HTTP 200; claves de config={claves}; storage-credentials={len(creds)}"

    paso("2. GET /v1/config", config)
    paso("3. loadTable gold.dim_entity (vended-credentials)", vending)

    def scan():
        from pyiceberg.catalog.rest import RestCatalog
        cat = RestCatalog("uc", uri=uri, warehouse=CATALOGO, token=tok,
                          **{"header.X-Iceberg-Access-Delegation": "vended-credentials"})
        t = cat.load_table("gold.dim_entity")
        filas = t.scan(selected_fields=("entity_id", "nombre")).to_arrow().num_rows
        if filas != a.filas_esperadas:
            raise RuntimeError(f"{filas} filas y Databricks dice {a.filas_esperadas}")
        return f"{filas} filas, igual que Databricks; snapshot {t.current_snapshot().snapshot_id}"

    paso("4. PyIceberg load_table + scan de gold.dim_entity", scan)

    def no_ve_silver():
        r = load_crudo("silver", "sec_emisor")
        if r.ok:
            raise RuntimeError("el SP pudo cargar silver.sec_emisor: sobran grants")
        return f"HTTP {r.status_code} (esperado: sin acceso)"

    paso("5. Mínimo privilegio: silver.sec_emisor no se puede cargar", no_ve_silver)

    print("\nRESULTADO: " + ("todo OK: Camino A habilitado para abrir el trial" if not paso.fallas
                            else f"fallaron {paso.fallas}: ver docs/fase9-plan.md §5 antes de abrir el trial"))
    return 1 if paso.fallas else 0


if __name__ == "__main__":
    sys.exit(main())
