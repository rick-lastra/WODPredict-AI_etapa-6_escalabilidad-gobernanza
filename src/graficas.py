"""
graficas.py - Gráficas de evidencia para el reporte (PNG en resultados/graficas/).

    python -m src.graficas

Paleta: azul = sistema actual (Etapa 4), naranja = optimizado (Etapa 6). Un solo eje por gráfica.
"""
import csv
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from src.comun import CARPETA_RESULTADOS  # noqa: E402

AZUL, NARANJA, TINTA, TINTA2, REJILLA = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
COLORES = {"actual": AZUL, "optimizado": NARANJA}
ETIQUETAS = {"actual": "Actual (Etapa 4)", "optimizado": "Optimizado (ONNX)"}
plt.rcParams.update({"font.size": 10, "axes.edgecolor": TINTA2, "axes.labelcolor": TINTA2, "xtick.color": TINTA2,
                     "ytick.color": TINTA2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": REJILLA, "grid.linewidth": 0.8, "axes.axisbelow": True,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
SALIDA = CARPETA_RESULTADOS / "graficas"


def barras(ax, perfiles, valores, titulo, unidad, formato="{:.1f}", linea=None, etiqueta_linea=None, log=False):
    x = np.arange(len(perfiles))
    ancho = 0.36
    for i, variante in enumerate(("actual", "optimizado")):
        v = valores[variante]
        pos = x + (i - 0.5) * (ancho + 0.03)
        ax.bar(pos, v, ancho, color=COLORES[variante], label=ETIQUETAS[variante], edgecolor="#fcfcfb", linewidth=2)
        for p, val in zip(pos, v):
            ax.annotate(formato.format(val), (p, val), ha="center", va="bottom", fontsize=8, color=TINTA,
                        xytext=(0, 2), textcoords="offset points")
    if linea is not None:
        ax.axhline(linea, color=TINTA2, linestyle="--", linewidth=1)
        ax.annotate(etiqueta_linea, (len(perfiles) - 0.5, linea), ha="right", va="bottom", fontsize=8, color=TINTA2)
    if log:
        ax.set_yscale("log")
    ax.set_xticks(x, [f"{p} vCPU" for p in perfiles])
    ax.set_title(titulo, loc="left", fontsize=11, color=TINTA)
    ax.set_ylabel(unidad)
    ax.grid(axis="x", visible=False)


def antes_despues():
    datos = json.loads((CARPETA_RESULTADOS / "bench_contenedores.json").read_text(encoding="utf-8"))["resultados"]
    perfiles = sorted({f["vcpu"] for f in datos})

    def serie(fn):
        return {v: [fn(next(f for f in datos if f["variante"] == v and f["vcpu"] == p)) for p in perfiles]
                for v in ("actual", "optimizado")}

    def cap(f):
        return max(f[k]["throughput_rps"] for k in f if k.startswith("c") and isinstance(f[k], dict)
                   and f[k]["p99_ms"] < 300 and f[k]["errores"] == 0)

    fig, ejes = plt.subplots(2, 2, figsize=(11, 7.5))
    barras(ejes[0, 0], perfiles, serie(lambda f: f["c16"]["p99_ms"]), "Latencia p99 con 16 clientes simultáneos",
           "ms (escala log)", "{:.0f}", 300, "SLO 300 ms", log=True)
    barras(ejes[0, 1], perfiles, serie(cap), "Capacidad por réplica que cumple el SLO", "consultas/s", "{:.0f}")
    barras(ejes[1, 0], perfiles, serie(lambda f: f["c4"]["cpu_ms_por_consulta"]), "CPU consumida por consulta",
           "ms de CPU", "{:.1f}")
    barras(ejes[1, 1], perfiles, serie(lambda f: f["arranque_frio_s_mediana"]), "Arranque en frío (docker run → 1.ª respuesta)",
           "segundos", "{:.1f}")
    ejes[0, 0].legend(frameon=False, loc="upper right")
    fig.suptitle("WODPredict-AI: antes vs después (medición local con límites de réplica de Azure)",
                 x=0.01, ha="left", fontsize=12, color=TINTA)
    fig.tight_layout()
    fig.savefig(SALIDA / "antes_despues_contenedores.png", dpi=200)
    plt.close(fig)


def costos():
    filas = list(csv.DictReader(open(CARPETA_RESULTADOS / "costos_escenarios.csv", encoding="utf-8")))
    escenarios = [("piloto", "Piloto (288 consultas/h)"), ("red_x10", "Red ×10"), ("pico_competencia", "Pico de competencia ×50")]
    fig, ejes = plt.subplots(1, 3, figsize=(12, 4.4))
    for ax, (clave, titulo) in zip(ejes, escenarios):
        sub = [r for r in filas if r["escenario"] == clave and r["capa_gratuita"] == "no"]
        etiquetas = [r["config"] for r in sub]
        valores = [float(r["total_usd"]) for r in sub]
        no_cumple = [r["cumple_slo_con_rafaga"] != "sí" for r in sub]
        colores = ["#b8b7b1" if nc else (AZUL if c == "A" else NARANJA) for c, nc in zip(etiquetas, no_cumple)]
        barras_ = ax.bar(etiquetas, valores, color=colores, edgecolor="#fcfcfb", linewidth=2, width=0.6)
        for b, nc in zip(barras_, no_cumple):
            if nc:
                b.set_hatch("///")
                b.set_edgecolor(TINTA2)
        for i, (v, nc) in enumerate(zip(valores, no_cumple)):
            ax.annotate(f"${v:,.2f}" + ("\nno cumple SLO" if nc else ""), (i, v), ha="center", va="bottom",
                        fontsize=8, color=TINTA, xytext=(0, 2), textcoords="offset points")
        ax.set_ylim(0, max(valores) * 1.22)
        ax.set_title(titulo, loc="left", fontsize=11, color=TINTA)
        ax.set_ylabel("USD al mes (sin capa gratuita)")
        ax.grid(axis="x", visible=False)
    fig.suptitle("Costo mensual ESTIMADO (Azure Container Apps + ACR Basic)\nA = actual · A2 = actual en 0.25 vCPU · "
                 "B = +ONNX · C = +ONNX y 0.25 vCPU · D = propuesta (C + min 1 réplica en horario)", x=0.01, ha="left", fontsize=10, color=TINTA)
    fig.tight_layout()
    fig.savefig(SALIDA / "costos_escenarios.png", dpi=200)
    plt.close(fig)


def fairness():
    tabla = list(csv.DictReader(open(CARPETA_RESULTADOS / "fairness_por_grupo.csv", encoding="utf-8")))
    resumen = json.loads((CARPETA_RESULTADOS / "fairness_resumen.json").read_text(encoding="utf-8"))["brechas_por_variante"]
    series = [("v1.0.0 (con sexo)", "v1.0.0 actual", AZUL), ("sin sexo + umbral por nivel", "Propuesta: sin sexo + umbral por nivel", NARANJA)]
    atributos = ["sexo", "nivel", "idioma", "edad"]
    fig, ejes = plt.subplots(1, 4, figsize=(13, 4.5), sharey=True)
    for ax, atr in zip(ejes, atributos):
        grupos = [r["grupo"] for r in tabla if r["variante"] == series[0][0] and r["atributo"] == atr]
        orden = {"≤ 30": 0, "31 a 40": 1, "> 40": 2, "novato": 0, "intermedio": 1, "élite": 2}
        grupos.sort(key=lambda g: orden.get(g, 0))
        x = np.arange(len(grupos))
        for i, (var, etiqueta, color) in enumerate(series):
            rec = [float(next(r for r in tabla if r["variante"] == var and r["atributo"] == atr and r["grupo"] == g)["recall"])
                   for g in grupos]
            ic = resumen[var][atr]["ic95_recall_por_grupo"]
            err = np.array([[r - ic[g][0] for r, g in zip(rec, grupos)], [ic[g][1] - r for r, g in zip(rec, grupos)]])
            pos = x + (i - 0.5) * 0.36
            ax.bar(pos, rec, 0.33, color=color, label=etiqueta, edgecolor="#fcfcfb", linewidth=2)
            ax.errorbar(pos, rec, yerr=err, fmt="none", ecolor=TINTA2, elinewidth=1, capsize=3)
        ax.axhline(0.70, color=TINTA2, linestyle="--", linewidth=1)
        ax.set_xticks(x, grupos)
        ax.set_title(atr.capitalize(), loc="left", fontsize=11, color=TINTA)
        ax.set_ylim(0.4, 0.95)
        ax.grid(axis="x", visible=False)
    ejes[0].set_ylabel("Recall por grupo (IC 95 % por atleta)")
    manejadores, etiquetas = ejes[0].get_legend_handles_labels()
    fig.legend(manejadores, etiquetas, frameon=False, loc="upper left", bbox_to_anchor=(0.005, 0.93), ncol=2, fontsize=9)
    fig.suptitle("Igualdad de oportunidad: recall por grupo en 56 atletas de prueba (datos sintéticos). Línea punteada = SLO 0.70",
                 x=0.01, ha="left", fontsize=12, color=TINTA)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(SALIDA / "fairness_recall_por_grupo.png", dpi=200)
    plt.close(fig)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    if (CARPETA_RESULTADOS / "fairness_resumen.json").exists():
        fairness()
    antes_despues()
    if (CARPETA_RESULTADOS / "costos_escenarios.csv").exists():
        costos()
    print(f"  -> {SALIDA.relative_to(CARPETA_RESULTADOS.parent)}/")


if __name__ == "__main__":
    main()
