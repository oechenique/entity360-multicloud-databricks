"""Lambda de entrega (regla 05): S3 -> UC Volume de Databricks.

Disparada por la creación de un _manifest_<ts>.json en lotes/ (notificación de S3). Separar
extracción y entrega hace que cada una se pueda reintentar sola.

1. Lee el manifest y el archivo de datos del bucket; verifica el sha256.
2. Pide un token OAuth M2M del SP entity360-producer (credenciales en Secrets Manager).
3. PUT del archivo de datos y DESPUÉS del manifest al volume, con el contrato de landing.
   Si el archivo ya existe en el volume (reintento), lo relee y compara el sha256: si coincide,
   sigue (idempotente); si no, falla.

Los errores se propagan: Lambda reintenta y, agotados los reintentos, el evento va a la DLQ (SQS).

Variables de entorno: SECRET_ID, VOLUME_ROOT.
"""

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import boto3

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")


def http(metodo: str, url: str, headers: dict, cuerpo: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=cuerpo, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def token(cred: dict) -> str:
    import base64
    basico = base64.b64encode(f"{cred['client_id']}:{cred['client_secret']}".encode()).decode()
    estado, cuerpo = http("POST", f"{cred['host'].rstrip('/')}/oidc/v1/token",
                          {"Authorization": f"Basic {basico}", "Content-Type": "application/x-www-form-urlencoded"},
                          urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "all-apis"}).encode())
    if estado != 200:
        raise RuntimeError(f"token OAuth M2M: HTTP {estado} {cuerpo[:200]!r}")
    return json.loads(cuerpo)["access_token"]


def subir(host: str, tk: str, ruta: str, contenido: bytes) -> str:
    url = f"{host}/api/2.0/fs/files{urllib.parse.quote(ruta)}?overwrite=false"
    estado, cuerpo = http("PUT", url, {"Authorization": f"Bearer {tk}", "Content-Type": "application/octet-stream"},
                          contenido)
    if estado in (200, 201, 204):
        return "subido"
    if estado == 409:  # ya existe: reintento de una entrega anterior
        e2, actual = http("GET", f"{host}/api/2.0/fs/files{urllib.parse.quote(ruta)}", {"Authorization": f"Bearer {tk}"})
        if e2 == 200 and hashlib.sha256(actual).digest() == hashlib.sha256(contenido).digest():
            return "ya estaba (mismo sha256)"
        raise RuntimeError(f"{ruta} ya existe en el volume con otro contenido")
    raise RuntimeError(f"PUT {ruta}: HTTP {estado} {cuerpo[:300]!r}")


def lambda_handler(event, context):
    cred = json.loads(secrets.get_secret_value(SecretId=os.environ["SECRET_ID"])["SecretString"])
    host = cred["host"].rstrip("/")
    tk = token(cred)
    resultados = []
    for rec in event["Records"]:
        bucket = rec["s3"]["bucket"]["name"]
        clave_manifest = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
        carpeta = clave_manifest.rsplit("/", 1)[0]                       # lotes/ingest_date=YYYY-MM-DD
        manifest_bytes = s3.get_object(Bucket=bucket, Key=clave_manifest)["Body"].read()
        manifest = json.loads(manifest_bytes)
        datos = s3.get_object(Bucket=bucket, Key=f"{carpeta}/{manifest['archivo']}")["Body"].read()
        if hashlib.sha256(datos).hexdigest() != manifest["sha256"]:
            raise RuntimeError(f"sha256 no coincide para {manifest['archivo']}")

        destino = f"{os.environ['VOLUME_ROOT']}/{manifest['fuente']}/{carpeta.rsplit('/', 1)[1]}"
        r_datos = subir(host, tk, f"{destino}/{manifest['archivo']}", datos)                    # 1. datos
        r_man = subir(host, tk, f"{destino}/{clave_manifest.rsplit('/', 1)[1]}", manifest_bytes)  # 2. manifest
        resultados.append({"lote": manifest["archivo"], "registros": manifest["registros"],
                           "datos": r_datos, "manifest": r_man, "destino": destino})
    print(json.dumps(resultados, ensure_ascii=False))
    return resultados
