"""Claves y conexiones locales de Snowflake (fase 9, manual-steps §14). Nada de esto va al repo.

Dos usuarios de servicio, con key pair y sin contraseña:
- ENTITY360_TF: Terraform (infra/snowflake) e integracion.py. Rol ACCOUNTADMIN: crear un resource
  monitor y una catalog integration lo exigen. Lo crea Gastón en Snowsight con el SQL que imprime
  `claves` (lleva solo la clave PÚBLICA).
- ENTITY360_DBT_SVC: dbt (marts). Lo crea Terraform con su clave pública (variable dbt_rsa_public_key):
  una clave pública no es un secreto.

    claves        genera los dos pares en ~/.snowflake/keys (no pisa los que existen), restringe el acceso
                  al usuario de Windows e imprime el SQL de Snowsight y la línea de terraform.tfvars.
    conexiones    con el account identifier (<ORG>-<CUENTA>): perfil `entity360` del provider de
                  Terraform (~/.snowflake/config, lleva la clave privada: el provider no acepta una
                  ruta) y conexión `entity360` del conector de Python (~/.snowflake/connections.toml,
                  con la ruta). No pisa una sección distinta sin --reemplazar.

Las claves privadas no se imprimen nunca y no se cifran con frase: viven en el perfil del usuario con
acceso restringido (icacls), como las credenciales del resto del proyecto en el llavero.

Uso:
    .venv\\Scripts\\python.exe snowflake\\cuenta.py claves
    .venv\\Scripts\\python.exe snowflake\\cuenta.py conexiones --cuenta <ORG>-<CUENTA>
"""

import argparse
import base64
import os
import re
import subprocess
import sys
from pathlib import Path

USUARIOS = {"tf": "ENTITY360_TF", "dbt": "ENTITY360_DBT_SVC"}
PERFIL = "entity360"


def carpeta() -> Path:
    return Path(os.environ.get("SNOWFLAKE_HOME", Path.home() / ".snowflake"))


def ruta_clave(quien: str, base: Path | None = None) -> Path:
    return (base or carpeta()) / "keys" / f"{USUARIOS[quien].lower()}.p8"


def restringir(ruta: Path):
    """Solo el usuario de Windows actual puede leer el archivo (sin herencia)."""
    if os.name == "nt":
        subprocess.run(["icacls", str(ruta), "/inheritance:r", "/grant:r", f"{os.environ['USERNAME']}:F"],
                       capture_output=True, check=True)
    else:
        ruta.chmod(0o600)


def generar(ruta: Path) -> bool:
    """Par RSA 2048 en PKCS#8 sin cifrar. False si ya existía (no se pisa)."""
    if ruta.exists():
        return False
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    restringir(ruta)
    return True


def publica(ruta: Path) -> str:
    """Clave pública en base64 DER, sin encabezados: el formato de RSA_PUBLIC_KEY de Snowflake."""
    from cryptography.hazmat.primitives import serialization
    privada = serialization.load_pem_private_key(ruta.read_bytes(), password=None)
    der = privada.public_key().public_bytes(serialization.Encoding.DER,
                                            serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode()


def sql_bootstrap(publica_tf: str) -> str:
    return (f"USE ROLE ACCOUNTADMIN;\n"
            f"CREATE USER IF NOT EXISTS {USUARIOS['tf']}\n"
            f"  TYPE = SERVICE\n"
            f"  DEFAULT_ROLE = ACCOUNTADMIN\n"
            f"  RSA_PUBLIC_KEY = '{publica_tf}'\n"
            f"  COMMENT = 'entity360: Terraform (infra/snowflake) y snowflake/integracion.py. Key pair, sin contraseña.';\n"
            f"GRANT ROLE ACCOUNTADMIN TO USER {USUARIOS['tf']};\n"
            f"-- Verificación: DESC USER {USUARIOS['tf']};  (RSA_PUBLIC_KEY_FP con valor, HAS_PASSWORD = false)\n")


def cuenta_valida(cuenta: str) -> tuple[str, str]:
    m = re.fullmatch(r"([A-Za-z0-9_]+)-([A-Za-z0-9_]+)", cuenta.strip())
    if not m:
        raise SystemExit("la cuenta va como <ORG>-<CUENTA> (Snowsight: Admin > Accounts, o el account identifier)")
    return m.group(1).upper(), m.group(2).upper()


def seccion_config(cuenta: str, privada_pem: str) -> str:
    org, cta = cuenta_valida(cuenta)
    return (f"[{PERFIL}]\n"
            f"organization_name = '{org}'\n"
            f"account_name = '{cta}'\n"
            f"user = '{USUARIOS['tf']}'\n"
            f"role = 'ACCOUNTADMIN'\n"
            f"authenticator = 'SNOWFLAKE_JWT'\n"
            f"private_key = '''\n{privada_pem.strip()}\n'''\n")


def seccion_conexion(cuenta: str, ruta: Path) -> str:
    cuenta_valida(cuenta)
    return (f"[{PERFIL}]\n"
            f"account = \"{cuenta.strip().upper()}\"\n"
            f"user = \"{USUARIOS['tf']}\"\n"
            f"role = \"ACCOUNTADMIN\"\n"
            f"warehouse = \"ENTITY360_WH\"\n"
            f"authenticator = \"SNOWFLAKE_JWT\"\n"
            f"private_key_file = \"{ruta.as_posix()}\"\n")


def secciones(texto: str) -> dict[str, str]:
    """[nombre] -> texto de la sección, respetando strings de varias líneas ('''...''')."""
    out, actual, dentro = {}, None, False
    for linea in texto.splitlines(keepends=True):
        if not dentro and re.match(r"^\[[^\]]+\]\s*$", linea):
            actual = linea.strip()[1:-1]
            out[actual] = ""
        if actual is not None:
            out[actual] += linea
        if linea.count("'''") % 2 == 1:
            dentro = not dentro
    return out


def escribir_seccion(archivo: Path, nombre: str, contenido: str, reemplazar: bool) -> str:
    """Agrega la sección si falta; si existe igual, nada; si existe distinta, solo con reemplazar."""
    archivo.parent.mkdir(parents=True, exist_ok=True)
    texto = archivo.read_text(encoding="utf-8") if archivo.exists() else ""
    actuales = secciones(texto)
    if nombre in actuales:
        if actuales[nombre].strip() == contenido.strip():
            return "sin cambios"
        if not reemplazar:
            raise SystemExit(f"{archivo} ya tiene [{nombre}] con otro contenido: revisar a mano o --reemplazar")
        texto = texto.replace(actuales[nombre], "")
    texto = (texto.rstrip() + "\n\n" if texto.strip() else "") + contenido
    archivo.write_text(texto, encoding="utf-8")
    restringir(archivo)
    return "reemplazada" if nombre in actuales else "agregada"


def claves() -> int:
    for quien in USUARIOS:
        r = ruta_clave(quien)
        print(f"{USUARIOS[quien]}: {'clave generada' if generar(r) else 'ya existía, no se pisa'} ({r})")
    print("\n-- 1) Snowsight, hoja SQL nueva, con ACCOUNTADMIN (solo la clave PÚBLICA de Terraform):\n")
    print(sql_bootstrap(publica(ruta_clave("tf"))))
    print("-- 2) infra/snowflake/terraform.tfvars (clave PÚBLICA del usuario de dbt; no es un secreto):\n")
    print(f'dbt_rsa_public_key = "{publica(ruta_clave("dbt"))}"')
    return 0


def conexiones(cuenta: str, reemplazar: bool) -> int:
    tf = ruta_clave("tf")
    if not tf.exists():
        raise SystemExit("primero `claves`")
    r1 = escribir_seccion(carpeta() / "config", PERFIL, seccion_config(cuenta, tf.read_text(encoding="utf-8")), reemplazar)
    r2 = escribir_seccion(carpeta() / "connections.toml", PERFIL, seccion_conexion(cuenta, tf), reemplazar)
    print(f"~/.snowflake/config [{PERFIL}] (Terraform): {r1}")
    print(f"~/.snowflake/connections.toml [{PERFIL}] (integracion.py): {r2}")
    print("dbt: $env:SNOWFLAKE_ACCOUNT, $env:SNOWFLAKE_USER = 'ENTITY360_DBT_SVC' y "
          f"$env:SNOWFLAKE_PRIVATE_KEY_PATH = '{ruta_clave('dbt').as_posix()}'")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="accion", required=True)
    sub.add_parser("claves")
    c = sub.add_parser("conexiones")
    c.add_argument("--cuenta", required=True)
    c.add_argument("--reemplazar", action="store_true")
    a = ap.parse_args()
    return claves() if a.accion == "claves" else conexiones(a.cuenta, a.reemplazar)


if __name__ == "__main__":
    sys.exit(main())
