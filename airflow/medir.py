"""Mide CPU y memoria de los containers de Airflow y del legacy con `docker stats` (fase 8, aligerar).

Toma una muestra cada --cada segundos y la agrega al CSV (tiempo, container, cpu %, memoria MiB) en el
momento: si el proceso se corta, lo medido queda. Suma en cada muestra la memoria libre de Windows
(fila `windows-libre`). Termina a los --minutos o, con --run-id, cuando esa corrida del DAG llega a
success o failed. Al final (o con --resumir sobre un CSV existente) imprime CPU media y máxima y memoria
máxima por container, y el total del stack. La CPU es la de docker: 100 % = un núcleo lógico.

Uso: python airflow\\medir.py --minutos 90 --run-id manual__... --salida airflow\\evidencia\\corrida-liviano.csv
     python airflow\\medir.py --resumir --salida airflow\\evidencia\\corrida-liviano.csv
"""

import argparse
import csv
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone

UNIDADES = {"B": 1 / 2**20, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1e3 / 2**20, "MB": 1e6 / 2**20,
            "GB": 1e9 / 2**20}


def mib(texto: str) -> float:
    n, u = re.match(r"([\d.]+)\s*([A-Za-z]+)", texto.strip()).groups()
    return float(n) * UNIDADES[u]


def muestra() -> list[tuple[str, float, float]]:
    out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}};{{.CPUPerc}};{{.MemUsage}}"],
                         capture_output=True, text=True, check=True).stdout
    filas = []
    for l in out.strip().splitlines():
        nombre, cpu, mem = l.split(";")
        if nombre.startswith("entity360"):
            filas.append((nombre.removeprefix("entity360-airflow-").removesuffix("-1"),
                          float(cpu.rstrip("%")), mib(mem.split("/")[0])))
    return filas


def libre_windows_mib() -> float:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
                         capture_output=True, text=True).stdout.strip()
    return float(out) / 1024 if out else float("nan")


def estado_corrida(run_id: str) -> str | None:
    out = subprocess.run(["docker", "exec", "entity360-airflow-airflow-scheduler-1", "airflow", "dags", "list-runs",
                          "entity360_convergencia", "-o", "plain"], capture_output=True, text=True).stdout
    for l in out.splitlines():
        partes = l.split()
        if len(partes) > 2 and partes[1] == run_id:
            return partes[2]
    return None


def resumir(ruta: str):
    with open(ruta, encoding="utf-8") as f:
        datos = [(r["utc"], r["container"], float(r["cpu_pct"]), float(r["mem_mib"])) for r in csv.DictReader(f)]
    libre = [m for _, n, _, m in datos if n == "windows-libre"]
    datos = [d for d in datos if d[1] != "windows-libre"]
    por = defaultdict(list)
    tot = defaultdict(lambda: [0.0, 0.0])
    for t, n, c, m in datos:
        por[n].append((c, m))
        tot[t][0] += c
        tot[t][1] += m
    print(f"{'container':28s} {'cpu media':>9s} {'cpu max':>8s} {'mem max MiB':>12s}")
    for n, v in sorted(por.items()):
        print(f"{n:28s} {sum(c for c, _ in v) / len(v):9.1f} {max(c for c, _ in v):8.1f} {max(m for _, m in v):12.0f}")
    t = list(tot.values())
    print(f"{'TOTAL (por muestra)':28s} {sum(c for c, _ in t) / len(t):9.1f} {max(c for c, _ in t):8.1f} "
          f"{max(m for _, m in t):12.0f}   ({len(t)} muestras, {datos[0][0]} a {datos[-1][0]})")
    if libre:
        print(f"memoria libre de Windows: mínima {min(libre):.0f} MiB, media {sum(libre) / len(libre):.0f} MiB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutos", type=float, default=5)
    ap.add_argument("--cada", type=float, default=10)
    ap.add_argument("--run-id")
    ap.add_argument("--resumir", action="store_true")
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()
    if not a.resumir:
        fin, ultimo_chequeo = time.time() + a.minutos * 60, 0.0
        with open(a.salida, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["utc", "container", "cpu_pct", "mem_mib"])
            while time.time() < fin:
                t = datetime.now(timezone.utc).isoformat(timespec="seconds")
                w.writerows((t, *m) for m in muestra())
                w.writerow((t, "windows-libre", 0, round(libre_windows_mib(), 1)))
                f.flush()
                if a.run_id and time.time() - ultimo_chequeo > 60:
                    ultimo_chequeo = time.time()
                    estado = estado_corrida(a.run_id)
                    if estado in ("success", "failed"):
                        print(f"corrida {a.run_id}: {estado}")
                        break
                time.sleep(a.cada)
    resumir(a.salida)


if __name__ == "__main__":
    main()
