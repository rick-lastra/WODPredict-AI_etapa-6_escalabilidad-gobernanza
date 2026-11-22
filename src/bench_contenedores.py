"""
bench_contenedores.py - Antes vs después con los CONTENEDORES reales y límites de CPU/memoria de Azure.

    python -m src.bench_contenedores                       # completo (≈ 15 min)
    python -m src.bench_contenedores --rapido              # solo el perfil 0.5 vCPU (≈ 4 min)

Qué hace (requiere Docker Desktop abierto):
  1. Construye la imagen ACTUAL desde el repositorio de la Etapa 4 SIN modificarlo
     (lo clona en externos/ si no existe) y la imagen OPTIMIZADA desde servicio_optimizado/.
  2. Para cada perfil de réplica de Azure Container Apps (0.25 vCPU/0.5 GiB, 0.5/1, 1/2) arranca cada
     imagen con esos límites (docker run --cpus --memory) y mide:
       - arranque en frío: de `docker run` a la primera respuesta 200 de GET / (3 veces)
       - memoria en reposo (docker stats)
       - latencia secuencial con y sin keep-alive
       - throughput y latencia con 1, 4 y 16 clientes simultáneos
       - CPU consumida por consulta (contador de CPU del cgroup del contenedor)
  3. Guarda resultados/bench_contenedores.json y resultados/bench_contenedores.csv

Es una MEDICIÓN REAL en la computadora local con límites que imitan una réplica de Azure; no es una
medición en Azure (el despliegue de la Etapa 4 está apagado). La red local no incluye la latencia de
internet ni de TLS: eso se discute aparte con el modo sin keep-alive.
"""
import argparse
import csv
import json
import subprocess
import time
import zlib
from pathlib import Path

import requests

from src.bench_http import concurrente, secuencial
from src.comun import RAIZ, cargas_de_prueba, entorno, guardar_json

URL_ETAPA4 = "https://github.com/rick-lastra/WODPredict-AI_etapa-4_API-despliegue.git"
IMAGENES = {"actual": "wodpredict-api:1.0", "optimizado": "wodpredict-api:2.0-onnx"}
PERFILES = [(0.25, "512m"), (0.5, "1g"), (1.0, "2g")]
CONCURRENCIAS = [1, 4, 16]
PUERTO = 8090


def sh(*args, **kw):
    return subprocess.run(list(args), check=True, capture_output=True, text=True, **kw).stdout.strip()


def construir(etapa4: Path):
    if not etapa4.exists():
        print(f"   clonando la Etapa 4 en {etapa4} (solo lectura, no se modifica)")
        sh("git", "clone", "--depth", "1", URL_ETAPA4, str(etapa4))
    commit = sh("git", "-C", str(etapa4), "rev-parse", "HEAD")
    print("   construyendo imagen actual (Dockerfile de la Etapa 4, sin cambios)")
    sh("docker", "build", "-q", "-t", IMAGENES["actual"], str(etapa4))
    print("   construyendo imagen optimizada (servicio_optimizado/Dockerfile)")
    sh("docker", "build", "-q", "-f", str(RAIZ / "servicio_optimizado" / "Dockerfile"), "-t", IMAGENES["optimizado"], str(RAIZ))
    tam = {k: int(sh("docker", "image", "inspect", v, "--format", "{{.Size}}")) for k, v in IMAGENES.items()}
    comprimido = {k: tamano_comprimido(v) for k, v in IMAGENES.items()}
    return commit, tam, comprimido


def tamano_comprimido(imagen):
    """Bytes de la imagen comprimida con gzip: aproxima lo que una réplica nueva descarga del registro."""
    compresor, total = zlib.compressobj(6, zlib.DEFLATED, 31), 0
    with subprocess.Popen(["docker", "save", imagen], stdout=subprocess.PIPE) as proc:
        while bloque := proc.stdout.read(1 << 20):
            total += len(compresor.compress(bloque))
    return total + len(compresor.flush())


def detener(nombre="wodpredict-bench"):
    subprocess.run(["docker", "rm", "-f", nombre], capture_output=True)


def arrancar(imagen, cpus, memoria, nombre="wodpredict-bench"):
    """Arranca el contenedor y devuelve los segundos hasta la primera respuesta 200 de GET /."""
    detener(nombre)
    inicio = time.perf_counter()
    sh("docker", "run", "-d", "--name", nombre, f"--cpus={cpus}", f"--memory={memoria}",
       "-p", f"{PUERTO}:8000", imagen)
    while time.perf_counter() - inicio < 120:
        try:
            if requests.get(f"http://localhost:{PUERTO}/", timeout=1).status_code == 200:
                return time.perf_counter() - inicio
        except requests.RequestException:
            pass
        time.sleep(0.02)
    raise RuntimeError(f"{imagen} no respondió en 120 s")


def cpu_segundos(nombre="wodpredict-bench"):
    """CPU acumulada del contenedor (cgroup v2 o v1), leída desde dentro del contenedor."""
    salida = sh("docker", "exec", nombre, "sh", "-c",
                "cat /sys/fs/cgroup/cpu.stat 2>/dev/null || cat /sys/fs/cgroup/cpuacct/cpuacct.usage")
    if "usage_usec" in salida:
        return int(salida.split("usage_usec")[1].split()[0]) / 1e6
    return int(salida.split()[0]) / 1e9


def memoria_mb(nombre="wodpredict-bench"):
    texto = sh("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", nombre).split("/")[0].strip()
    valor, unidad = float(texto[:-3]), texto[-3:]
    return round(valor * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[unidad], 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--etapa4", default=str(RAIZ / "externos" / "WODPredict-AI_etapa-4_API-despliegue"))
    ap.add_argument("--rapido", action="store_true", help="solo el perfil de 0.5 vCPU / 1 GiB")
    ap.add_argument("--duracion", type=float, default=15, help="segundos por nivel de concurrencia")
    a = ap.parse_args()

    print("1. Construir imágenes")
    commit, tamanos, comprimidos = construir(Path(a.etapa4))
    cargas = cargas_de_prueba(500)
    perfiles = [(0.5, "1g")] if a.rapido else PERFILES
    filas = []

    print("2. Medir cada imagen en cada perfil de réplica")
    for cpus, mem in perfiles:
        for variante, imagen in IMAGENES.items():
            print(f"   {variante} @ {cpus} vCPU / {mem}")
            arranques = [arrancar(imagen, cpus, mem) for _ in range(3)]
            time.sleep(3)
            fila = {"variante": variante, "vcpu": cpus, "memoria": mem,
                    "imagen_mb": round(tamanos[variante] / 1e6, 1),
                    "imagen_comprimida_mb": round(comprimidos[variante] / 1e6, 1),
                    "arranque_frio_s_mediana": round(sorted(arranques)[1], 3),
                    "arranques_s": [round(x, 3) for x in arranques],
                    "memoria_reposo_mb": memoria_mb()}
            fila["sin_keepalive"] = secuencial(f"http://localhost:{PUERTO}", cargas, 300, keepalive=False)
            fila["keepalive"] = secuencial(f"http://localhost:{PUERTO}", cargas, 300, keepalive=True)
            for c in CONCURRENCIAS:
                cpu0 = cpu_segundos()
                r = concurrente(f"http://localhost:{PUERTO}", cargas, c, a.duracion)
                cpu1 = cpu_segundos()
                n = r["n"]
                r["cpu_ms_por_consulta"] = round(1000 * (cpu1 - cpu0) / max(n, 1), 3)  # incluye ~2 s de calentamiento
                fila[f"c{c}"] = r
            fila["memoria_tras_carga_mb"] = memoria_mb()
            detener()
            filas.append(fila)
            print(f"      arranque {fila['arranque_frio_s_mediana']} s | p95 keep-alive {fila['keepalive']['p95_ms']} ms | "
                  f"máx. {max(fila[f'c{c}']['throughput_rps'] for c in CONCURRENCIAS)} rps")

    resultado = {"descripcion": "Contenedor actual (Etapa 4) vs optimizado con límites de réplica de Azure Container Apps",
                 "tipo_medicion": "MEDICIÓN REAL local con docker --cpus/--memory (imita una réplica; NO es Azure)",
                 "commit_etapa4": commit, "imagenes": IMAGENES, "duracion_por_nivel_s": a.duracion,
                 "entorno": entorno(), "docker": sh("docker", "version", "--format", "{{.Server.Version}}"),
                 "resultados": filas}
    guardar_json("bench_contenedores.json", resultado)

    columnas = ["variante", "vcpu", "memoria", "imagen_mb", "imagen_comprimida_mb", "arranque_frio_s_mediana", "memoria_reposo_mb",
                "memoria_tras_carga_mb"]
    with open(RAIZ / "resultados" / "bench_contenedores.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columnas + ["sin_keepalive_p50_ms", "keepalive_p50_ms", "keepalive_p95_ms"]
                   + [f"c{c}_{m}" for c in CONCURRENCIAS for m in ("rps", "p95_ms", "p99_ms", "cpu_ms_por_consulta", "errores")])
        for fila in filas:
            w.writerow([fila[k] for k in columnas]
                       + [fila["sin_keepalive"]["p50_ms"], fila["keepalive"]["p50_ms"], fila["keepalive"]["p95_ms"]]
                       + [fila[f"c{c}"][m] for c in CONCURRENCIAS
                          for m in ("throughput_rps", "p95_ms", "p99_ms", "cpu_ms_por_consulta", "errores")])


if __name__ == "__main__":
    main()
