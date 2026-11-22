"""
app.py - API OPTIMIZADA de WODPredict-AI (Etapa 6).

Mismo contrato que la API de la Etapa 4 (mismos endpoints, mismas validaciones y la misma
respuesta), con un solo cambio de fondo: la inferencia corre en ONNX Runtime en lugar de
pandas + scikit-learn. Así la imagen ya no instala pandas, scipy ni scikit-learn (palanca 2) y cada
consulta usa menos CPU (palanca 1). El modelo es el mismo v1.0.0 (ver resultados/calidad_onnx.json).

    uvicorn app:app --port 8001          (desde la carpeta servicio_optimizado/)

La Etapa 4 NO se modifica: sigue siendo el "sistema actual" contra el que se compara.
"""
import json
import os
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. Cargar el modelo ONNX y su ficha UNA sola vez al iniciar
# ---------------------------------------------------------------------------
CARPETA = Path(__file__).resolve().parent
CARPETA_MODELO = Path(os.environ.get("CARPETA_MODELO", CARPETA / "modelo"))
metadata = json.loads((CARPETA_MODELO / "metadata.json").read_text(encoding="utf-8"))
UMBRAL = metadata["umbral"]
NUMERICAS = metadata["variables_numericas"]
CATEGORICAS = metadata["variables_categoricas"]

opciones = ort.SessionOptions()
# Un hilo por consulta: el modelo es diminuto y en una réplica de 0.25 a 0.5 vCPU más hilos solo
# compiten por la misma CPU. La concurrencia se obtiene con más réplicas (escalado horizontal).
opciones.intra_op_num_threads = 1
opciones.inter_op_num_threads = 1
sesion = ort.InferenceSession(str(CARPETA_MODELO / "model.onnx"), sess_options=opciones,
                              providers=["CPUExecutionProvider"])
SALIDA = ["probabilities"]


# ---------------------------------------------------------------------------
# 2. Contrato de entrada (copiado sin cambios de la Etapa 4)
# ---------------------------------------------------------------------------
class DatosAtleta(BaseModel):
    level: Literal["novato", "intermedio", "élite"] = Field(description="Nivel del atleta")
    sex: Literal["F", "M"] = Field(description="Sexo")
    language: Literal["es", "en"] = Field(description="Idioma de sus comentarios")
    age: Optional[float] = Field(None, ge=16, le=80, description="Edad en años")
    days_since_first_session: int = Field(ge=0, le=3650, description="Días desde su primera sesión")
    days_since_prev_session: int = Field(ge=1, le=365, description="Días desde la sesión anterior")
    sessions_last_3d: int = Field(ge=0, le=3, description="Sesiones en los últimos 3 días")
    sessions_last_7d: int = Field(ge=0, le=7, description="Sesiones en los últimos 7 días")
    sessions_last_28d: int = Field(ge=0, le=28, description="Sesiones en los últimos 28 días")
    load_last_3d: float = Field(ge=0, le=10000, description="Carga de los últimos 3 días")
    load_last_7d: float = Field(ge=0, le=20000, description="Carga de los últimos 7 días")
    mean_session_load_28d: Optional[float] = Field(None, ge=0, le=5000, description="Carga promedio por sesión en 28 días")
    acwr3_freq: Optional[float] = Field(None, ge=0, le=4, description="ACWR de frecuencia (3 días)")
    acwr3_load: Optional[float] = Field(None, ge=0, le=4, description="ACWR de carga (3 días)")
    acwr_freq: Optional[float] = Field(None, ge=0, le=4, description="ACWR de frecuencia (7 días)")
    acwr_load: Optional[float] = Field(None, ge=0, le=4, description="ACWR de carga (7 días)")
    prev_rpe: Optional[float] = Field(None, ge=1, le=10, description="RPE de la sesión anterior (1 a 10)")
    prev_session_load: float = Field(ge=0, le=5000, description="Carga de la sesión anterior")
    prev_has_note: int = Field(ge=0, le=1, description="1 si dejó comentario en la sesión anterior")
    prob_fatiga_prev_session: Optional[float] = Field(None, ge=0, le=1, description="Prob. de fatiga del comentario anterior")
    prob_fatiga_last_note: Optional[float] = Field(None, ge=0, le=1, description="Prob. de fatiga del último comentario")
    days_since_last_note: Optional[float] = Field(None, ge=0, le=3650, description="Días desde el último comentario")
    notes_last_28d: int = Field(ge=0, le=60, description="Comentarios en los últimos 28 días")

    model_config = {"json_schema_extra": {"example": {
        "level": "élite", "sex": "F", "language": "es", "age": 31, "days_since_first_session": 365,
        "days_since_prev_session": 1, "sessions_last_3d": 2, "sessions_last_7d": 5, "sessions_last_28d": 18,
        "load_last_3d": 760, "load_last_7d": 1650, "mean_session_load_28d": 310,
        "acwr3_freq": 1.2, "acwr3_load": 1.3, "acwr_freq": 1.1, "acwr_load": 1.25,
        "prev_rpe": 8, "prev_session_load": 420, "prev_has_note": 1,
        "prob_fatiga_prev_session": 0.70, "prob_fatiga_last_note": 0.70,
        "days_since_last_note": 1, "notes_last_28d": 8}}}


class Prediccion(BaseModel):
    probabilidad: float
    umbral: float
    prediccion: int
    riesgo: str
    recomendacion: str
    version_modelo: str


def clasificar_riesgo(probabilidad):
    if probabilidad >= 0.50:
        return "Alto", "Bajar la carga o programar descanso activo; revisar con el atleta."
    if probabilidad >= UMBRAL:
        return "Moderado", "Revisar con el atleta antes de la sesión y considerar escalar el WOD."
    return "Bajo", "Entrenar según lo planeado."


def a_entradas(datos: dict):
    """JSON validado -> entradas del grafo ONNX. None pasa a NaN y el grafo lo imputa con la mediana."""
    entradas = {c: np.array([[np.nan if datos[c] is None else datos[c]]], dtype=np.float32) for c in NUMERICAS}
    entradas.update({c: np.array([[datos[c]]], dtype=object) for c in CATEGORICAS})
    return entradas


# ---------------------------------------------------------------------------
# 3. Aplicación (mismos endpoints que la Etapa 4)
# ---------------------------------------------------------------------------
app = FastAPI(title="WODPredict-AI API (optimizada, ONNX Runtime)",
              description="Mismo contrato que la Etapa 4; inferencia con ONNX Runtime (Etapa 6).",
              version=metadata["version"])


@app.get("/")
def health_check():
    return {"mensaje": "API funcionando", "modelo": metadata["nombre"], "version": metadata["version"],
            "motor": f"onnxruntime {ort.__version__}"}


@app.get("/modelo")
def info_modelo():
    return metadata


@app.post("/predict", response_model=Prediccion)
def predecir(datos: DatosAtleta):
    probabilidad = float(sesion.run(SALIDA, a_entradas(datos.model_dump()))[0][0, 1])
    riesgo, recomendacion = clasificar_riesgo(probabilidad)
    return Prediccion(probabilidad=round(probabilidad, 4), umbral=UMBRAL, prediccion=int(probabilidad >= UMBRAL),
                      riesgo=riesgo, recomendacion=recomendacion, version_modelo=metadata["version"])


app.mount("/app", StaticFiles(directory=CARPETA / "frontend", html=True), name="frontend")


@app.get("/formulario", include_in_schema=False)
def ir_al_formulario():
    return RedirectResponse(url="/app/")
