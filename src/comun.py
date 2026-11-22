"""
comun.py - Rutas, datos y utilidades compartidas por los scripts de la Etapa 6.

Datos: se usan los mismos datos (Etapa 2, tag v1.0) y la misma separación 80/20 por atleta
(GroupShuffleSplit, semilla 42) que las Etapas 4 y 5. Nada se inventa: las consultas del benchmark
son sesiones reales del conjunto de prueba (atletas que el modelo nunca vio). El dataset es
SINTÉTICO desde su origen (rick-lastra/wodpredict-synth@v1.0), como en todas las etapas.
"""
import hashlib
import json
import platform
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_MODELO = RAIZ / "modelo"
CARPETA_DATOS = RAIZ / "datos"
CARPETA_RESULTADOS = RAIZ / "resultados"
CARPETA_CONFIG = RAIZ / "config"
ARCHIVO_DATOS = CARPETA_DATOS / "sesiones_limpias.csv"
URL_DATOS = ("https://raw.githubusercontent.com/rick-lastra/WODPredict-AI_etapa-2_preparacion-datos/"
             "v1.0/datos/datos_limp/sesiones_limpias.csv")
SHA256_DATOS = "4256b41dc5675e8d247541103f2059bc7f4ec6fbff9f455e6dd14f7d16016fe4"

SEMILLA = 42
METADATA = json.loads((CARPETA_MODELO / "metadata.json").read_text(encoding="utf-8"))
NUMERICAS = METADATA["variables_numericas"]
CATEGORICAS = METADATA["variables_categoricas"]
VARIABLES = NUMERICAS + CATEGORICAS
ETIQUETA = "overreaching_label"
UMBRAL = METADATA["umbral"]
ENTERAS = ["days_since_first_session", "days_since_prev_session", "sessions_last_3d", "sessions_last_7d",
           "sessions_last_28d", "prev_has_note", "notes_last_28d"]


def sha256(ruta):
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def cargar_datos():
    """Lee datos/sesiones_limpias.csv; si no existe, lo descarga del tag v1.0 de la Etapa 2."""
    if not ARCHIVO_DATOS.exists():
        CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
        print(f"Descargando datos de la Etapa 2 (v1.0, ~19 MB)...\n  {URL_DATOS}")
        # Se guardan los bytes tal cual (sin pasar por pandas) para que el SHA-256 coincida en
        # cualquier sistema operativo; pandas en Windows reescribe el archivo con saltos de línea \r\n.
        from urllib.request import urlopen
        with urlopen(URL_DATOS) as respuesta:
            ARCHIVO_DATOS.write_bytes(respuesta.read())
    huella = sha256(ARCHIVO_DATOS)
    if huella != SHA256_DATOS:
        print(f"AVISO: el archivo de datos no coincide con el SHA-256 esperado ({huella[:12]}...)")
    return pd.read_csv(ARCHIVO_DATOS)


def separar_entrenamiento_prueba():
    """Separación 80/20 por atleta idéntica a la Etapa 4 (GroupShuffleSplit, semilla 42)."""
    from sklearn.model_selection import GroupShuffleSplit
    datos = cargar_datos()
    separador = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEMILLA)
    idx_train, idx_test = next(separador.split(datos[VARIABLES], datos[ETIQUETA], groups=datos["athlete_id"]))
    return datos.iloc[idx_train].reset_index(drop=True), datos.iloc[idx_test].reset_index(drop=True)


def conjunto_prueba():
    """Solo la parte de prueba (56 atletas que el modelo nunca vio)."""
    return separar_entrenamiento_prueba()[1]


def a_json(fila):
    """Convierte una fila del dataset en el JSON que recibe POST /predict (NaN -> null)."""
    salida = {}
    for col in VARIABLES:
        valor = fila[col]
        if isinstance(valor, float) and np.isnan(valor):
            salida[col] = None
        elif col in ENTERAS:
            salida[col] = int(valor)
        elif col in CATEGORICAS:
            salida[col] = str(valor)
        else:
            salida[col] = float(valor)
    return salida


def cargas_de_prueba(n=500, semilla=SEMILLA):
    """n consultas reales (sin repetir) del conjunto de prueba, en formato JSON de la API."""
    prueba = conjunto_prueba()
    muestra = prueba.sample(n=min(n, len(prueba)), random_state=semilla)
    return [a_json(fila) for _, fila in muestra.iterrows()]


def entorno():
    """Descripción del equipo donde se midió (va en cada archivo de resultados)."""
    import os
    return {"fecha": datetime.now().isoformat(timespec="seconds"), "python": sys.version.split()[0],
            "sistema": platform.platform(), "procesador": platform.processor() or platform.machine(),
            "nucleos_logicos": os.cpu_count()}


def guardar_json(nombre, contenido):
    CARPETA_RESULTADOS.mkdir(exist_ok=True)
    ruta = CARPETA_RESULTADOS / nombre
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {ruta.relative_to(RAIZ)}")
    return ruta


def percentiles(tiempos_ms):
    t = np.asarray(tiempos_ms, dtype=float)
    return {"n": int(t.size), "media_ms": round(float(t.mean()), 3), "p50_ms": round(float(np.percentile(t, 50)), 3),
            "p95_ms": round(float(np.percentile(t, 95)), 3), "p99_ms": round(float(np.percentile(t, 99)), 3),
            "max_ms": round(float(t.max()), 3)}
