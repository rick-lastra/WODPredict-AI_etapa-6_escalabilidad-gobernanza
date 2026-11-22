"""
costos.py - ESTIMACIÓN de costo mensual en Azure Container Apps a partir de lo MEDIDO (Etapa 6).

    python -m src.costos

No hay facturas: el despliegue de la Etapa 4 está apagado. El costo se ESTIMA con:
  - lo medido en resultados/bench_contenedores.json (capacidad por réplica que cumple el SLO);
  - los precios y la demanda SUPUESTOS de config/precios_azure.yaml (cada supuesto está escrito ahí);
  - las reglas de cobro de Azure Container Apps (learn.microsoft.com/azure/container-apps/billing):
      * réplica escalada a 0 -> no cobra;
      * réplicas por ENCIMA del mínimo -> siempre tarifa activa mientras existen;
      * réplicas del MÍNIMO (min > 0) -> tarifa inactiva en los segundos sin consultas
        (sin solicitudes HTTP, < 0.01 vCPU y < 1,000 bytes/s), tarifa activa en el resto.

Configuraciones comparadas (una palanca a la vez, para atribuir el ahorro):
  A. Actual (Etapa 4): imagen 1.0, 0.5 vCPU / 1 GiB, min 0 réplicas (valor por defecto de `az containerapp up`).
  A2. Solo right-sizing SIN ONNX: imagen 1.0 en 0.25 vCPU (control: ¿se podía ahorrar sin optimizar?).
  B. + ONNX: imagen 2.0-onnx, mismo perfil y escalado.
  C. + ONNX + réplica de 0.25 vCPU / 0.5 GiB (right-sizing permitido por la medición).
  D. Propuesta: C + mínimo de 1 réplica SOLO en horario de operación (regla cron) y 0 de noche.
"""
import csv
import json
import math

import yaml

from src.comun import CARPETA_CONFIG, CARPETA_RESULTADOS, guardar_json

FACTOR_UTILIZACION = 0.6   # se dimensiona para usar como máximo 60 % de la capacidad medida (margen para picos)


def cumple_slo(fila, slo_ms, rafaga, max_err):
    """El perfil cumple el SLO si p99 < SLO y errores <= máximo con 1 cliente y con la ráfaga."""
    return all(fila[f"c{c}"]["p99_ms"] < slo_ms and fila[f"c{c}"]["tasa_errores"] <= max_err for c in (1, rafaga))


def capacidad(fila, slo_ms):
    """Mayor throughput medido con p99 < SLO y sin errores (rps). Si ninguno cumple, 0."""
    ok = [fila[k]["throughput_rps"] for k in fila if k.startswith("c") and isinstance(fila[k], dict)
          and fila[k]["p99_ms"] < slo_ms and fila[k]["errores"] == 0]
    return max(ok) if ok else 0.0


def costo_mes(cfg, esc, precios, cap_rps, gratis):
    ca, dias = precios["container_apps"], precios["dias_mes"]
    lam = esc["solicitudes_por_hora"] / 3600                       # consultas por segundo
    seg_operacion = esc["horas_operacion_por_dia"] * 3600 * dias
    replicas = max(1, math.ceil(lam / (cap_rps * FACTOR_UTILIZACION))) if cap_rps > 0 else float("nan")
    frac_activa = 1 - math.exp(-lam)                              # P(al menos una consulta en un segundo), Poisson
    if cfg["min_replicas_operacion"] == 0:
        # Con una consulta cada pocos segundos la réplica nunca llega a escalar a 0 en horario de operación;
        # al cierre paga el cooldown. Todas las réplicas están por encima del mínimo -> tarifa activa.
        s_activos = replicas * (seg_operacion + ca["cooldown_s"] * dias)
        s_inactivos = 0
    else:
        base = cfg["min_replicas_operacion"]
        s_activos = base * seg_operacion * frac_activa + max(replicas - base, 0) * seg_operacion
        s_inactivos = base * seg_operacion * (1 - frac_activa)
    vcpu_s_act, gib_s_act = s_activos * cfg["vcpu"], s_activos * cfg["gib"]
    vcpu_s_ina, gib_s_ina = s_inactivos * cfg["vcpu"], s_inactivos * cfg["gib"]
    solicitudes = esc["solicitudes_por_hora"] * esc["horas_operacion_por_dia"] * dias
    g = ca["capa_gratuita_mensual"] if gratis else {"vcpu_s": 0, "gib_s": 0, "solicitudes": 0}
    computo = (max(vcpu_s_act - g["vcpu_s"], 0) * ca["vcpu_activo_por_s"]
               + max(gib_s_act - g["gib_s"], 0) * ca["gib_activo_por_s"]
               + vcpu_s_ina * ca["vcpu_inactivo_por_s"] + gib_s_ina * ca["gib_inactivo_por_s"])
    peticiones = max(solicitudes - g["solicitudes"], 0) / 1e6 * ca["por_millon_solicitudes"]
    registro = precios["container_registry"]["basic_por_dia"] * dias
    return {"replicas_hora_pico": replicas, "fraccion_segundos_activos": round(frac_activa, 3),
            "vcpu_s_activos": round(vcpu_s_act), "vcpu_s_inactivos": round(vcpu_s_ina),
            "solicitudes_mes": solicitudes, "computo_usd": round(computo, 2), "solicitudes_usd": round(peticiones, 2),
            "registro_usd": round(registro, 2), "total_usd": round(computo + peticiones + registro, 2)}


def main():
    precios = yaml.safe_load((CARPETA_CONFIG / "precios_azure.yaml").read_text(encoding="utf-8"))
    restr = yaml.safe_load((CARPETA_CONFIG / "restricciones.yaml").read_text(encoding="utf-8"))
    bench = json.loads((CARPETA_RESULTADOS / "bench_contenedores.json").read_text(encoding="utf-8"))
    slo = restr["desempeno"]["p99_max_ms"]
    rafaga, max_err = restr["desempeno"]["concurrencia_rafaga"], restr["desempeno"]["tasa_errores_max"]
    medido = {(f["variante"], f["vcpu"]): f for f in bench["resultados"]}

    configs = [
        {"id": "A", "nombre": "Actual (Etapa 4)", "variante": "actual", "vcpu": 0.5, "gib": 1.0, "min_replicas_operacion": 0},
        {"id": "A2", "nombre": "Actual en 0.25 vCPU (sin ONNX)", "variante": "actual", "vcpu": 0.25, "gib": 0.5, "min_replicas_operacion": 0},
        {"id": "B", "nombre": "+ ONNX (palanca 1 y 2)", "variante": "optimizado", "vcpu": 0.5, "gib": 1.0, "min_replicas_operacion": 0},
        {"id": "C", "nombre": "+ réplica 0.25 vCPU (palanca 3)", "variante": "optimizado", "vcpu": 0.25, "gib": 0.5, "min_replicas_operacion": 0},
        {"id": "D", "nombre": "Propuesta: C + min 1 réplica en horario (cron)", "variante": "optimizado", "vcpu": 0.25, "gib": 0.5, "min_replicas_operacion": 1},
    ]
    filas = []
    for cfg in configs:
        fila_bench = medido.get((cfg["variante"], cfg["vcpu"]))
        if fila_bench is None:
            print(f"   (sin medición para {cfg['variante']} @ {cfg['vcpu']} vCPU; corre el benchmark completo)")
            continue
        cap = capacidad(fila_bench, slo)
        slo_ok = cumple_slo(fila_bench, slo, rafaga, max_err)
        for clave, esc in precios["escenarios"].items():
            for gratis in (False, True):
                c = costo_mes(cfg, esc, precios, cap, gratis)
                filas.append({"config": cfg["id"], "configuracion": cfg["nombre"], "escenario": clave,
                              "capa_gratuita": "sí" if gratis else "no", "vcpu": cfg["vcpu"], "gib": cfg["gib"],
                              "min_replicas_operacion": cfg["min_replicas_operacion"],
                              "capacidad_rps_medida_slo": cap,
                              "cumple_slo_con_rafaga": "sí" if slo_ok else "NO", **c})

    with open(CARPETA_RESULTADOS / "costos_escenarios.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    print("  -> resultados/costos_escenarios.csv")

    def total(cfg, esc, gratis="no"):
        return next(r["total_usd"] for r in filas if r["config"] == cfg and r["escenario"] == esc and r["capa_gratuita"] == gratis)

    anual_actual, anual_prop = 12 * total("A", "piloto"), 12 * total("D", "piloto")
    fase_i = precios["fase_i"]
    resumen = {
        "tipo": "ESTIMACIÓN con supuestos (config/precios_azure.yaml) a partir de mediciones locales; no es una factura",
        "piloto_mensual_usd": {c: total(c, "piloto") for c in ("A", "A2", "B", "C", "D") if any(r["config"] == c for r in filas)},
        "red_x10_mensual_usd": {c: total(c, "red_x10") for c in ("A", "A2", "B", "C", "D") if any(r["config"] == c for r in filas)},
        "pico_competencia_mensual_usd": {c: total(c, "pico_competencia") for c in ("A", "A2", "B", "C", "D") if any(r["config"] == c for r in filas)},
        "piloto_anual_usd": {"actual": round(anual_actual, 2), "propuesta": round(anual_prop, 2)},
        "fase_i_presupuesto_computo_nube_anio1_usd": fase_i["computo_nube_anio1"],
        "fase_i_vs_propuesta": (f"La Fase I presupuestó USD {fase_i['computo_nube_anio1']:,} para cómputo en la nube con GPU; "
                                f"el modelo real es una regresión logística que corre en CPU y la propuesta se estima en "
                                f"USD {anual_prop:,.0f} al año sin capa gratuita (piloto)."),
        "cumple_slo_con_rafaga": {r["config"]: r["cumple_slo_con_rafaga"] for r in filas if r["escenario"] == "piloto"},
        "restriccion_costo_cumple": total("D", "piloto") <= total("A", "piloto"),
        "lectura": ("Con la carga del proyecto una sola réplica basta en todos los escenarios, así que el costo lo domina "
                    "el TIEMPO-RÉPLICA (tamaño x segundos encendida x tarifa), no la CPU por consulta. ONNX por sí solo "
                    "(B) no baja la factura; lo que la baja es el tamaño de réplica (C) y la política de réplicas "
                    "mínimas (D). ONNX es lo que permite bajar a 0.25 vCPU sin romper el SLO en ráfaga (A2 no cumple)."),
        "factor_utilizacion": FACTOR_UTILIZACION,
    }
    guardar_json("costos_resumen.json", resumen)
    print(json.dumps(resumen, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
