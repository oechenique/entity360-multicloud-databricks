"""Alertas de la plataforma (regla 09): fallos críticos de contratos y fuentes atrasadas.

Canal: Telegram (un bot y un chat), porque es un POST HTTP sin servidor de correo ni contraseñas de
SMTP. Credenciales en variables de entorno (en Airflow, en su archivo .env, fuera de git):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Sin credenciales, la alerta se escribe en stderr y el proceso sigue: una alerta que no sale no frena
la plataforma (se ve en el log de la tarea).
"""

import json
import os
import sys
import urllib.request


def enviar(titulo: str, texto: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    mensaje = f"{titulo}\n{texto}"
    if not token or not chat:
        print(f"[alerta sin canal configurado] {mensaje}", file=sys.stderr)
        return False
    datos = json.dumps({"chat_id": chat, "text": mensaje[:4000]}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=datos,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except OSError as e:     # sin red o token inválido: se registra y se sigue
        print(f"[alerta no enviada: {type(e).__name__}] {mensaje}", file=sys.stderr)
        return False
