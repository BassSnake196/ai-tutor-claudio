# Decisión provisional del Bloque 3

Fecha: 2 de septiembre de 2026. Estado: provisional; no autoriza cambios productivos.

## Evidencia disponible

| Brazo | Split | Recall@20 | nDCG@20 | MRR@20 | p95 |
|---|---:|---:|---:|---:|---:|
| Nomic dense | calibration | 0.85 | 0.63 | 0.59 | 1456.6 ms |
| Nomic dense | dev | 0.72 | 0.66 | 0.67 | 1388.1 ms |
| BGE-M3 dense | calibration | 1.00 | 0.77 | 0.72 | 1399.8 ms |
| BGE-M3 dense | dev | 1.00 | 0.81 | 0.78 | 1391.2 ms |

En calibration, la híbrida Nomic alcanzó Recall@5 0.75 y MRR@5 0.684 frente a
dense 0.729/0.585. La híbrida BGE alcanzó 0.646/0.639 frente a dense
0.792/0.731; por ello no se recomienda activarla por defecto.

## Decisiones

- Mantener colecciones experimentales separadas; `tutor_documents` no se reemplaza.
- Tratar Nomic como baseline operativo por disponibilidad local y menor complejidad.
- Mantener BGE-M3 como candidato fuerte de calidad, sujeto a memoria, corpus curado
  y reproducción independiente.
- Mantener sparse/RRF como experimento, no como adopción: el resultado depende del
  modelo y no fue consistentemente superior.
- Calibrar k/threshold offline reutilizando raw top-20. `quality` es pool potencial;
  `context` limita k<=10 por el límite de contexto runtime.
- Mantener prompts y contratos productivos sin cambios durante el benchmark. Los
  hashes, modelo efectivo, fallbacks, repairs, tokens y latencias sí se registran.

## Evaluación curricular

Se evaluaron seis artefactos grabados (tres architecture y tres full) sobre tareas de
calibration. `cur-001` y `cur-006` pasaron los checks principales; `cur-002` falló.
La riqueza didáctica registra campos completos, actividades, preguntas y errores
comunes. Los checks de alineación se separan en estructura y señal léxica diagnóstica.

La variante `observable-v2` se implementó como opción aislada para exigir objetivos
con verbos observables. La ejecución acotada consumió tres llamadas de arquitectura
(`cur-001` calibration y `cur-008`/`cur-010` dev, `NO_SOURCES`); no constituye el A/B
de `cur-002` porque el filtro de selección del CLI escogió `cur-001`. El baseline
productivo se mantiene sin cambios.

## Test sellado ejecutado

Con Docker/Qdrant levantado se ejecutaron los dos brazos pre-registrados (los
primeros intentos fueron rechazados por el daemon apagado y se conservaron como
fallos de infraestructura):

| Brazo | Recall | MRR | nDCG | p95 | Abstención | Fuga |
|---|---:|---:|---:|---:|---:|---:|
| BGE-M3 dense, k=10, t=0.45 | 0.667 | 0.625 | 0.577 | 2234 ms | 0.500 | 0.017 |
| Nomic hybrid, k=5, t=0.35 | 0.750 | 0.458 | 0.550 | 2431 ms | 0.000 | 0.000 |

La comparación queda limitada a seis consultas con qrels en `test`; las otras seis
son no respondibles y se evalúan sólo por abstención. No es un gold humano.

## Reranker real

La corrida offline sobre 24 consultas de calibration (top-20 → 5) ya usa
`BAAI/bge-reranker-v2-m3` con CPU. Frente al baseline BGE-M3, subió Hit@5 de 0.850 a
1.000, MRR de 0.710 a 0.722 y nDCG de 0.711 a 0.767; el coste fue p50 24.0 s y
p95 32.3 s por consulta. Por ese coste y el uso de ~1.3 GB de RAM, se difiere su
activación en producción hasta contar con presupuesto explícito o un modelo
cuantizado.

## Limitaciones

El corpus es pequeño (27 puntos) y los qrels incluyen casos marcados para curación
humana. Las cifras no son un gold humano ni prueban entailment semántico. Retrieval,
grounding, pedagogía y operación deben interpretarse por separado; tampoco se deben
comparar directamente scores Nomic y BGE.

## Verificación operativa

- Suite final: `182 passed, 2 skipped`.
- `smoke_semantic_critic.py`: completó con `UNSUPPORTED` seguro, sin error no
  controlado y con `qwen2.5:3b`.
- `smoke_external_resolution.py`: una etapa `LOCAL_LIBRARY`, 7 chunks, cobertura
  1.0 y sin búsqueda externa requerida.
- Qdrant: `tutor_documents` y `tutor_documents_live_test` green, 27/1 puntos y
  dimensión 768; las colecciones experimentales green con 27 puntos cada una,
  dimensiones 768 (Nomic) y 1024 (BGE).
- Dependencias: `pip check` sin conflictos.
- API live: `/health` respondió `ok` y `/v1/tutor/query` respondió `200` con
  `route=CLOUD`, `intent=pedagogical_generation`, `grounding_status=UNSUPPORTED`
  (sin fuentes solicitadas), latencia 57.9 s y respuesta curricular no vacía.

Artefactos verificables: `data/eval/runs/final_test_bge_dense_k10_t045_retry_qdrant/`,
`data/eval/runs/final_test_nomic_hybrid_k5_t035_retry_qdrant/` y
`docs/evaluation/RERANKER_RESULTS.md`.

## Pendientes bloqueantes

- `[PENDIENTE]` Decidir si el incremento del reranker justifica su coste mediante
  una prueba humana y una alternativa cuantizada; no se activa por defecto.
- `[PENDIENTE]` Curar humanamente qrels y ampliar corpus antes de una conclusión
  estadística fuerte.
- `[PENDIENTE]` Consolidar el reporte operativo final con llamadas, tokens, fallbacks,
  repairs, p50/p95 y errores tipados por corrida.

## Gate de cierre

Sol sólo puede emitir `adoptar`, `rechazar` o `diferir` después de verificar corpus y
labels, reproducibilidad, colección productiva intacta, suite verde, aislamiento de
fuentes, presupuesto de RAM/latencia y el reranker pendiente. Con la evidencia actual,
la decisión es `diferir` cualquier migración productiva: el baseline sigue siendo
válido y los candidatos quedan listos para la siguiente fase de curación humana y
ampliación del corpus.
