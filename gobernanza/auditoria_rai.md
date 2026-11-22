# Auditoría de IA responsable de WODPredict-AI (ética, técnica y legal)

**Alcance:** el modelo v1.0.0 y su servicio (API de la Etapa 4, operación de la Etapa 5 y propuesta de la Etapa 6).
**Fecha:** 20-nov-2026.
**Auditor:** autor del capstone.

**Carácter del documento:**
- Es un **análisis académico**, no un dictamen legal.
- Los marcos NIST e ISO se **mencionan y documentan**, no se certifican.
- Todos los datos son **sintéticos**.

**Cómo se lee:**
- Severidad: 🔴 alta (bloquea el escalamiento), 🟠 media (se corrige antes del piloto con datos reales), 🟢 baja (mejora continua).
- Cada hallazgo remite a evidencia del repositorio o de las etapas anteriores.

## 1. Marcos de referencia

| Marco | Uso en esta auditoría |
|---|---|
| **NIST AI RMF 1.0** (2023) | Estructura de la auditoría con sus cuatro funciones: Gobernar, Mapear, Medir y Gestionar (sección 5) |
| **ISO/IEC 42001:2023** (sistema de gestión de IA) | Referencia de controles organizacionales: roles, políticas, ciclo de vida, registros. Se menciona, no se certifica |
| **ISO/IEC 23894:2023** (gestión de riesgos de IA) | Formato del registro de riesgos, conectado con los riesgos R1 a R8 de la Fase I |
| **ISO/IEC 23053:2022** | Marco de ciclo de vida de ML que ya usó el manual de despliegue de la Etapa 4 |
| **Reglamento (UE) 2024/1689, AI Act** | Referencia internacional para clasificar el riesgo. No aplica directamente porque UnderCover Fitness opera en México (sección 4) |
| **LFPDPPP de México** (nueva ley, DOF 20-mar-2025) | Norma aplicable a los datos de salud y rendimiento de los atletas (sección 4) |
| **Actividad 7: IBM SkillsBuild *Project Management Fundamentals*** | Gestión del cambio: un cambio de umbral o de variables entra como *project change request* con aprobación del responsable, y la matriz de roles define quién decide |

## 2. Auditoría ética

| # | Principio | Hallazgo | Evidencia | Severidad | Acción |
|---|---|---|---|---|---|
| E1 | Equidad (igualdad de oportunidad) | **El modelo detecta peor la sobrecarga en atletas élite**: recall de 0.623 (IC 95 % de 0.569 a 0.686) contra 0.799 en novatos. Uno de cada tres atletas élite en riesgo no recibe alerta | `resultados/fairness_resumen.json`, `graficas/fairness_recall_por_grupo.png` | 🔴 | Umbral por nivel (élite 0.10) calibrado solo con entrenamiento: el recall de élite sube a 0.805 y la brecha a 0.070. Requiere la aprobación del responsable del modelo |
| E2 | Equidad y minimización | El **sexo** (atributo protegido) entra al modelo aunque casi no aporta: lugares 25 y 27 de 27 y OR de 0.99 | `resultados/coeficientes_modelo.csv` | 🟠 | Quitar `sex`: recall de 0.731 contra 0.732 y ROC-AUC sin cambio. No hay brecha por sexo con o sin la variable |
| E3 | Equidad | Hay una brecha por edad de 0.098 (el grupo de 31 a 40 años tiene recall de 0.689), pero el intervalo es amplio | idem | 🟢 | Volver a medir con datos reales antes de concluir |
| E4 | Equidad | Sin brecha por idioma (0.003) ni por sexo (0.013) | idem | — | Mantener el monitoreo por grupo |
| E5 | Autonomía humana | El modelo recomienda y el coach decide; las respuestas incluyen una recomendación en lenguaje claro | API: campos `riesgo` y `recomendacion` | 🟢 | Registrar en los logs si el coach siguió o no la alerta, para medir la adopción (riesgo R7) |
| E6 | Transparencia | Hay explicabilidad global (coeficientes) pero no una explicación por predicción para el coach (la Fase I prometió SHAP o LIME, riesgo R3) | `resultados/coeficientes_modelo.csv` | 🟠 | En una regresión logística la contribución exacta de cada variable es coeficiente × valor escalado. Exponer las 3 principales en la respuesta de `/predict` antes del piloto |
| E7 | Carga de falsas alarmas | La mitigación E1 sube las alertas de 24 % a 30 % y baja la precisión de élite a 0.215 | `resultados/fairness_resumen.json` | 🟠 | El coach líder decide el balance. Vigilar la precisión por nivel en el dashboard de la Etapa 5 |

## 3. Auditoría técnica

| # | Área | Hallazgo | Evidencia | Severidad | Acción |
|---|---|---|---|---|---|
| T1 | Trazabilidad | Artefactos con SHA-256, Model Registry con alias, `request_id` y `trace_id` por consulta, semillas fijas. El reentrenamiento reproduce el v1.0.0 con una diferencia de 2e-10 | `modelo/ORIGEN.md`, Etapa 5 `resultados/registry_final.csv`, `fairness_resumen.json` | 🟢 | Agregar el hash del dataset a la ficha del modelo en el registro |
| T2 | Robustez y monitoreo | Hay SLO, alertas por burn rate, drift con PSI y Evidently, y runbooks (Etapa 5) | Etapa 5 `config/monitoreo.yaml` | 🟢 | Agregar recall y precisión **por nivel** como SLI (consecuencia de E1) |
| T3 | Desempeño y SLA | El sistema actual no cumple el SLO de latencia en ráfaga en su perfil de 0.5 vCPU: p99 de 481 ms con 4 clientes. La versión ONNX sí lo cumple (60 ms) | `resultados/bench_contenedores.json` | 🟠 | Desplegar la imagen ONNX (Etapa 6) |
| T4 | Seguridad | **La API no tiene autenticación** y `/admin/*` (Etapa 5) queda expuesto si se publica | README de la Etapa 4, sección Limitaciones | 🔴 | Antes de datos reales: autenticación (Microsoft Entra ID o una clave por box), HTTPS obligatorio (Container Apps ya lo da) y `/admin` solo en la red interna |
| T5 | Calidad de datos | Los datos son sintéticos. El recall con datos reales puede ser distinto | Model card, sección 3 | 🔴 | El piloto valida con datos reales y repite esta auditoría completa (fase 2 del plan) |
| T6 | Eficiencia y sostenibilidad | La inferencia ONNX usa 89 % menos CPU por consulta y la réplica pasa a 0.25 vCPU, con menos cómputo y menos energía para el mismo servicio | `resultados/bench_contenedores.json`, `costos_resumen.json` | 🟢 | — |

## 4. Auditoría legal (análisis, no dictamen)

| # | Norma | Análisis | Severidad | Acción |
|---|---|---|---|---|
| L1 | **LFPDPPP 2025**: datos personales sensibles | El RPE, la fatiga y las notas sobre el estado físico son datos relacionados con la **salud**, por lo tanto **sensibles**. La ley exige consentimiento **expreso y por escrito**, aviso de privacidad, finalidad limitada y seguridad. La autoridad de protección de datos es ahora la Secretaría Anticorrupción y Buen Gobierno, que absorbió las funciones del INAI | 🔴 | Antes del piloto con Wodify: aviso de privacidad integral que mencione el uso de IA, consentimiento expreso de cada atleta, procedimiento de derechos ARCO y cifrado en tránsito y en reposo |
| L2 | LFPDPPP: minimización | Usar `sex` sin necesidad técnica (E2) va contra el principio de proporcionalidad | 🟠 | Quitar la variable (E2) |
| L3 | LFPDPPP: decisiones automatizadas | La decisión final la toma el coach, no el sistema. Hay que confirmar con asesoría legal si alguna obligación sobre tratamientos automatizados aplica a la alerta | 🟢 | Documentar en el aviso que la alerta no produce efectos sin revisión humana |
| L4 | **AI Act** (referencia) | Si se ofreciera en la UE: el caso de uso (carga de entrenamiento deportivo) **no aparece en el Anexo III** de alto riesgo, y el sistema no se presenta como dispositivo médico (no diagnostica ni trata). Probablemente sería de **riesgo mínimo**, con buenas prácticas voluntarias y alfabetización en IA del personal (art. 4). Si la finalidad cambiara a prevención clínica de lesiones, habría que revisar el reglamento de dispositivos médicos | 🟢 | Mantener la finalidad declarada (apoyo al coach) en la documentación y el marketing |
| L5 | Transferencias internacionales | Hoy el despliegue está en Azure México Central, así que los datos se quedan en México | 🟢 | Mantener la región. Si se usa otra, informarlo en el aviso de privacidad |

## 5. NIST AI RMF: dónde está cada función

| Función | Evidencia en WODPredict-AI | Hueco |
|---|---|---|
| **Gobernar** | Roles (matriz de roles de la Actividad 1), política `no_automatizar` (Etapa 5), control de cambios de la Actividad 7 y esta auditoría | Falta nombrar formalmente a quien responde por la privacidad de los datos |
| **Mapear** | Business case y riesgos R1 a R8 (Fase I), uso previsto y fuera de alcance (model card) | — |
| **Medir** | Métricas por grupo con IC (`fairness_por_grupo.csv`), SLO de calidad y latencia, benchmarks de la Etapa 6 | Faltan métricas por nivel en producción (T2) |
| **Gestionar** | Runbooks RB-01 a RB-03, rollback por alias, compuerta de staging y plan de escalamiento (sección 7) | Falta autenticación (T4) |

## 6. Conexión con el registro de riesgos de la Fase I

| Riesgo de la Fase I | Estado tras la auditoría |
|---|---|
| R1 Sesgo algorítmico (crítico) | **Confirmado y medido**: brecha por nivel (E1). Mitigación probada |
| R2 Sesgo por registros incompletos (alto) | Los datos sintéticos no lo reproducen. Se revisa en el piloto (T5) |
| R3 Falta de explicabilidad (crítico) | Parcial: hay explicabilidad global, falta la explicación por predicción (E6) |
| R4 Degradación por drift (alto) | Cubierto por la Etapa 5: PSI, alertas y reentrenamiento con compuerta |
| R5 Incumplimiento normativo de datos de salud (crítico) | Abierto: L1 y T4 se cierran en la fase 1 (preparación) y bloquean el uso con datos reales |
| R6 Lesión por recomendación mal calibrada (alto) | Mitigado por la decisión humana (E5) y el recall por nivel (E1) |
| R7 y R8 (medio y bajo) | Sin cambio. Se registra la adopción (E5) |

## 7. Plan de escalamiento responsable (criterios para pasar de fase)

Cada fase se aprueba solo si se cumplen **todos** sus criterios técnicos, éticos, legales y de costo. Si un criterio falla, la fase no avanza: se corrige o se hace rollback.

| Fase | Alcance | Criterios técnicos | Criterios éticos | Criterios legales | Criterios de costo |
|---|---|---|---|---|---|
| **0. Hoy** (datos sintéticos) | Demo y evidencia académica | Imagen ONNX con p99 < 300 ms en ráfaga ✅ | Auditoría de fairness hecha ✅. E1 y E2 aprobadas por el responsable del modelo el 20-nov-2026 ✅ | Análisis legal hecho (sección 4) ✅ | Estimación de USD 9.65 al mes ✅ |
| **1. Preparación del piloto** (después de aprobar el proyecto y antes de usar datos reales) | Sin atletas reales: el servicio sigue con datos sintéticos | Autenticación de la API y `/admin` solo en red interna (T4). Modelo v1.1.0 sin `sex` y con umbral por nivel (E1, E2), con la misma compuerta de staging de la Etapa 5. Explicación por predicción (E6) | Recall y precisión por nivel en el dashboard (T2, E7) | Aviso de privacidad que mencione la IA, consentimiento expreso y por escrito de cada atleta, y procedimiento de derechos ARCO (L1). Cifrado en tránsito y en reposo | Alerta de presupuesto en Azure Cost Management |
| **2. Piloto** (1 sucursal de UnderCover Fitness, datos reales de Wodify) | 6 meses, grupo controlado. Solo empieza si la fase 1 está completa | SLO de la Etapa 5 durante 28 días | Repetir esta auditoría con datos reales: recall ≥ 0.70 en **cada** nivel y brecha ≤ 0.10 | Solo atletas con consentimiento firmado. Derechos ARCO operando | ≤ USD 15 al mes |
| **3. Red completa** | Todas las sucursales de UnderCover | 2 réplicas mínimas en horario, en zonas distintas (`politicas/autoscaling.yaml`). Recall y precisión por nivel como SLI (T2) | Repetir la auditoría tras cada reentrenamiento. Medir la adopción del coach (R7) | Revisión anual de la privacidad. Registro de incidentes | ≤ USD 30 al mes. Etiquetas de costo por sucursal |
| **4. Crecimiento ×10** (otras redes o franquicias) | Multi-cliente | Prueba de carga con el escenario ×10. `max_replicas` revisado | Auditoría externa de fairness (como prevé la Fase I, USD 1,200 al año) | Contratos de encargado de datos con cada cliente. Revisar el AI Act si hay clientes en la UE (L4) | Costo por consulta ≤ al del piloto. Reservas o planes dedicados solo si el uso es estable |

## 8. Decisiones del responsable del modelo (20-nov-2026)

| # | Decisión | Estado | Cuándo se aplica |
|---|---|---|---|
| 1 | **Quitar `sex` del modelo (E2, L2).** No tiene costo medible (recall 0.731 contra 0.732) y mejora el cumplimiento | ✅ Aprobada | Fase 1: el reentrenamiento genera la versión v1.1.0 |
| 2 | **Umbral por nivel para élite (E1):** élite 0.10 y el resto 0.17, calibrado solo con entrenamiento. Recall de élite de 0.623 a 0.805, con vigilancia de la precisión de élite (E7) | ✅ Aprobada | Fase 1, junto con la v1.1.0. Se revisa con datos reales en la fase 2 |
| 3 | **Autenticación de la API (T4) y consentimiento de atletas (L1)** | ✅ Aprobada como fase posterior a la aprobación del proyecto | Fase 1: después de aprobar el proyecto y antes de la prueba real de 6 meses en una sucursal. Hoy el sistema solo usa datos sintéticos, así que no bloquean este entregable. **Sí bloquean el inicio del piloto con datos reales** |

La versión v1.0.0 sigue siendo la que miden los benchmarks de este repositorio. Las decisiones 1 y 2 cambian el modelo, por lo que pasan por el control de cambios (compuerta de staging y alias `champion` de la Etapa 5) antes de llegar al piloto.
