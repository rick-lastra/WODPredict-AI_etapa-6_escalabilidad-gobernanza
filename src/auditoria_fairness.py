"""
auditoria_fairness.py - Evaluación de fairness y sesgos del modelo v1.0.0 (Etapa 6, gobernanza).

    python -m src.auditoria_fairness

Qué mide (conjunto de prueba: 16,498 sesiones de 56 atletas que el modelo nunca vio; datos SINTÉTICOS):
  1. Métricas por grupo de cada atributo sensible o protegido: sexo, nivel, idioma y grupo de edad.
     Tasa base real, tasa de alertas, recall (TPR), tasa de falsas alarmas (FPR), precisión y ROC-AUC.
  2. Brechas entre grupos con intervalos de confianza al 95 % por BOOTSTRAP DE ATLETAS: se remuestrean
     atletas completos, no sesiones, porque las sesiones de un mismo atleta no son independientes.
  3. Criterio principal: IGUALDAD DE OPORTUNIDAD (recall parecido entre grupos). En este caso de uso el
     error grave es el falso negativo: un atleta en riesgo de sobrecarga que no recibe alerta.
     Criterio secundario: FPR (carga de falsas alarmas). La paridad demográfica (misma tasa de alertas)
     se reporta, pero NO se usa como criterio: las tasas base reales son distintas entre grupos (por
     ejemplo, novatos 18 % contra élite 8 %), así que igualar alertas obligaría a ignorar riesgo real.
  4. Mitigaciones probadas:
     A. Reentrenar el MISMO pipeline sin la variable `sex` (y sin `sex` ni `language`). El sexo es un
        atributo protegido que hoy entra al modelo.
     B. Sobre el modelo sin sexo, un umbral por NIVEL (no por sexo) calibrado solo con el conjunto de
        entrenamiento, para corregir el bajo recall del nivel élite. El nivel es un factor de riesgo
        deportivo legítimo, no un atributo protegido; aun así, cambiar umbrales requiere la aprobación del
        responsable del modelo (política "no_automatizar" de la Etapa 5).
  5. Explicabilidad global: coeficientes de la regresión logística (sobre variables escaladas).

Umbrales de la auditoría (definidos antes de medir):
  - Alerta de sesgo si |brecha de recall| > 0.10 o si un grupo queda con recall < 0.70 (SLO de calidad).
  - Una brecha cuyo intervalo de 95 % incluye 0 se reporta como "no concluyente" por tamaño de muestra.
"""
import json

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

import joblib

from src.comun import (CARPETA_MODELO, CARPETA_RESULTADOS, CATEGORICAS, ETIQUETA, NUMERICAS, SEMILLA, UMBRAL,
                       entorno, guardar_json, separar_entrenamiento_prueba)

N_BOOTSTRAP = 1000
UMBRAL_BRECHA_RECALL = 0.10
RECALL_MINIMO = 0.70


def grupo_edad(edad):
    if pd.isna(edad):
        return "sin dato"
    return "≤ 30" if edad <= 30 else ("31 a 40" if edad <= 40 else "> 40")


ATRIBUTOS = {"sexo": "sex", "nivel": "level", "idioma": "language", "edad": "grupo_edad"}


def metricas(y, p, d):
    pos, neg = y == 1, y == 0
    return {"sesiones": int(len(y)), "tasa_base": float(y.mean()), "tasa_alertas": float(d.mean()),
            "recall": float(d[pos].mean()) if pos.any() else np.nan,
            "fpr": float(d[neg].mean()) if neg.any() else np.nan,
            "precision": float(precision_score(y, d, zero_division=0)),
            "roc_auc": float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else np.nan}


def tabla_grupos(df, prob, dec, atributo):
    filas = []
    for g, sub in df.groupby(atributo):
        i = sub.index.to_numpy()
        m = metricas(sub[ETIQUETA].to_numpy(), prob[i], dec[i])
        filas.append({"atributo": atributo, "grupo": g, "atletas": int(sub["athlete_id"].nunique()), **m})
    return filas


def bootstrap_brechas(df, dec, atributo, rng):
    """IC 95 % del recall, FPR y tasa de alertas por grupo y de la brecha máx-mín, remuestreando atletas."""
    grupos = sorted(df[atributo].dropna().unique())
    por_atleta = {a: idx.to_numpy() for a, idx in df.groupby("athlete_id").groups.items()}
    atleta_grupo = df.groupby("athlete_id")[atributo].first()
    y_all = df[ETIQUETA].to_numpy()
    d_all = dec
    muestras = {k: [] for k in ("brecha_recall", "brecha_fpr", "brecha_alertas")}
    recall_g = {g: [] for g in grupos}
    for _ in range(N_BOOTSTRAP):
        r, f, a = {}, {}, {}
        for g in grupos:
            atletas = atleta_grupo[atleta_grupo == g].index.to_numpy()
            elegidos = rng.choice(atletas, size=len(atletas), replace=True)
            idx = np.concatenate([por_atleta[x] for x in elegidos])
            y, d = y_all[idx], d_all[idx]
            r[g] = d[y == 1].mean() if (y == 1).any() else np.nan
            f[g] = d[y == 0].mean() if (y == 0).any() else np.nan
            a[g] = d.mean()
            recall_g[g].append(r[g])
        muestras["brecha_recall"].append(np.nanmax(list(r.values())) - np.nanmin(list(r.values())))
        muestras["brecha_fpr"].append(np.nanmax(list(f.values())) - np.nanmin(list(f.values())))
        muestras["brecha_alertas"].append(max(a.values()) - min(a.values()))

    def ic(v):
        v = np.asarray(v, dtype=float)
        return [round(float(np.nanpercentile(v, 2.5)), 4), round(float(np.nanpercentile(v, 97.5)), 4)]

    return {"ic95_recall_por_grupo": {str(g): ic(v) for g, v in recall_g.items()},
            **{f"ic95_{k}": ic(v) for k, v in muestras.items()}}


def brechas(filas):
    rec = [f["recall"] for f in filas]
    fpr = [f["fpr"] for f in filas]
    ale = [f["tasa_alertas"] for f in filas]
    return {"brecha_recall": float(max(rec) - min(rec)), "brecha_fpr": float(max(fpr) - min(fpr)),
            "brecha_alertas": float(max(ale) - min(ale)),
            "razon_alertas_min_max": float(min(ale) / max(ale)) if max(ale) > 0 else np.nan,
            "recall_minimo_grupo": float(min(rec))}


def veredicto(b, ic_brecha_recall, recall_ic_min):
    sesgo = b["brecha_recall"] > UMBRAL_BRECHA_RECALL or b["recall_minimo_grupo"] < RECALL_MINIMO
    if not sesgo:
        return "sin hallazgo"
    # El bootstrap de la brecha máx-mín nunca baja de 0, así que se usa el IC del recall por grupo:
    concluyente = recall_ic_min is not None and recall_ic_min[1] < RECALL_MINIMO
    return "HALLAZGO" if concluyente or ic_brecha_recall[0] > UMBRAL_BRECHA_RECALL else "hallazgo no concluyente (muestra pequeña)"


def crear_modelo(categoricas):
    numericas = Pipeline([("imputar", SimpleImputer(strategy="median")), ("escalar", StandardScaler())])
    transformadores = [("num", numericas, NUMERICAS)]
    if categoricas:
        transformadores.append(("cat", OneHotEncoder(handle_unknown="ignore"), categoricas))
    return Pipeline([("prep", ColumnTransformer(transformadores)),
                     ("modelo", LogisticRegression(C=0.1, max_iter=3000, random_state=SEMILLA))])


def evaluar_variante(nombre, prob, umbrales, prueba, rng):
    y = prueba[ETIQUETA].to_numpy()
    d = (prob >= umbrales).astype(int)
    global_ = {"recall": round(recall_score(y, d), 4), "precision": round(precision_score(y, d), 4),
               "roc_auc": round(roc_auc_score(y, prob), 4), "tasa_alertas": round(float(d.mean()), 4)}
    filas, resumen = [], {}
    for etiqueta, col in ATRIBUTOS.items():
        f = tabla_grupos(prueba, prob, d, col)
        b = brechas(f)
        bs = bootstrap_brechas(prueba, d, col, rng)
        peor = min(f, key=lambda x: x["recall"])["grupo"]
        resumen[etiqueta] = {**{k: round(v, 4) for k, v in b.items()}, **bs,
                             "grupo_con_menor_recall": str(peor),
                             "veredicto": veredicto(b, bs["ic95_brecha_recall"], bs["ic95_recall_por_grupo"].get(str(peor)))}
        for x in f:
            x["variante"] = nombre
            x["atributo"] = etiqueta
        filas += f
    return global_, filas, resumen


def calibrar_umbral_por_nivel(entrenamiento, cats, recall_objetivo=0.732):
    """Umbral por nivel con predicciones fuera de pliegue en ENTRENAMIENTO (nunca con el conjunto de prueba)."""
    from sklearn.model_selection import GroupKFold
    X = NUMERICAS + cats
    oof = np.zeros(len(entrenamiento))
    for a, b in GroupKFold(5).split(entrenamiento, entrenamiento[ETIQUETA], entrenamiento["athlete_id"]):
        m = crear_modelo(cats).fit(entrenamiento.iloc[a][X], entrenamiento.iloc[a][ETIQUETA])
        oof[b] = m.predict_proba(entrenamiento.iloc[b][X])[:, 1]
    y = entrenamiento[ETIQUETA].to_numpy()
    umbrales = {}
    for nivel in sorted(entrenamiento["level"].unique()):
        pos = (entrenamiento["level"].to_numpy() == nivel) & (y == 1)
        umbrales[nivel] = UMBRAL
        for t in np.round(np.arange(UMBRAL, 0.049, -0.005), 3):
            if (oof[pos] >= t).mean() >= recall_objetivo:
                umbrales[nivel] = float(t)
                break
    return umbrales


def main():
    rng = np.random.default_rng(SEMILLA)
    entrenamiento, prueba = separar_entrenamiento_prueba()
    for df in (entrenamiento, prueba):
        df["grupo_edad"] = df["age"].map(grupo_edad)

    print("1. Modelo v1.0.0 (Etapa 4) y control de reproducibilidad")
    v1 = joblib.load(CARPETA_MODELO / "model.pkl")
    p_v1 = v1.predict_proba(prueba[NUMERICAS + CATEGORICAS])[:, 1]
    reentrenado = crear_modelo(CATEGORICAS).fit(entrenamiento[NUMERICAS + CATEGORICAS], entrenamiento[ETIQUETA])
    dif_reentreno = float(np.abs(reentrenado.predict_proba(prueba[NUMERICAS + CATEGORICAS])[:, 1] - p_v1).max())

    umbral_unico = np.full(len(prueba), UMBRAL)
    variantes = {"v1.0.0 (con sexo)": (p_v1, umbral_unico)}
    print("2. Mitigación A: reentrenar sin sexo y sin sexo ni idioma")
    for nombre, cats in {"sin sexo": ["level", "language"], "sin sexo ni idioma": ["level"]}.items():
        m = crear_modelo(cats).fit(entrenamiento[NUMERICAS + cats], entrenamiento[ETIQUETA])
        variantes[nombre] = (m.predict_proba(prueba[NUMERICAS + cats])[:, 1], umbral_unico)

    print("   Mitigación B: umbral por nivel calibrado SOLO con entrenamiento (validación cruzada por atleta)")
    umbrales_nivel = calibrar_umbral_por_nivel(entrenamiento, ["level", "language"])
    umbral_por_fila = prueba["level"].map(umbrales_nivel).to_numpy(dtype=float)
    variantes["sin sexo + umbral por nivel"] = (variantes["sin sexo"][0], umbral_por_fila)
    print(f"   umbrales elegidos: {umbrales_nivel}")

    print("3. Métricas por grupo y bootstrap por atleta (1,000 remuestreos por atributo)")
    globales, filas, resumenes = {}, [], {}
    for nombre, (prob, umbrales) in variantes.items():
        g, f, r = evaluar_variante(nombre, prob, umbrales, prueba, rng)
        globales[nombre], resumenes[nombre] = g, r
        filas += f
        print(f"   {nombre}: recall {g['recall']} | " + " | ".join(f"{k} Δrecall {v['brecha_recall']:.3f} ({v['veredicto']})"
                                                         for k, v in r.items()))

    tabla = pd.DataFrame(filas)[["variante", "atributo", "grupo", "atletas", "sesiones", "tasa_base", "tasa_alertas",
                                  "recall", "fpr", "precision", "roc_auc"]]
    tabla.round(4).to_csv(CARPETA_RESULTADOS / "fairness_por_grupo.csv", index=False)
    print("  -> resultados/fairness_por_grupo.csv")

    print("4. Explicabilidad global (coeficientes del v1.0.0)")
    nombres = v1.named_steps["prep"].get_feature_names_out()
    coef = pd.DataFrame({"variable": [n.split("__", 1)[1] for n in nombres],
                         "coeficiente": v1.named_steps["modelo"].coef_[0]})
    coef["odds_ratio"] = np.exp(coef["coeficiente"])
    coef = coef.reindex(coef["coeficiente"].abs().sort_values(ascending=False).index)
    coef.round(4).to_csv(CARPETA_RESULTADOS / "coeficientes_modelo.csv", index=False)
    print("  -> resultados/coeficientes_modelo.csv")
    rango = {c: int(coef.reset_index(drop=True).query("variable == @c").index[0]) + 1 for c in ("sex_F", "sex_M")}

    guardar_json("fairness_resumen.json", {
        "descripcion": "Auditoría de fairness del modelo de sobrecarga (conjunto de prueba por atleta)",
        "tipo_medicion": "MEDICIÓN REAL sobre datos SINTÉTICOS (wodpredict-synth@v1.0); 56 atletas de prueba",
        "umbral_decision": UMBRAL, "bootstrap": f"{N_BOOTSTRAP} remuestreos de atletas por grupo",
        "criterio_principal": "igualdad de oportunidad (brecha de recall)",
        "umbrales_auditoria": {"brecha_recall_max": UMBRAL_BRECHA_RECALL, "recall_minimo_por_grupo": RECALL_MINIMO},
        "control_reentrenamiento_max_dif_prob": dif_reentreno,
        "umbrales_por_nivel_mitigacion_b": umbrales_nivel,
        "metodo_umbral_por_nivel": ("predicciones fuera de pliegue (GroupKFold 5 por atleta) del modelo sin sexo en el "
                                    "conjunto de ENTRENAMIENTO; para cada nivel, el umbral más alto <= 0.17 que alcanza el "
                                    "recall global del v1.0.0 (0.732). El conjunto de prueba no se usa para elegirlo."),
        "metricas_globales": globales, "brechas_por_variante": resumenes,
        "posicion_sexo_en_ranking_de_coeficientes": rango, "variables_totales": int(len(coef)),
        "entorno": entorno()})


if __name__ == "__main__":
    main()
