# Consumo del stack de Airflow (2026-09-29)

Medido con `airflow/medir.py` (`docker stats` cada 10 s; CPU de docker: 100 % = un núcleo lógico).
PC: i5-12500H (16 hilos), 15,6 GB de RAM, Docker Desktop sobre WSL2.

## Qué cambió (stack liviano)
| | Antes | Stack liviano |
|---|---|---|
| Executor | LocalExecutor | LocalExecutor (sin cambio) |
| Triggerer | no había | no hace falta: ninguna tarea es diferible (sensores `mode=reschedule`, `DatabricksRunNowOperator` sin `deferrable`) |
| Tareas a la vez | 32 (16 por DAG) | 4 (4 por DAG) |
| Parseo del DAG | 2 procesos, cada 30 s | 1 proceso, cada 5 min |
| Workers del api-server | 1 | 1 |
| Techo por container | ninguno | postgres 0,5 CPU / 384 MB; api-server 1 / 768 MB; scheduler 2 / 2 GB (ejecuta dbt, Soda y el CDC); dag-processor 1 / 1 GB; init 1 / 1 GB |
| WSL2 (`.wslconfig`) | sin archivo: 8 GB y 16 procesadores | 6 procesadores, 5,8 GB, 2 GB de swap (`airflow/wslconfig.propuesto`, aplicado por Gastón) |

## Reposo (5 min, DAG pausado)
| Container | CPU media antes | CPU media liviano | Memoria máx. antes | Memoria máx. liviano |
|---|---|---|---|---|
| api-server | 0,2 % | 0,1 % | 250 MiB | 245 MiB |
| dag-processor | 1,3 % | 0,8 % | 295 MiB | 251 MiB |
| scheduler | 1,8 % | 1,8 % | 454 MiB | 324 MiB |
| postgres | 1,6 % | 1,3 % | 61 MiB | 34 MiB |
| SQL Server del legacy | 5,1 % | 3,6 % | 1353 MiB | 1248 MiB |
| **Total** | **10,1 %** (máx. 20,6 %) | **7,6 %** (máx. 12,7 %) | **2410 MiB** | **2102 MiB** |

Datos: `reposo-pesado.csv`, `reposo-liviano.csv`. Con el stack liviano, Windows queda con 1,3–1,6 GB
libres en reposo (el resto lo usan Windows y otras aplicaciones, no el stack).

En reposo el stack ya era chico: el problema es la **corrida**.

## Corrida con la configuración anterior (2026-09-29 16:11–16:30 UTC)
La medición se perdió: la primera versión de `medir.py` escribía el CSV al final y el proceso se cortó
por falta de memoria. Lo que se observó: Windows llegó a **0,6 GB libres** con los containers en ~2,9 GB;
la presión era la VM de WSL sin techo (retiene la caché de Linux). `medir.py` ahora escribe cada muestra
en el momento y registra la memoria libre de Windows.

## Pendiente
Corrida completa del DAG (24/24) con el stack liviano, medida con `--run-id`. Bloqueada por la cuota
diaria de cómputo serverless de Free Edition (el warehouse no arranca desde el 2026-09-29 ~17:10 UTC).
Si el SQL Server aprieta la memoria durante la corrida, se le pone un techo de 2 GB en
`legacy/docker-compose.yml`.
