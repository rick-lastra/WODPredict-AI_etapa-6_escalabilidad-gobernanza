"""
bench_inferencia.py - Mide el costo de la INFERENCIA dentro del proceso (sin red ni HTTP).

    python -m src.bench_inferencia

Compara el camino de la Etapa 4 (JSON -> DataFrame de pandas -> Pipeline de scikit-learn) contra el
camino optimizado (JSON -> arreglos de numpy -> ONNX Runtime) con 500 consultas reales del conjunto
de prueba. También mide lo que pesa cada motor al ARRANCAR (tiempo de import + carga del modelo y
memoria), que es lo que paga cada arranque en frío de una réplica.

Además deja la evidencia para DESCARTAR dos palancas:
  - Caché de predicciones: qué fracción de consultas se repite exactamente en el flujo de prueba.
  - Batching: cuánto baja el costo por consulta al agrupar, frente a cuánto habría que esperar para
    juntar un lote con la carga real de 288 consultas por hora (una cada 12.5 s).
"""
import json
import subprocess
import sys
import time

import joblib
import numpy as np
import onnxruntime as ort
import pandas as pd

from src.comun import (CARPETA_MODELO, CATEGORICAS, NUMERICAS, VARIABLES, cargas_de_prueba, conjunto_prueba,
                       entorno, guardar_json, percentiles)

REPETICIONES = 3        # cada consulta se evalúa 3 veces -> 1,500 mediciones por camino
CALENTAMIENTO = 100

# --- Camino ACTUAL: idéntico a src/app.py de la Etapa 4 -------------------------------------------
modelo_sk = joblib.load(CARPETA_MODELO / "model.pkl")


def predecir_actual(datos):
    fila = pd.DataFrame([datos])[VARIABLES]
    fila[NUMERICAS] = fila[NUMERICAS].astype(float)
    return float(modelo_sk.predict_proba(fila)[0, 1])


# --- Camino OPTIMIZADO: idéntico a servicio_optimizado/app.py --------------------------------------
opciones = ort.SessionOptions()
opciones.intra_op_num_threads = 1
opciones.inter_op_num_threads = 1
sesion = ort.InferenceSession(str(CARPETA_MODELO / "model.onnx"), sess_options=opciones,
                              providers=["CPUExecutionProvider"])


def entradas(lote):
    e = {c: np.array([[np.nan if d[c] is None else d[c]] for d in lote], dtype=np.float32) for c in NUMERICAS}
    e.update({c: np.array([[d[c]] for d in lote], dtype=object) for c in CATEGORICAS})
    return e


def predecir_onnx(datos):
    return float(sesion.run(["probabilities"], entradas([datos]))[0][0, 1])


def cronometrar(funcion, cargas):
    for d in cargas[:CALENTAMIENTO]:
        funcion(d)
    tiempos = []
    for _ in range(REPETICIONES):
        for d in cargas:
            inicio = time.perf_counter()
            funcion(d)
            tiempos.append((time.perf_counter() - inicio) * 1000)
    return tiempos


ARRANQUE = {
    "actual (pandas + scikit-learn)": (
        "import time,json,psutil;t=time.perf_counter();import pandas,joblib,sklearn;"
        "m=joblib.load(r'{m}/model.pkl');"
        "print(json.dumps({{'s':time.perf_counter()-t,'rss_mb':psutil.Process().memory_info().rss/2**20}}))"),
    "optimizado (onnxruntime)": (
        "import time,json,psutil;t=time.perf_counter();import numpy,onnxruntime as ort;"
        "s=ort.InferenceSession(r'{m}/model.onnx',providers=['CPUExecutionProvider']);"
        "print(json.dumps({{'s':time.perf_counter()-t,'rss_mb':psutil.Process().memory_info().rss/2**20}}))"),
}


def medir_arranque(veces=5):
    """Tiempo de import + carga del modelo y memoria residente, en un proceso nuevo cada vez."""
    salida = {}
    for nombre, codigo in ARRANQUE.items():
        corridas = [json.loads(subprocess.check_output([sys.executable, "-c", codigo.format(m=CARPETA_MODELO)]))
                    for _ in range(veces)]
        salida[nombre] = {"import_y_carga_s_mediana": round(float(np.median([c["s"] for c in corridas])), 3),
                          "memoria_rss_mb_mediana": round(float(np.median([c["rss_mb"] for c in corridas])), 1),
                          "corridas": veces}
    return salida


def main():
    print("1. Cargar 500 consultas reales del conjunto de prueba")
    cargas = cargas_de_prueba(500)
    # Las dos rutas deben dar la misma probabilidad (control de que se mide lo mismo)
    dif = max(abs(predecir_actual(d) - predecir_onnx(d)) for d in cargas)

    print("2. Latencia de inferencia por consulta (en proceso)")
    t_act, t_onx = cronometrar(predecir_actual, cargas), cronometrar(predecir_onnx, cargas)
    p_act, p_onx = percentiles(t_act), percentiles(t_onx)
    print(f"   actual p50 {p_act['p50_ms']} ms | optimizado p50 {p_onx['p50_ms']} ms")

    print("3. Arranque del motor (proceso nuevo, 5 veces)")
    arranque = medir_arranque()

    print("4. Evidencia para descartar batching")
    lotes = {}
    for tam in (1, 8, 32, 128):
        lote = cargas[:tam]
        t = []
        for _ in range(200):
            inicio = time.perf_counter()
            sesion.run(["probabilities"], entradas(lote))
            t.append((time.perf_counter() - inicio) * 1000)
        lotes[str(tam)] = {"ms_por_lote_p50": round(float(np.median(t)), 4),
                           "ms_por_consulta_p50": round(float(np.median(t)) / tam, 4),
                           "espera_para_juntar_lote_s (288 consultas/h)": round((tam - 1) * 3600 / 288, 1)}

    print("5. Evidencia para descartar caché")
    prueba = conjunto_prueba()
    repetidas = prueba[VARIABLES].astype(str).duplicated().mean()

    resultado = {
        "descripcion": "Inferencia en proceso: Etapa 4 (pandas + scikit-learn) contra ONNX Runtime",
        "tipo_medicion": "MEDICIÓN REAL en el equipo indicado en 'entorno' (no simulada)",
        "datos": "500 consultas reales del conjunto de prueba (dataset sintético wodpredict-synth@v1.0)",
        "control_misma_probabilidad_max_dif": dif,
        "latencia_inferencia": {"actual": p_act, "optimizado": p_onx,
                                "reduccion_p50_pct": round(100 * (1 - p_onx["p50_ms"] / p_act["p50_ms"]), 1)},
        "arranque_motor": arranque,
        "batching_onnx": lotes,
        "cache": {"sesiones_prueba": int(len(prueba)),
                  "fraccion_consultas_repetidas_exactas": round(float(repetidas), 5),
                  "conclusion": (f"{100 * repetidas:.2f} % de las consultas se repite exactamente (cada sesión "
                                 "combina cargas, ACWR y días distintos): un caché de predicciones casi no tendría "
                                 "aciertos y solo agregaría memoria e invalidación al cambiar de modelo.")},
        "entorno": entorno(),
        "versiones": {"pandas": pd.__version__, "scikit-learn": __import__("sklearn").__version__,
                      "onnxruntime": ort.__version__, "numpy": np.__version__},
    }
    guardar_json("bench_inferencia.json", resultado)


if __name__ == "__main__":
    main()
