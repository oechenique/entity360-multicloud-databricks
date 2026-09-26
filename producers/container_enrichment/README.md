# Container de enriquecimiento (OpenSanctions + Wikidata → UC Volume)

Regla 07. Fuentes de riesgo y de vínculos que no pertenecen a ninguna nube de la organización: una
imagen Docker que corre igual en cualquier lado. Se publica en GitHub Container Registry y GitHub
Actions la corre una vez por día.

```text
push a main (este directorio)  → enriquecimiento-imagen.yml → ghcr.io/<owner>/entity360-enrichment:{sha,latest}
cron diario 09:17 UTC (o a mano) → enriquecimiento-diario.yml → docker run :latest
                                    → OpenSanctions (targets.simple.csv, streaming) ─┐
                                    → Wikidata SPARQL (4 consultas)                  ─┴→ OAuth M2M (SP entity360-producer-enrichment)
                                                                                        → PUT .jsonl + _manifest al volume
```

## Salida (contrato de landing, regla 01)
Un lote por fuente, independientes: si una falla, la otra igual se publica y el workflow queda en rojo.

| Fuente | Ruta | Qué trae | Tamaño (2026-09-26) |
|---|---|---|---|
| `opensanctions` | `/Volumes/entity360/landing/raw/opensanctions/ingest_date=…/` | Entidades no-persona (`Company`, `Organization`, `LegalEntity`, `PublicBody`) con país AR **o** con un LEI en `identifiers`. Campos de `targets.simple.csv` sin `last_seen`; listas partidas por `;` (salvo `sanctions` y `addresses`, texto crudo) y `leis` extraídos | 2.597 (36 AR + 2.561 con LEI), 5 MB |
| `wikidata` | `/Volumes/entity360/landing/raw/wikidata/ingest_date=…/` | Un ítem por fila: etiquetas es/en, LEI, CIK, tickers (`NYSE:YPF`), sitios web, países ISO y el motivo por el que entró | 20 ítems, 5 KB |

**Por qué ese filtro de OpenSanctions:** "entidades que puedan cruzarse con el universo". Las AR se
cruzan por nombre normalizado con GLEIF AR (spike 11c); las que tienen LEI se cruzan por LEI con
cualquier entidad del universo, incluido el conjunto de control no argentino (matrices extranjeras).
Las personas quedan afuera: el universo son empresas.

**Wikidata:** las tres consultas validadas en el spike (ítems AR con LEI o CIK; los 16 emisores de
`producers/aws_sec_edgar/universo.json` por CIK y por ticker en NYSE/Nasdaq) más una de detalle.
Es una **señal extra** del matching, no la verdad de referencia (D11). Pautas del endpoint:
User-Agent con contacto, consultas en serie con 1 s de pausa, `Retry-After` en 429/503.

Manifest: `registros`, `sha256`, `extraido_utc`, `producer_version`, licencia y atribución; en
OpenSanctions además `version_fuente` y `filas_leidas_fuente`.

## Idempotencia (D6, capa 1)
Antes de empujar, lee el último manifest de la fuente en el volume y compara el `sha256`: si no
cambió, no sube nada. Para que eso funcione, el JSONL es determinístico (filas ordenadas, claves
ordenadas) y se descarta `last_seen` de OpenSanctions, que cambia en cada export aunque la entidad
no cambie. Verificado: dos corridas seguidas, la segunda no empujó ninguna de las dos fuentes.

## Credenciales (ADR 0002)
SP propio `entity360-producer-enrichment` (`infra/databricks/producers.tf`), con los mismos grants
mínimos que el resto de los productores. El secreto OAuth vive **solo** en GitHub Secrets:
```powershell
winget install GitHub.cli; gh auth login          # una vez
$env:ENRIQUECIMIENTO_USER_AGENT = "entity360 (portfolio) <CONTACT_EMAIL>"
.venv\Scripts\python.exe producers\container_enrichment\credenciales.py cargar --dias 90
```
Carga `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` y `USER_AGENT`. Valida
`gh` antes de crear el secreto del SP. Rotar antes del vencimiento (volver a correr `cargar`).

**Logs sin datos identificatorios (principio 9):** el repo es privado, pero se piensa publicar al
cerrar el portfolio y los logs de Actions quedan visibles para quien lea el repo. GitHub enmascara
los secretos; el workflow además enmascara el hostname del workspace (sin `https://`) y el container
lo reemplaza por `<WORKSPACE_HOST>` en los tracebacks.

## Correr local
```powershell
docker build -f producers\container_enrichment\Dockerfile -t entity360-enrichment:local producers
$env:USER_AGENT = "entity360 (portfolio) <CONTACT_EMAIL>"
docker run --rm -e USER_AGENT entity360-enrichment:local --solo-leer          # extrae y resume, no empuja
docker run --rm -e USER_AGENT -e DATABRICKS_HOST -e DATABRICKS_TOKEN entity360-enrichment:local   # prueba manual con token de usuario (D4)
```
`--fuentes opensanctions` o `--fuentes wikidata` corre una sola.

## Costo y límites
- Repo privado (GitHub Free): 2.000 minutos de Actions por mes y 500 MB de GHCR sin costo. Una
  corrida diaria usa ~1-2 minutos (~60 por mes) y la imagen pesa decenas de MB; cada push deja una
  versión nueva, así que conviene borrar las viejas sin etiqueta de vez en cuando. Sin medio de pago
  cargado, pasarse del cupo bloquea los workflows, no cobra.
- Si el repo vuelve a ser público: Actions y GHCR pasan a ser gratis sin cupo, pero GitHub
  **desactiva los workflows programados** tras 60 días sin actividad en el repo.
- El cron de Actions no es exacto (puede atrasarse en horas de carga). Para una fuente diaria alcanza.

## Licencias
OpenSanctions **CC BY-NC 4.0** (uso no comercial, atribución obligatoria); Wikidata **CC0**. Ver
`docs/fuentes.md`.
