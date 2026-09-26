# Legacy: el ERP "on-prem" (SQL Server + CDC)

**Historia (regla 04):** el ERP viejo de la organización, un SQL Server que vive "on-premise"
(un container en la PC). Cargar datos reales de GLEIF en un SQL Server para que haga de sistema
legacy es una **decisión de arquitectura, no de datos** (principio 1): no hay nada inventado.

## Qué hay
| Pieza | Archivo |
|---|---|
| SQL Server 2022 **Developer** (el CDC necesita el Agent; Express no lo trae), solo en `127.0.0.1:1433` | `docker-compose.yml` (+ `.env`, fuera de git) |
| Modelo normalizado: `erp.entidad`, `erp.direccion`, `erp.nombre_alternativo`, `erp.relacion`; control `etl.aplicacion_gleif` | `sql/001_modelo.sql` |
| CDC en las 4 tablas `erp.*` (instancias `erp_<tabla>`, net changes habilitado) | `sql/002_cdc.sql` |
| Carga inicial y deltas diarios de GLEIF | `gleif_erp.py` |

## Universo cargado (2026-09-25, publicación GLEIF 16:00)
| Alcance | Criterio | Entidades |
|---|---|---|
| `universo_ar` | domicilio legal o jurisdicción AR | 965 |
| `sede_ar` | no argentinas con sede (headquarters) en AR | 55 |
| `control` | contrapartes no argentinas de relaciones RR con las anteriores | 142 |
| **Total** | | **1.162** |

Más 2.324 direcciones (legal y sede), 146 nombres alternativos y 393 relaciones.

Primer delta real (2026-09-26, `LastWeek` de la publicación 16:00, porque habían pasado más de 24 h):
19 registros del universo, **1 alta** (Provincia de San Juan, LEI registrado el 2026-09-25, con sus 2
direcciones y un nombre alternativo) y **7 updates** (renovaciones de 4 entidades, una dirección y 2
relaciones). El extractor los llevó al volume como un lote de 11 cambios; la segunda corrida no empujó
nada.

## Cómo corre
```powershell
cd legacy
docker compose up -d --wait
# modelo y CDC (idempotentes). Sin pipe: PowerShell 5.1 le agrega un BOM y sqlcmd falla.
foreach ($f in '001_modelo.sql','002_cdc.sql') {
  docker cp "sql\$f" "entity360-legacy-mssql:/tmp/$f"
  docker exec entity360-legacy-mssql /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -b -i "/tmp/$f"
}
cd ..
.venv\Scripts\python.exe legacy\gleif_erp.py carga-inicial   # una vez
.venv\Scripts\python.exe legacy\gleif_erp.py delta           # diario (LastDay, o LastWeek si pasó más de un día)
```
El CDC se habilita **antes** de la carga inicial a propósito: la primera corrida del extractor
lleva el estado inicial completo como inserts, por el mismo camino que después los cambios.

## Idempotencia
- `etl.aplicacion_gleif` registra cada archivo aplicado con su sha256: re-correr la carga o el
  mismo delta no hace nada.
- El `MERGE` solo actualiza si **cambió algún campo** (`EXISTS (... EXCEPT ...)`). Verificado:
  aplicar el delta LastDay de la misma publicación que el golden copy dio 0 inserts, 0 updates y
  0 deletes, y el CDC no registró ningún update falso.

## Por qué el CDC captura casi solo inserts y updates
GLEIF **nunca borra un LEI**. Cuando una entidad deja de existir o su registro se invalida, GLEIF
cambia su estado (`RegistrationStatus` a `RETIRED`, `ANNULLED`, `LAPSED`, `DUPLICATE`, ...;
`EntityStatus` a `INACTIVE`). El ERP refleja eso con **bajas lógicas**: un `UPDATE` del estado, que
es lo que haría un ERP real con historia contable. Un `DELETE` físico no tendría respaldo en los
datos (principio 1).

Por eso el CDC ve:
- **Inserts:** la carga inicial y las altas (entidades nuevas que entran al universo).
- **Updates:** cambios de nombre, dirección, estado (incluidas las bajas lógicas), renovaciones.
- **Deletes:** solo en `erp.nombre_alternativo`, cuando GLEIF deja de informar un nombre de una
  entidad. Es raro, pero real.

Bronze (fase 6) conserva la operación y el LSN de cada cambio; Silver arma el historial (SCD2).

## Apagado limpio (el exit 137)
El contenedor salía con **137** (SIGKILL) en cada `docker compose stop`, aun con
`stop_grace_period: 30s`, y sin ningún mensaje de cierre de SQL Server en el log. No era memoria
(`OOMKilled=false`).

**Causa:** el entrypoint de la imagen (`/opt/mssql/bin/launch_sqlservr.sh`) deja a **bash como
PID 1**, lanza `sqlservr` en segundo plano (`"$@" &`) y hace `wait`. Bash como PID 1 no tiene handler
de SIGTERM (el kernel no le entrega señales sin handler al PID 1) y tampoco se la reenvía al hijo:
`docker stop` espera el grace period entero y termina con SIGKILL. Subir el grace period solo demora
el SIGKILL; cambiar `stop_signal` no sirve porque ninguna señal atrapable llega a `sqlservr`.

**Solución:** `init: true` + `entrypoint: ["/opt/mssql/bin/sqlservr"]`. Tini queda como PID 1, le
reenvía el SIGTERM a `sqlservr` y cosecha zombies. El wrapper que se saltea solo imprime un aviso de
permisos y corre el setup de `MSSQL_DB` / `/mssql-server-setup-scripts.d`, que acá no se usan.

Prueba (2026-09-26, contenedores descartables sin volumen, imagen `2022-latest`, Agent habilitado):

| Variante | `docker stop` | Exit | Cierre de SQL Server en el log |
|---|---|---|---|
| Imagen tal cual (bash PID 1) | 30,5 s | 137 | no |
| `init: true` | 0,5 s | 143 | **no**: tini mata a bash y `sqlservr` cae con el contenedor |
| `init: true` + `TINI_KILL_PROCESS_GROUP=1` | 0,4 s | 143 | no |
| `entrypoint: sqlservr` | 0,6 s | 0 | sí ("terminating in response to a 'stop' request") |
| **`init: true` + `entrypoint: sqlservr`** (elegida) | 1,4 s | 0 | sí |

`init: true` solo es la trampa: el 143 parece un cierre ordenado y no lo es. Con la base real, después
del cambio: `stop` en 0,9 s, exit 0, cierre completo en el log.

**Después del 137 del 2026-09-25 la base quedó intacta** (verificado el 2026-09-26): `DBCC CHECKDB`
sin errores, conteos iguales a la carga, CDC habilitado en las 4 tablas, Agent y capture job
corriendo. SQL Server recupera por el log de transacciones; el riesgo del SIGKILL era un recovery
más largo o una transacción a medias, no pérdida de lo commiteado.

## Limitación asumida
Corre **cuando la PC está prendida**. Es coherente con la historia (un sistema on-prem) y está
contemplado: si pasó más de un día desde la última aplicación, `delta` usa el archivo
**LastWeek** de GLEIF en lugar de LastDay, y el extractor retoma desde el último LSN procesado.

## Mejora opcional (no implementada)
**Debezium Server** leyendo el CDC de SQL Server y publicando los cambios como eventos, en lugar del
extractor por lotes. Da latencia de segundos en vez de minutos, a cambio de operar un servicio más.
Con el volumen de este ERP (decenas de cambios por día), el extractor por lotes alcanza.
