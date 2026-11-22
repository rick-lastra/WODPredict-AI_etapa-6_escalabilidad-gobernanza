# Origen de los artefactos del modelo

| Archivo | Origen | SHA-256 |
|---|---|---|
| `model.pkl` | Copia byte a byte de `model/model.pkl` de [WODPredict-AI_etapa-4_API-despliegue](https://github.com/rick-lastra/WODPredict-AI_etapa-4_API-despliegue) (commit `37706cd`, modelo v1.0.0 entrenado el 2026-10-30) | `9cc8a54400b6254dae30cf8bd328cdb272e5172f37f26699d6045683ea57f518` |
| `metadata.json` | Copia de `model/metadata.json` de la misma Etapa 4 | `235a66bab516356189f96e36d4f50ed3ab62870014c6e3ef6ead9633150a6ed2` |
| `model.onnx` | Generado aquí con `python -m src.exportar_onnx` (skl2onnx 1.20.0, opset 17 / ai.onnx.ml 3) a partir de `model.pkl` | ver `resultados/calidad_onnx.json` |

El modelo NO se reentrena en esta etapa: es el mismo v1.0.0. Solo cambia el motor que lo ejecuta.
Datos: sintéticos (`rick-lastra/wodpredict-synth@v1.0`, limpieza de la Etapa 2 `v1.0`).
