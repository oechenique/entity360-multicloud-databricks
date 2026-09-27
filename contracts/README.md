# Contratos de llegada (regla 09, Soda Core)

Cada lote que un productor deja en el landing se verifica **antes** de entrar a Bronze. Si falla un
check crítico, el lote va a cuarentena y se genera una alerta. Las demás fuentes siguen su camino:
un proveedor roto no frena la plataforma.

## Qué se verifica

Por fuente, dos archivos:

| Archivo | Qué hace |
|---|---|
| `<fuente>.sql` | Proyecta el lote crudo (tabla `crudo` en DuckDB) a una vista `lote`. En SEC EDGAR y el CDC lee campos anidados: si la fuente cambia de formato, la proyección falla y el lote va a cuarentena. |
| `<fuente>.yml` | Contrato de **Soda Core 4** sobre la vista: esquema, no nulos, unicidad, valores válidos, frescura y volumen. |

Además, `verificar.py` compara el lote con su manifest: **sha256** y **cantidad de registros**.

- **Críticos** (nivel `fail`, el default de Soda): el lote va a cuarentena.
- **Avisos** (`level: warn`): quedan en el veredicto y el lote pasa. Son el volumen fuera de rango, la
  frescura, el ticker faltante en la SEC y los tipos de entidad nuevos en OpenSanctions.
- La **frescura** se mide contra el `extraido_utc` del manifest, no contra la hora de la verificación:
  un lote verificado tarde (con la PC apagada) o re-verificado da el mismo veredicto.

| Fuente | Críticos | Avisos |
|---|---|---|
| `sqlserver_cdc` | tabla y operación válidas, LSN hexadecimal, LEI con formato ISO 17442, sin nulos en la clave, sin cambios duplicados | volumen 1–5.000 |
| `sec_edgar` | proyección (formato de submissions), CIK y nombre sin nulos, CIK único | ticker faltante, volumen 1–100 |
| `gdelt` | `entidad` es una clave de `alias.json`, tono entre −100 y 100, id sin nulos, (id, entidad) único | url faltante, menciones de más de 26 h, volumen 1–2.000 |
| `opensanctions` | id y nombre sin nulos, id único | tipo de entidad nuevo, sin cambios en 7 días, volumen 1.000–10.000 |
| `wikidata` | QID con formato `Q<n>`, único, con alguna etiqueta | volumen 5–200 |

## Veredicto y cuarentena

`verificar.py` escribe `_contrato_<ts>.json` junto al manifest del lote, con el estado (`aprobado` o
`cuarentena`), las fallas críticas, los avisos y el resultado de cada check. Bronze
(`databricks/medallion/capa2.py`) no ingiere un lote en `cuarentena`: queda como `cuarentena_contrato`
en `ops.ingestion_log`. El veredicto es de un sha256: si el archivo cambia, ese veredicto no aplica.

Un lote en cuarentena se revisa a mano. Si fue un error de la fuente, el productor reenvía un lote nuevo
(otro timestamp) y ese se verifica solo.

## Alertas

`alertas.py` manda las cuarentenas a Telegram. Credenciales en variables de entorno, fuera de git:
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (cómo crearlas: `docs/manual-steps.md`). Sin credenciales,
la alerta va a stderr y el proceso sigue.

## Correr

Entorno propio (Soda y DuckDB no se mezclan con el de la fase 6):

```powershell
python -m venv contracts\.venv
contracts\.venv\Scripts\python.exe -m pip install -r contracts\requirements.txt pytest==9.1.1

# Lotes del volume sin veredicto (perfil de la CLI de Databricks, por defecto entity360-free)
contracts\.venv\Scripts\python.exe contracts\verificar.py --pendientes [--fuente gdelt]

# Un lote local
contracts\.venv\Scripts\python.exe contracts\verificar.py --fuente gdelt --archivo lote.jsonl --manifest m.json

# Tests (muestras reales de lotes en tests\contracts\datos)
contracts\.venv\Scripts\python.exe -m pytest tests\contracts
```

En la fase 8, Airflow corre `--pendientes` antes de disparar el job de Databricks.

Primera verificación (2026-09-27): los 10 lotes del landing, **aprobados**, en 31 s.
