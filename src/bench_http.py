"""
bench_http.py - Generador de carga HTTP contra POST /predict (cualquier URL).

    python -m src.bench_http --url http://localhost:8000 --modo keepalive --n 300
    python -m src.bench_http --url http://localhost:8001 --modo concurrente --concurrencia 8 --duracion 15

Modos:
  sin_keepalive : una conexión NUEVA por consulta (así mide la prueba L01 de la Etapa 4 con
                  requests.post). En la nube cada consulta paga TCP + TLS completos.
  keepalive     : una sola conexión reutilizada (requests.Session), como un cliente bien configurado.
  concurrente   : N clientes simultáneos, cada uno con su conexión, durante D segundos. Mide el
                  throughput máximo de una réplica y la latencia bajo saturación.

Las consultas son sesiones reales del conjunto de prueba, en orden aleatorio.
"""
import argparse
import threading
import time

import requests

from src.comun import cargas_de_prueba, percentiles


def _una(cliente, url, datos):
    inicio = time.perf_counter()
    try:
        r = cliente.post(f"{url}/predict", json=datos, timeout=10)
        ok = r.status_code == 200
    except requests.RequestException:
        ok = False
    return (time.perf_counter() - inicio) * 1000, ok


def secuencial(url, cargas, n, keepalive=True, calentamiento=20):
    sesion = requests.Session() if keepalive else None
    tiempos, errores = [], 0
    for i in range(calentamiento + n):
        cliente = sesion if keepalive else requests     # requests.post abre conexión nueva cada vez
        t, ok = _una(cliente, url, cargas[i % len(cargas)])
        if i >= calentamiento:
            tiempos.append(t)
            errores += (not ok)
    return {**percentiles(tiempos), "errores": errores, "tasa_errores": round(errores / n, 4)}


def concurrente(url, cargas, concurrencia, duracion_s, calentamiento_s=2):
    tiempos, errores = [], [0]
    candado = threading.Lock()
    fin_calentamiento = time.perf_counter() + calentamiento_s
    fin = fin_calentamiento + duracion_s

    def trabajador(k):
        sesion = requests.Session()
        i = k
        while True:
            ahora = time.perf_counter()
            if ahora >= fin:
                break
            t, ok = _una(sesion, url, cargas[i % len(cargas)])
            i += concurrencia
            if ahora >= fin_calentamiento:
                with candado:
                    tiempos.append(t)
                    errores[0] += (not ok)

    hilos = [threading.Thread(target=trabajador, args=(k,)) for k in range(concurrencia)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    n = len(tiempos)
    return {**percentiles(tiempos), "concurrencia": concurrencia, "duracion_s": duracion_s,
            "throughput_rps": round(n / duracion_s, 1), "errores": errores[0],
            "tasa_errores": round(errores[0] / max(n, 1), 4)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--modo", choices=["sin_keepalive", "keepalive", "concurrente"], default="keepalive")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--concurrencia", type=int, default=8)
    ap.add_argument("--duracion", type=float, default=15)
    a = ap.parse_args()
    cargas = cargas_de_prueba(500)
    if a.modo == "concurrente":
        print(concurrente(a.url, cargas, a.concurrencia, a.duracion))
    else:
        print(secuencial(a.url, cargas, a.n, keepalive=(a.modo == "keepalive")))


if __name__ == "__main__":
    main()
