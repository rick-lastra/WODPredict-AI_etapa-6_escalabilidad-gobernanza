"""
exportar_onnx.py - Palanca 1: convierte el modelo v1.0.0 de la Etapa 4 a ONNX y valida la calidad.

    python -m src.exportar_onnx

1. Carga modelo/model.pkl (copia byte a byte del artefacto de la Etapa 4; ver modelo/ORIGEN.md).
2. Convierte el Pipeline completo (imputación + escalado + One-Hot + regresión logística) a ONNX
   con skl2onnx. El grafo ONNX hace exactamente las mismas operaciones; solo cambia el motor que
   las ejecuta (onnxruntime en lugar de pandas + scikit-learn).
3. Restricción de calidad (config/restricciones.yaml): compara probabilidades y decisiones en las
   16,498 sesiones de prueba. Si no cumple, el script termina con error y el modelo ONNX no se usa.

Sobre la cuantización (quantization): se evaluó y se DESCARTA. El modelo tiene 26 coeficientes;
cuantizar a INT8 no reduce latencia ni memoria de forma medible y sí arriesga cambiar decisiones
cerca del umbral 0.17. El archivo ONNX ya pesa ≈ 2 KB.
"""
import time

import joblib
import numpy as np
import onnx
import onnxruntime as ort
import yaml
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType, StringTensorType
from sklearn.metrics import recall_score, precision_score, roc_auc_score

from src.comun import (CARPETA_CONFIG, CARPETA_MODELO, CATEGORICAS, ETIQUETA, NUMERICAS, UMBRAL, VARIABLES,
                       conjunto_prueba, entorno, guardar_json, sha256)

RUTA_PKL = CARPETA_MODELO / "model.pkl"
RUTA_ONNX = CARPETA_MODELO / "model.onnx"


def entradas_onnx(df):
    """DataFrame -> diccionario de entradas del grafo ONNX (una columna por entrada)."""
    entradas = {c: df[[c]].to_numpy(dtype=np.float32) for c in NUMERICAS}
    entradas.update({c: df[[c]].astype(str).to_numpy(dtype=object) for c in CATEGORICAS})
    return entradas


def convertir(modelo):
    tipos = [(c, FloatTensorType([None, 1])) for c in NUMERICAS] + [(c, StringTensorType([None, 1])) for c in CATEGORICAS]
    onx = convert_sklearn(modelo, initial_types=tipos, target_opset={"": 17, "ai.onnx.ml": 3},
                          options={id(modelo): {"zipmap": False}})
    onx.doc_string = "WODPredict-AI v1.0.0 (Etapa 4) convertido con skl2onnx - Etapa 6"
    onnx.checker.check_model(onx)
    RUTA_ONNX.write_bytes(onx.SerializeToString())
    return onx


def main():
    print("1. Cargar el modelo de la Etapa 4")
    modelo = joblib.load(RUTA_PKL)
    print("2. Convertir a ONNX")
    convertir(modelo)
    sesion = ort.InferenceSession(str(RUTA_ONNX), providers=["CPUExecutionProvider"])

    print("3. Validar la restricción de calidad en el conjunto de prueba")
    prueba = conjunto_prueba()
    X, y = prueba[VARIABLES], prueba[ETIQUETA].to_numpy()
    p_sk = modelo.predict_proba(X)[:, 1]
    p_onnx = sesion.run(["probabilities"], entradas_onnx(X))[0][:, 1]

    dif = np.abs(p_sk - p_onnx)
    d_sk, d_onnx = (p_sk >= UMBRAL).astype(int), (p_onnx >= UMBRAL).astype(int)
    # La sesión más cercana al umbral indica cuánto margen hay antes de que una diferencia cambie una decisión.
    margen_umbral = float(np.min(np.abs(p_sk - UMBRAL)))

    def metricas(p, d):
        return {"recall": round(recall_score(y, d), 4), "precision": round(precision_score(y, d), 4),
                "roc_auc": round(roc_auc_score(y, p), 4), "alertas": int(d.sum())}

    restr = yaml.safe_load((CARPETA_CONFIG / "restricciones.yaml").read_text(encoding="utf-8"))["calidad"]
    m_onnx = metricas(p_onnx, d_onnx)
    cumple = (dif.max() <= restr["max_diferencia_probabilidad"]
              and int((d_sk != d_onnx).sum()) <= restr["decisiones_distintas_max"]
              and m_onnx["recall"] >= restr["recall_minimo"])
    resultado = {
        "descripcion": "Equivalencia del modelo ONNX contra el modelo scikit-learn v1.0.0 (Etapa 4)",
        "datos": "Conjunto de prueba: 20 % de atletas (GroupShuffleSplit, semilla 42), dataset sintético wodpredict-synth@v1.0",
        "sesiones_prueba": int(len(y)),
        "atletas_prueba": int(prueba["athlete_id"].nunique()),
        "diferencia_probabilidad": {"max": float(dif.max()), "media": float(dif.mean())},
        "margen_minimo_al_umbral": margen_umbral,
        "decisiones_distintas": int((d_sk != d_onnx).sum()),
        "metricas_sklearn": metricas(p_sk, d_sk),
        "metricas_onnx": m_onnx,
        "restriccion": restr,
        "cumple_restriccion_calidad": bool(cumple),
        "artefactos": {"model.pkl": {"bytes": RUTA_PKL.stat().st_size, "sha256": sha256(RUTA_PKL)},
                       "model.onnx": {"bytes": RUTA_ONNX.stat().st_size, "sha256": sha256(RUTA_ONNX)}},
        "versiones": {"onnxruntime": ort.__version__, "onnx": onnx.__version__,
                      "skl2onnx": __import__("skl2onnx").__version__, "scikit-learn": __import__("sklearn").__version__},
        "entorno": entorno(),
    }
    print(f"   diferencia máx. {dif.max():.2e} | decisiones distintas {resultado['decisiones_distintas']} | "
          f"recall {m_onnx['recall']} | cumple: {cumple}")
    guardar_json("calidad_onnx.json", resultado)
    if not cumple:
        raise SystemExit("El modelo ONNX NO cumple la restricción de calidad: no se debe usar.")


if __name__ == "__main__":
    main()
