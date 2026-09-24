"""Spike B.7: CDC en SQL Server "legacy" con datos reales de GLEIF.

Pasos (cada uno se imprime para la evidencia):
  1. Base entity360_legacy_spike + tabla dbo.entidad.
  2. CDC en la base y en la tabla (antes de cargar, para capturar los inserts).
  3. Insert de 10 entidades argentinas reales (API de GLEIF, CC0).
  4. Update técnico: solo `actualizado_en` en 2 registros (no se inventan datos de negocio).
  5. Delete de 1 registro y re-insert con su valor real.
  6. Lectura con cdc.fn_cdc_get_all_changes_dbo_entidad (espera a que el capture job procese).

sqlcmd corre dentro del contenedor y toma la credencial de SQLCMDPASSWORD (entorno del
contenedor, cargado desde .env): no pasa por la línea de comandos ni se imprime.

Uso:
    python spike/legacy-sqlserver/b7_cdc_prueba.py                 # pasos 0-6
    python spike/legacy-sqlserver/b7_cdc_prueba.py --solo-lectura  # solo el paso 6
"""

import re
import subprocess
import sys
import time

import requests

CONTENEDOR = "entity360-spike-mssql"
BASE = "entity360_legacy_spike"
GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"


def sql(texto: str, base: str = "master") -> str:
    cmd = [
        "docker", "exec", "-i", CONTENEDOR, "bash", "-c",
        f"/opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -d {base} -b -W -i /dev/stdin",
    ]
    r = subprocess.run(cmd, input=texto, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"sqlcmd falló:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def lit(valor: str | None) -> str:
    return "NULL" if valor is None else "N'" + valor.replace("'", "''") + "'"


def titulo(t: str) -> None:
    print(f"\n=== {t} ===")


def conteo_por_operacion(salida: str) -> dict[str, int]:
    """Parsea la salida de sqlcmd ('<operacion> <n>' por línea) a {operacion: n}."""
    conteo = {}
    for linea in salida.splitlines():
        m = re.match(r"^(delete|insert|update \((?:antes|después)\))\s+(\d+)\s*$", linea.strip())
        if m:
            conteo[m.group(1)] = int(m.group(2))
    return conteo


def main() -> int:
    if "--solo-lectura" in sys.argv:
        return leer_cambios()

    titulo("0. versión y Agent")
    print(sql("SELECT @@VERSION AS version; "
              "SELECT status_desc AS agent FROM sys.dm_server_services WHERE servicename LIKE 'SQL Server Agent%';"))

    titulo("1. base y tabla")
    print(sql(f"""
IF DB_ID('{BASE}') IS NULL CREATE DATABASE {BASE};
"""))
    print(sql("""
IF OBJECT_ID('dbo.entidad') IS NULL
CREATE TABLE dbo.entidad (
    lei            CHAR(20)       NOT NULL CONSTRAINT pk_entidad PRIMARY KEY,
    nombre_legal   NVARCHAR(500)  NOT NULL,
    pais           CHAR(2)        NOT NULL,
    estado         VARCHAR(20)    NOT NULL,
    actualizado_en DATETIME2(3)   NOT NULL CONSTRAINT df_entidad_actualizado DEFAULT SYSUTCDATETIME()
);
SELECT 'tabla dbo.entidad lista' AS ok;
""", BASE))

    titulo("2. CDC en base y tabla")
    print(sql(f"""
IF (SELECT is_cdc_enabled FROM sys.databases WHERE name = '{BASE}') = 0 EXEC sys.sp_cdc_enable_db;
IF NOT EXISTS (SELECT 1 FROM cdc.change_tables WHERE capture_instance = 'dbo_entidad')
    EXEC sys.sp_cdc_enable_table @source_schema = N'dbo', @source_name = N'entidad',
         @role_name = NULL, @supports_net_changes = 1;
SELECT name, is_cdc_enabled FROM sys.databases WHERE name = '{BASE}';
SELECT capture_instance, supports_net_changes FROM cdc.change_tables;
SELECT j.name AS job_cdc FROM msdb.dbo.cdc_jobs c JOIN msdb.dbo.sysjobs j ON j.job_id = c.job_id
 WHERE c.database_id = DB_ID('{BASE}');
""", BASE))

    titulo("3. insert de 10 entidades reales (GLEIF, AR)")
    resp = requests.get(
        GLEIF_URL,
        params={"filter[entity.legalAddress.country]": "AR", "page[size]": 10},
        headers={"Accept": "application/vnd.api+json"},
        timeout=60,
    )
    resp.raise_for_status()
    filas = [
        (r["id"], r["attributes"]["entity"]["legalName"]["name"],
         r["attributes"]["entity"]["legalAddress"]["country"], r["attributes"]["entity"]["status"])
        for r in resp.json()["data"]
    ]
    valores = ",\n".join(f"({lit(l)}, {lit(n)}, {lit(p)}, {lit(e)})" for l, n, p, e in filas)
    print(sql(f"""
INSERT INTO dbo.entidad (lei, nombre_legal, pais, estado)
SELECT v.lei, v.nombre_legal, v.pais, v.estado
FROM (VALUES {valores}) AS v(lei, nombre_legal, pais, estado)
WHERE NOT EXISTS (SELECT 1 FROM dbo.entidad e WHERE e.lei = v.lei);
SELECT COUNT(*) AS filas FROM dbo.entidad;
""", BASE))

    lei_upd = [filas[0][0], filas[1][0]]
    lei_del = filas[2]

    titulo(f"4. update técnico (actualizado_en) en {lei_upd}")
    print(sql(f"""
UPDATE dbo.entidad SET actualizado_en = SYSUTCDATETIME()
WHERE lei IN ({lit(lei_upd[0])}, {lit(lei_upd[1])});
SELECT @@ROWCOUNT AS actualizadas;
""", BASE))

    titulo(f"5. delete y re-insert de {lei_del[0]}")
    print(sql(f"""
DELETE FROM dbo.entidad WHERE lei = {lit(lei_del[0])};
INSERT INTO dbo.entidad (lei, nombre_legal, pais, estado)
VALUES ({lit(lei_del[0])}, {lit(lei_del[1])}, {lit(lei_del[2])}, {lit(lei_del[3])});
SELECT COUNT(*) AS filas FROM dbo.entidad;
""", BASE))

    return leer_cambios()


def leer_cambios() -> int:
    titulo("6. cambios capturados (cdc.fn_cdc_get_all_changes_dbo_entidad)")
    # El capture job lee el log de forma asíncrona (cada ~5 s por defecto).
    consulta = """
DECLARE @desde BINARY(10) = sys.fn_cdc_get_min_lsn('dbo_entidad');
DECLARE @hasta BINARY(10) = sys.fn_cdc_get_max_lsn();
SELECT CONVERT(VARCHAR(22), __$start_lsn, 1) AS start_lsn,
       CASE __$operation WHEN 1 THEN 'delete' WHEN 2 THEN 'insert'
                         WHEN 3 THEN 'update (antes)' WHEN 4 THEN 'update (después)' END AS operacion,
       lei, LEFT(nombre_legal, 40) AS nombre_legal, actualizado_en
FROM cdc.fn_cdc_get_all_changes_dbo_entidad(@desde, @hasta, N'all update old')
ORDER BY __$start_lsn, __$seqval, __$operation;
"""
    resumen = """
DECLARE @desde BINARY(10) = sys.fn_cdc_get_min_lsn('dbo_entidad');
DECLARE @hasta BINARY(10) = sys.fn_cdc_get_max_lsn();
SELECT CASE __$operation WHEN 1 THEN 'delete' WHEN 2 THEN 'insert'
                         WHEN 3 THEN 'update (antes)' WHEN 4 THEN 'update (después)' END AS operacion,
       COUNT(*) AS cambios
FROM cdc.fn_cdc_get_all_changes_dbo_entidad(@desde, @hasta, N'all update old')
GROUP BY __$operation ORDER BY __$operation;
"""
    esperado = {"insert": 11, "update (antes)": 2, "update (después)": 2, "delete": 1}
    for _ in range(12):
        salida = sql(resumen, BASE)
        obtenido = conteo_por_operacion(salida)
        if obtenido == esperado:
            break
        time.sleep(5)
    print(salida)
    print()
    print(sql(consulta, BASE))
    ok = obtenido == esperado
    print(f"\nesperado {esperado}\nobtenido {obtenido}\n=> {'OK' if ok else 'NO COINCIDE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
