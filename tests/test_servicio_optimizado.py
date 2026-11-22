"""
test_servicio_optimizado.py - La API optimizada respeta el contrato de la Etapa 4.

    pytest tests/ -v

No necesita Docker: usa el TestClient de FastAPI sobre servicio_optimizado/app.py.
Las probabilidades esperadas son las que documenta el README de la Etapa 4 (simula_consumo.py).
"""
import json
import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
os.environ["CARPETA_MODELO"] = str(RAIZ / "modelo")
sys.path.insert(0, str(RAIZ / "servicio_optimizado"))

from fastapi.testclient import TestClient  # noqa: E402

import app as servicio  # noqa: E402

cliente = TestClient(servicio.app)
ESPERADO = {"bajo": (0.030, "Bajo", 0), "moderado": (0.3025, "Moderado", 1), "alto": (0.7502, "Alto", 1)}


def ejemplo(nombre):
    return json.loads((RAIZ / "tests" / "ejemplos" / f"atleta_riesgo_{nombre}.json").read_text(encoding="utf-8"))


def test_health_check():
    r = cliente.get("/")
    assert r.status_code == 200 and r.json()["version"] == "1.0.0" and "onnxruntime" in r.json()["motor"]


@pytest.mark.parametrize("nombre", list(ESPERADO))
def test_mismas_predicciones_que_etapa4(nombre):
    prob, riesgo, alerta = ESPERADO[nombre]
    r = cliente.post("/predict", json=ejemplo(nombre)).json()
    assert abs(r["probabilidad"] - prob) <= 0.001
    assert r["riesgo"] == riesgo and r["prediccion"] == alerta and r["umbral"] == 0.17


def test_rechaza_dato_fuera_de_rango():
    datos = ejemplo("moderado") | {"prev_rpe": 11}
    r = cliente.post("/predict", json=datos)
    assert r.status_code == 422 and "prev_rpe" in r.text


def test_vacios_se_imputan():
    datos = ejemplo("moderado") | {"age": None, "prev_rpe": None, "acwr_load": None}
    assert cliente.post("/predict", json=datos).status_code == 200


def test_mismo_contrato_de_respuesta():
    r = cliente.post("/predict", json=ejemplo("alto")).json()
    assert set(r) == {"probabilidad", "umbral", "prediccion", "riesgo", "recomendacion", "version_modelo"}
