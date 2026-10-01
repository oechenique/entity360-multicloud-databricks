"""Mensajes de cierre de la corrida (bloque E, 2026-10-01): uno por corrida, por Telegram (contracts/alertas.py).

- `resultado` (la hoja, none_failed) manda el de éxito: si corre, no falló nada.
- El on_failure_callback del DAG manda el de falla: `resultado` queda upstream_failed y no corre. Las
  alertas por tarea (al_fallar, al_saltear) siguen como estaban.
Sin token en el llavero (servicio entity360-telegram), alertas.enviar escribe en stderr y sigue.
"""
from datetime import datetime, timezone


def duracion(inicio: datetime | None, fin: datetime) -> str:
    if inicio is None:
        return "-"
    minutos = int((fin - inicio).total_seconds() // 60)
    return f"{minutos // 60} h {minutos % 60:02d} min" if minutos >= 60 else f"{minutos} min"


def mensaje(estado: str, dag_id: str, run_id: str, inicio: datetime | None,
            fallidas: list[str] | None = None, ahora: datetime | None = None) -> tuple[str, str]:
    """(título, texto). estado: 'ok' o 'falla'."""
    ahora = ahora or datetime.now(timezone.utc)
    if estado == "ok":
        titulo = "entity360: corrida OK"
        detalle = "Gold, frescura y Snowflake (refresco, grants, marts y tests) en verde."
    else:
        titulo = "entity360: corrida FALLIDA"
        detalle = "Fallaron: " + (", ".join(sorted(fallidas)) if fallidas else "ver la UI de Airflow")
    return titulo, f"DAG {dag_id}, corrida {run_id} ({duracion(inicio, ahora)}).\n{detalle}"
