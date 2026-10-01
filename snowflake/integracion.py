"""Catalog integration de Snowflake contra Unity Catalog y base catalog-linked (fase 9, ADR 0012).

Fuera de Terraform a propósito: la integración lleva el secreto OAuth del SP entity360-snowflake y todo
lo que recibe un recurso de Terraform termina en el state. Este script lee el secreto del llavero de
Windows (servicio "entity360-snowflake"), no lo imprime ni lo loguea, y es idempotente:

- `crear`: si la integración ENTITY360_UNITY no existe, la crea; si existe y su configuración coincide,
  **no la toca** (con `--rotar-secreto`, solo cambia el secreto con ALTER). Si existe con otra
  configuración (URI, catálogo, modo de acceso o client_id), falla sin cambiar nada: recrearla es un
  DROP, y eso se hace a mano con OK (docs/destroy.md). Después, la base catalog-linked ENTITY360_UC
  con CREATE DATABASE IF NOT EXISTS, los grants de lectura para los roles de dbt y de los modelers
  (solo cuando la base es nueva, o con `--reaplicar-grants`) y SYSTEM$VERIFY_CATALOG_INTEGRATION.
- `verificar`: solo SYSTEM$VERIFY_CATALOG_INTEGRATION.
- `refrescar`: `ALTER ICEBERG TABLE ... REFRESH` de cada tabla de la base catalog-linked, para ver una
  corrida del DAG sin esperar el refresco automático (cada hora).
- `guardar-secreto`: crea un secreto OAuth para el SP (outputs de infra/databricks) y lo guarda en el
  llavero junto con el host y el client_id. Imprime solo el vencimiento.

Camino A: ACCESS_DELEGATION_MODE = VENDED_CREDENTIALS. Camino A2: EXTERNAL_VOLUME_CREDENTIALS y la base
usa el external volume de infra/snowflake (docs/fase9-plan.md §5).

Uso (desde la raíz del repo; conexión "entity360" de ~/.snowflake/connections.toml, key pair):
    .venv\\Scripts\\python.exe snowflake\\integracion.py guardar-secreto --dias 90
    .venv\\Scripts\\python.exe snowflake\\integracion.py crear --camino A
    .venv\\Scripts\\python.exe snowflake\\integracion.py crear --camino A2 --external-volume ENTITY360_GOLD_VOL
    .venv\\Scripts\\python.exe snowflake\\integracion.py verificar
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICIO = "entity360-snowflake"
INTEGRACION = "ENTITY360_UNITY"
BASE = "ENTITY360_UC"
CATALOGO_UC = "entity360"
# Metadata de las tablas: Gold solo cambia con el DAG (una vez por día) y la sincronización no la frena
# ningún resource monitor. Después de una corrida del DAG se puede forzar (docs/fase9-plan.md §2).
REFRESCO_S = 3600
NAMESPACES = ("gold",)          # solo gold: en silver, bronze o landing el SP recibe 403
SYNC_S = 3600                   # descubrimiento de schemas y tablas de la base (default de Snowflake: 30 s)
ROLES_LECTURA = ("ENTITY360_DBT", "ENTITY360_MODELER")
ROL_SYNC = "ENTITY360_SYNC"     # Airflow: dueño de la base, refresca y reaplica grants (infra/snowflake/sync.tf)
RAIZ = Path(__file__).resolve().parents[1]
PERFIL_DATABRICKS = "entity360-free"
OCULTO = "***"


@dataclass(frozen=True)
class Config:
    host: str                       # https://<WORKSPACE_URL>, sin barra final
    client_id: str                  # application_id del SP entity360-snowflake
    camino: str                     # A | A2
    external_volume: str | None = None

    def __post_init__(self):
        if self.camino not in ("A", "A2"):
            raise ValueError("la integración solo existe en los Caminos A y A2")
        if self.camino == "A2" and not self.external_volume:
            raise ValueError("el Camino A2 necesita --external-volume")

    @property
    def catalog_uri(self) -> str:
        return f"{self.host}/api/2.1/unity-catalog/iceberg-rest"

    @property
    def token_uri(self) -> str:
        return f"{self.host}/oidc/v1/token"

    @property
    def modo(self) -> str:
        return "VENDED_CREDENTIALS" if self.camino == "A" else "EXTERNAL_VOLUME_CREDENTIALS"


# ------------------------------------------------------------------ secreto

def _escapar(valor: str) -> str:
    return valor.replace("\\", "\\\\").replace("'", "\\'")


def _literal(valor: str) -> str:
    return "'" + _escapar(valor) + "'"


def ocultar(texto: str, secreto: str | None) -> str:
    """El texto sin el secreto, ni tal cual ni escapado como va en el SQL. Todo lo que sale del script
    (mensajes y errores) pasa por acá."""
    texto = str(texto)
    if secreto:
        for forma in sorted({_escapar(secreto), secreto}, key=len, reverse=True):
            texto = texto.replace(forma, OCULTO)
    return texto


# ------------------------------------------------------------------ SQL

def _autenticacion(cfg: Config, secreto: str) -> str:
    return (f"REST_AUTHENTICATION = (TYPE = OAUTH OAUTH_TOKEN_URI = {_literal(cfg.token_uri)} "
            f"OAUTH_CLIENT_ID = {_literal(cfg.client_id)} OAUTH_CLIENT_SECRET = {_literal(secreto)} "
            f"OAUTH_ALLOWED_SCOPES = ('all-apis'))")


def sql_crear_integracion(cfg: Config, secreto: str) -> str:
    return (f"CREATE CATALOG INTEGRATION IF NOT EXISTS {INTEGRACION} CATALOG_SOURCE = ICEBERG_REST "
            f"TABLE_FORMAT = ICEBERG REST_CONFIG = (CATALOG_URI = {_literal(cfg.catalog_uri)} "
            f"CATALOG_NAME = {_literal(CATALOGO_UC)} ACCESS_DELEGATION_MODE = {cfg.modo}) "
            f"{_autenticacion(cfg, secreto)} REFRESH_INTERVAL_SECONDS = {REFRESCO_S} ENABLED = TRUE "
            f"COMMENT = 'Unity Catalog de entity360 por Iceberg REST (camino {cfg.camino}). snowflake/integracion.py'")


def sql_rotar_secreto(cfg: Config, secreto: str) -> str:
    return f"ALTER CATALOG INTEGRATION {INTEGRACION} SET {_autenticacion(cfg, secreto)}"


def sql_crear_base(cfg: Config) -> str:
    # Sintaxis de la referencia de CREATE DATABASE (catalog-linked): parámetros del catálogo separados por
    # coma dentro de LINKED_CATALOG; EXTERNAL_VOLUME va afuera.
    permitidos = ", ".join(_literal(n) for n in NAMESPACES)
    volumen = f" EXTERNAL_VOLUME = {_literal(cfg.external_volume)}" if cfg.camino == "A2" else ""
    # Solo lectura también del lado de Snowflake (además de que el SP no tiene MODIFY en Unity Catalog).
    return (f"CREATE DATABASE IF NOT EXISTS {BASE} LINKED_CATALOG = (CATALOG = {_literal(INTEGRACION)}, "
            f"ALLOWED_NAMESPACES = ({permitidos}), ALLOWED_WRITE_OPERATIONS = NONE, "
            f"SYNC_INTERVAL_SECONDS = {SYNC_S}){volumen} "
            f"COMMENT = 'Gold de Unity Catalog sin copiar (catalog-linked). snowflake/integracion.py'")


def sql_grants() -> list[str]:
    """Lectura de Gold para dbt y los modelers. Las tablas las descubre Snowflake: Terraform no las conoce."""
    out = []
    for rol in ROLES_LECTURA:
        out += [f"GRANT USAGE ON DATABASE {BASE} TO ROLE {rol}",
                f"GRANT USAGE ON ALL SCHEMAS IN DATABASE {BASE} TO ROLE {rol}",
                # La base catalog-linked se sincroniza sola, después del CREATE: los schemas y las tablas
                # pueden no existir todavía. Los FUTURE cubren lo que aparezca (a verificar en una base
                # catalog-linked; si no aplican, `crear --reaplicar-grants` después de la sincronización).
                f"GRANT USAGE ON FUTURE SCHEMAS IN DATABASE {BASE} TO ROLE {rol}",
                f"GRANT SELECT ON ALL ICEBERG TABLES IN DATABASE {BASE} TO ROLE {rol}",
                f"GRANT SELECT ON FUTURE ICEBERG TABLES IN DATABASE {BASE} TO ROLE {rol}"]
    return out


def sql_ceder() -> list[str]:
    """Una vez, con ACCOUNTADMIN: la base y lo que tiene pasan a ENTITY360_SYNC, que así refresca las tablas
    y les da SELECT sin ACCOUNTADMIN ni MANAGE GRANTS. COPY CURRENT GRANTS conserva la lectura de dbt y
    los modelers; los FUTURE de la base quedan como están."""
    return [f"GRANT USAGE ON INTEGRATION {INTEGRACION} TO ROLE {ROL_SYNC}",
            f"GRANT OWNERSHIP ON DATABASE {BASE} TO ROLE {ROL_SYNC} COPY CURRENT GRANTS",
            f"GRANT OWNERSHIP ON ALL SCHEMAS IN DATABASE {BASE} TO ROLE {ROL_SYNC} COPY CURRENT GRANTS",
            f"GRANT OWNERSHIP ON ALL ICEBERG TABLES IN DATABASE {BASE} TO ROLE {ROL_SYNC} COPY CURRENT GRANTS"]


def sql_grants_dueno() -> list[str]:
    """Los grants de lectura que puede reaplicar el dueño de la base en cada corrida del DAG: sin FUTURE a
    nivel base, que exigen MANAGE GRANTS (los dejó `crear` con ACCOUNTADMIN y siguen en pie)."""
    return [g for g in sql_grants() if " FUTURE " not in g]


def diferencias(desc: list[tuple], cfg: Config) -> list[str]:
    """Qué de la configuración esperada no aparece en DESC CATALOG INTEGRATION. Se compara contra el texto
    de todas las filas (propiedad y valor), sin depender del formato exacto de REST_CONFIG."""
    texto = " ".join(str(c) for fila in desc for c in fila if c is not None).upper()
    esperado = {"CATALOG_URI": cfg.catalog_uri, "CATALOG_NAME": CATALOGO_UC,
                "ACCESS_DELEGATION_MODE": cfg.modo, "OAUTH_CLIENT_ID": cfg.client_id}
    return [k for k, v in esperado.items() if v.upper() not in texto]


# ------------------------------------------------------------------ ejecución

class IntegracionDesalineada(RuntimeError):
    pass


class Ejecutor:
    """Único lugar que habla con Snowflake. No loguea SQL; un error del conector sale con el secreto oculto
    (Snowflake puede citar el statement en el mensaje de un error de sintaxis)."""

    def __init__(self, cursor):
        self.cursor = cursor

    def __call__(self, sql: str, secreto: str | None = None) -> list[tuple]:
        try:
            self.cursor.execute(sql)
            return list(self.cursor.fetchall() or [])
        except Exception as e:  # noqa: BLE001 - cualquier error sale sin el secreto
            raise RuntimeError(ocultar(f"{type(e).__name__}: {e}", secreto)) from None


class Simulador(Ejecutor):
    """`crear --simular`: corre de verdad solo lo que lee (SHOW, DESC) y anota lo demás sin ejecutarlo."""

    LECTURA = ("SHOW ", "DESC ")

    def __init__(self, cursor):
        super().__init__(cursor)
        self.pendientes: list[str] = []

    def __call__(self, sql: str, secreto: str | None = None) -> list[tuple]:
        if sql.startswith(self.LECTURA):
            return super().__call__(sql, secreto)
        self.pendientes.append(ocultar(sql, secreto))
        return []


def crear(ejecutar, cfg: Config, secreto: str, rotar: bool = False, reaplicar_grants: bool = False,
          decir=print) -> list[str]:
    """Deja la integración, la base y los grants como tienen que estar. Devuelve qué hizo (o, simulando,
    qué haría)."""
    hecho = []
    creada = "se crearía" if isinstance(ejecutar, Simulador) else "creada"
    if not ejecutar(f"SHOW CATALOG INTEGRATIONS LIKE '{INTEGRACION}'"):
        ejecutar(sql_crear_integracion(cfg, secreto), secreto)
        hecho.append(f"integración {INTEGRACION} {creada} (camino {cfg.camino})")
    else:
        faltan = diferencias(ejecutar(f"DESC CATALOG INTEGRATION {INTEGRACION}"), cfg)
        if faltan:
            raise IntegracionDesalineada(
                f"{INTEGRACION} existe con otra configuración ({', '.join(faltan)}): no se modifica sola. "
                "Recrearla es un DROP: docs/destroy.md, con OK.")
        if rotar:
            ejecutar(sql_rotar_secreto(cfg, secreto), secreto)
            hecho.append(f"secreto de {INTEGRACION} rotado")
        else:
            hecho.append(f"integración {INTEGRACION} ya existe con la misma configuración: sin cambios")

    base_nueva = not ejecutar(f"SHOW DATABASES LIKE '{BASE}'")
    if base_nueva:
        ejecutar(sql_crear_base(cfg))
        hecho.append(f"base catalog-linked {BASE} {creada}")
    else:
        hecho.append(f"base {BASE} ya existe: sin cambios")
    if base_nueva or reaplicar_grants:
        for g in sql_grants():
            ejecutar(g)
        hecho.append(f"grants de lectura para {', '.join(ROLES_LECTURA)}")

    hecho.append("verificación: " + verificar(ejecutar, secreto))
    for h in hecho:
        decir(ocultar(h, secreto))
    return hecho


def refrescar(ejecutar, decir=print) -> list[str]:
    """Refresco manual de la metadata de las tablas de la base catalog-linked, después de una corrida del
    DAG (el automático es cada REFRESCO_S). Probado el 2026-09-29: `ALTER ICEBERG TABLE ... REFRESH`."""
    salida = []
    filas = ejecutar(f"SHOW ICEBERG TABLES IN DATABASE {BASE}")
    for f in filas:
        esquema, tabla = f[3], f[1]             # SHOW ICEBERG TABLES: created_on, name, database_name, schema_name
        r = ejecutar(f'ALTER ICEBERG TABLE {BASE}."{esquema}"."{tabla}" REFRESH')
        salida.append(f"{esquema}.{tabla}: {r[0][0] if r else 'ok'}")
    for linea in salida:
        decir(linea)
    return salida


def verificar(ejecutar, secreto: str | None = None) -> str:
    filas = ejecutar(f"SELECT SYSTEM$VERIFY_CATALOG_INTEGRATION('{INTEGRACION}')")
    return ocultar(filas[0][0] if filas else "(sin respuesta)", secreto)


# ------------------------------------------------------------------ llavero y conexión

def leer_llavero() -> tuple[str, str, str]:
    import keyring
    valores = [keyring.get_password(SERVICIO, k) for k in ("databricks_host", "client_id", "client_secret")]
    if not all(valores):
        raise SystemExit(f"faltan credenciales en el llavero ({SERVICIO}): correr `guardar-secreto`")
    host, client_id, secreto = valores
    return host.rstrip("/"), client_id, secreto


def guardar_secreto(dias: int) -> int:
    import keyring

    def cli(*args):
        r = subprocess.run(["databricks", *args, "-p", PERFIL_DATABRICKS, "-o", "json"], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"databricks {args[0]} falló: {r.stderr.strip()[:300]}")
        return json.loads(r.stdout)

    salidas = {o: v["value"] for o, v in json.loads(
        (RAIZ / "infra" / "databricks" / "terraform.tfstate").read_text(encoding="utf-8"))["outputs"].items()}
    if not salidas.get("snowflake_sp_id"):
        raise SystemExit("no existe el SP de Snowflake: fase9_snowflake = true y apply en infra/databricks")
    host = cli("auth", "describe")["details"]["host"].rstrip("/")
    s = cli("service-principal-secrets-proxy", "create", str(salidas["snowflake_sp_id"]), "--lifetime", f"{dias * 86400}s")
    for k, v in (("databricks_host", host), ("client_id", salidas["snowflake_sp_application_id"]),
                 ("client_secret", s["secret"])):
        keyring.set_password(SERVICIO, k, v)
    print(f"secreto guardado en el llavero ({SERVICIO}); vence {s.get('expire_time')}. "
          "Si la integración ya existe: `crear --rotar-secreto`.")
    return 0


def conectar(conexion: str):
    import snowflake.connector
    # El conector loguea el texto de cada query en DEBUG: nunca por debajo de WARNING acá.
    logging.getLogger("snowflake.connector").setLevel(logging.WARNING)
    if conexion != "entorno":
        return snowflake.connector.connect(connection_name=conexion)
    # Airflow: ENTITY360_SYNC_SVC con la clave privada montada (docker-compose.yml). Sin roles
    # secundarios: lo que corre, corre con los privilegios de ENTITY360_SYNC y nada más.
    con = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_SYNC_USER"],
        private_key_file=os.environ["SNOWFLAKE_SYNC_KEY_PATH"], role=ROL_SYNC, warehouse="ENTITY360_WH")
    con.cursor().execute("USE SECONDARY ROLES NONE")
    return con


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="accion", required=True)
    g = sub.add_parser("guardar-secreto")
    g.add_argument("--dias", type=int, default=90)
    c = sub.add_parser("crear")
    c.add_argument("--camino", choices=["A", "A2"], required=True)
    c.add_argument("--external-volume")
    c.add_argument("--rotar-secreto", action="store_true")
    c.add_argument("--reaplicar-grants", action="store_true")
    c.add_argument("--conexion", default="entity360")
    c.add_argument("--simular", action="store_true", help="solo lee; lista lo que ejecutaría (secreto oculto)")
    v = sub.add_parser("verificar")
    v.add_argument("--conexion", default="entity360")
    r = sub.add_parser("refrescar", help="refresca la metadata de las tablas de gold (después del DAG)")
    r.add_argument("--conexion", default="entity360", help="'entorno' en Airflow (ENTITY360_SYNC_SVC)")
    gr = sub.add_parser("grants", help="reaplica la lectura de gold para dbt y los modelers (dueño de la base)")
    gr.add_argument("--conexion", default="entity360", help="'entorno' en Airflow (ENTITY360_SYNC_SVC)")
    ce = sub.add_parser("ceder", help="una vez, con ACCOUNTADMIN: la base pasa a ENTITY360_SYNC")
    ce.add_argument("--conexion", default="entity360")
    ce.add_argument("--simular", action="store_true", help="lista los GRANT sin ejecutarlos")
    a = ap.parse_args()

    if a.accion == "guardar-secreto":
        return guardar_secreto(a.dias)
    con = conectar(a.conexion)
    try:
        ejecutar = Simulador(con.cursor()) if getattr(a, "simular", False) else Ejecutor(con.cursor())
        if a.accion == "verificar":
            print(verificar(ejecutar))
            return 0
        if a.accion == "refrescar":
            refrescar(ejecutar)
            return 0
        if a.accion in ("grants", "ceder"):
            for sql in (sql_grants_dueno() if a.accion == "grants" else sql_ceder()):
                ejecutar(sql)
                print(f"{'(simulado) ' if isinstance(ejecutar, Simulador) else ''}{sql}")
            return 0
        host, client_id, secreto = leer_llavero()
        try:
            crear(ejecutar, Config(host, client_id, a.camino, a.external_volume), secreto,
                  rotar=a.rotar_secreto, reaplicar_grants=a.reaplicar_grants)
        except IntegracionDesalineada as e:
            print(f"ERROR: {ocultar(e, secreto)}", file=sys.stderr)
            return 1
        if isinstance(ejecutar, Simulador):
            print("\nSIMULACIÓN: no se ejecutó nada de esto (el secreto va como ***):")
            for sql in ejecutar.pendientes:
                print(f"  {sql};")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
