"""Los scripts que corre spark_python_task no pueden usar __file__.

En serverless la tarea no importa el script: lo ejecuta con exec(compile(...)), y __file__ no existe
(NameError en la primera corrida de `resolucion`, 2026-09-27). Los módulos importados (comun.py) sí
lo tienen: la ruta del código sale de ahí.

Se revisa el script entero, no solo el nivel de módulo: una función que se llama desde main() falla
igual. Los scripts de tarea salen de infra/databricks/medallion.tf, así una tarea nueva queda cubierta.
"""

import ast
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
TF = RAIZ / "infra" / "databricks" / "medallion.tf"
CODIGO = RAIZ / "databricks" / "medallion"


def scripts_de_tarea() -> list[str]:
    tf = TF.read_text(encoding="utf-8")
    bloques = re.findall(r"spark_python_task\s*\{(.*?)\}", tf, re.S)
    return sorted({m for b in bloques for m in re.findall(r'databricks_workspace_file\.medallion\["([^"]+)"\]', b)})


def test_el_tf_declara_las_tareas():
    assert scripts_de_tarea() == ["bronze.py", "resolucion.py", "silver.py"]


@pytest.mark.parametrize("script", scripts_de_tarea())
def test_script_de_tarea_sin_dunder_file(script):
    arbol = ast.parse((CODIGO / script).read_text(encoding="utf-8"))
    usos = [n.lineno for n in ast.walk(arbol) if isinstance(n, ast.Name) and n.id == "__file__"]
    assert not usos, f"{script} usa __file__ en las líneas {usos}: usar Path(comun.__file__)"
