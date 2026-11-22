# Model card: WODPredict-AI, sobrecarga al día siguiente

Formato basado en *Model Cards for Model Reporting* (Mitchell et al., 2019). Cada cifra remite a un archivo de evidencia del repositorio.

## 1. Detalles del modelo

| Campo | Valor |
|---|---|
| Nombre y versión | WODPredict-AI, sobrecarga al día siguiente, **v1.0.0** (entrenado el 2026-10-30, Etapa 4) |
| Tipo | Regresión logística (`C = 0.1`) dentro de un `Pipeline` de scikit-learn: imputación por mediana, escalado, One-Hot y regresión |
| Variables | 20 numéricas (carga, frecuencia, ACWR, RPE, señal NLP `prob_fatiga_*`) y 3 categóricas (`level`, `sex`, `language`) |
| Umbral de decisión | 0.17, elegido en la Etapa 3 para priorizar el recall |
| Artefactos | `modelo/model.pkl` y `modelo/model.onnx` (mismo modelo, motor distinto). Las huellas SHA-256 están en `modelo/ORIGEN.md` y en `resultados/calidad_onnx.json` |
| Responsable | Responsable del modelo: Ricardo Lastra (autor del capstone). Usuario final: el coach de UnderCover Fitness |
| Licencia de datos | Dataset sintético `rick-lastra/wodpredict-synth@v1.0` (Hugging Face) |

## 2. Uso previsto

- **Uso previsto:** apoyar al coach, antes de la sesión, a decidir si ajusta la carga de un atleta con riesgo de sobrecarga al día siguiente. **El modelo recomienda y el coach decide** (human-in-the-loop).
- **Usuarios:** coaches certificados de la red UnderCover Fitness.
- **Fuera de alcance:**
  - Diagnóstico médico o de lesiones.
  - Decisiones de membresía, precios o selección de atletas.
  - Uso sin un coach que revise la alerta.
  - Uso con menores de 16 años: el contrato de la API rechaza `age < 16`.

## 3. Datos

- **Entrenamiento:** 65,403 sesiones (80 % de los atletas). **Prueba:** 16,498 sesiones de 56 atletas que el modelo nunca vio. La separación es por atleta (`GroupShuffleSplit`, semilla 42).
- **Los datos son sintéticos.** Se generaron a partir de patrones de carga de CrossFit, más el registro personal de SugarWOD del autor en las Etapas 1 y 2. Todavía no hay datos reales de atletas: el piloto con Wodify sigue pendiente.
- **Composición del conjunto de prueba** (`resultados/fairness_por_grupo.csv`):
  - Sexo: 35 atletas F y 21 M.
  - Nivel: 22 novatos, 15 intermedios y 19 élite.
  - Idioma: 36 en español y 20 en inglés.
  - Edad: 21 atletas de 30 años o menos, 24 de 31 a 40 y 11 de más de 40.

## 4. Desempeño (conjunto de prueba, umbral 0.17)

| Métrica | Valor | Fuente |
|---|---|---|
| Recall | 0.732 | `resultados/calidad_onnx.json` |
| Precisión | 0.378 | idem |
| ROC-AUC | 0.859 | idem |
| Tasa de alertas | 24.4 % | `resultados/fairness_resumen.json` |
| Latencia p99, réplica de 0.25 vCPU con ráfaga de 4 consultas (imagen ONNX) | 65 ms | `resultados/bench_contenedores.json` |

## 5. Evaluación de fairness (`resultados/fairness_resumen.json`)

El criterio principal es la **igualdad de oportunidad**: un recall parecido entre grupos, porque el error grave es no alertar a un atleta en riesgo. Los intervalos de confianza se calcularon con un bootstrap de 1,000 remuestreos de atletas.

| Atributo | Brecha de recall (IC 95 %) | Grupo con menor recall | Veredicto |
|---|---|---|---|
| Sexo | 0.013 (0.002 a 0.097) | M, 0.725 | Sin hallazgo |
| Idioma | 0.003 (0.002 a 0.103) | en, 0.730 | Sin hallazgo |
| Edad | 0.098 (0.030 a 0.211) | 31 a 40, 0.689 | No concluyente por muestra pequeña |
| **Nivel** | **0.176 (0.094 a 0.252)** | **élite, 0.623 (IC 0.569 a 0.686)** | **HALLAZGO**: todo el intervalo de élite queda por debajo del SLO de 0.70 |

**Explicabilidad global** (`resultados/coeficientes_modelo.csv`):
- Las variables con más peso son los días desde la sesión anterior (OR 0.31), la carga de 7 días (OR 2.01), las sesiones en 28 días (OR 0.57) y la carga de 3 días (OR 1.63). Después aparece el nivel: élite con OR 0.64 y novato con OR 1.47.
- El **sexo** ocupa los lugares 25 y 27 de 27 variables, con un OR de 0.99. Casi no aporta, y aun así es un atributo protegido dentro del modelo.

## 6. Mitigaciones evaluadas

| Variante | Recall | Precisión | Brecha de recall por nivel | Recall élite |
|---|---|---|---|---|
| v1.0.0 (actual) | 0.732 | 0.378 | 0.176 | 0.623 |
| Sin `sex` | 0.731 | 0.378 | 0.176 | 0.621 |
| Sin `sex` ni `language` | 0.728 | 0.381 | 0.178 | 0.616 |
| **Sin `sex` + umbral por nivel** (élite 0.10, resto 0.17; calibrado solo con entrenamiento) | **0.782** | **0.330** | **0.070** | **0.805** |

**Costo de la mitigación:**
- La tasa de alertas sube de 24 % a 30 %.
- La precisión del nivel élite baja a 0.215, lo que significa más falsas alarmas para esos atletas.
- La precisión global sigue arriba del mínimo de 0.30 de la Etapa 5.

Cambiar el umbral requiere la aprobación del responsable del modelo, según la política `no_automatizar` de la Etapa 5. **El responsable aprobó el 20-nov-2026 la última variante** (sin `sex` + umbral por nivel). Se publicará como v1.1.0 en la fase de preparación del piloto (`gobernanza/auditoria_rai.md`, secciones 7 y 8). Esta model card describe la v1.0.0, que es la versión medida.

## 7. Limitaciones y riesgos conocidos

- Datos sintéticos y solo 56 atletas de prueba: varios intervalos son amplios. **Hay que repetir esta auditoría con datos reales** antes de escalar.
- La señal NLP (`prob_fatiga_*`) viene de un modelo multilingüe. Aquí no se encontró brecha por idioma, pero con comentarios reales podría aparecer.
- La API de las Etapas 4 a 6 **no tiene autenticación** y todavía no hay consentimiento de atletas, porque solo se usan datos sintéticos. Ambos se resuelven en la fase de preparación, después de aprobar el proyecto y antes de la prueba de 6 meses con datos reales en una sucursal.
- La sobrecarga es un fenómeno multifactorial (sueño, nutrición, estrés) que el modelo no observa.

## 8. Mantenimiento

- Monitoreo de recall, precisión, PSI y latencia con alertas y runbooks (Etapa 5: `config/monitoreo.yaml`, RB-01 a RB-03).
- Model Registry con alias `champion` y `previous_champion` para hacer rollback. Reentrenamiento con compuerta de staging.
- Nueva auditoría de fairness en cada reentrenamiento y en cada fase del plan de escalamiento (`gobernanza/auditoria_rai.md`).
