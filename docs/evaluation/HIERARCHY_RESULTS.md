# Evaluación de jerarquía y políticas (Ola 3, Luna H)

## Alcance

Esta evaluación ejercita `SourceResolver` con backends deterministas en memoria. No modifica `app/**`, no usa Gemini y no ejecuta el split `test`. El objetivo es medir el contrato observable de la secuencia `SELECTED → LOCAL_LIBRARY → EXTERNAL`, incluyendo sus políticas de fuente y sus fallos de seguridad. Los resultados no son una medición de calidad semántica ni un conjunto de etiquetas humanas.

Archivos del arnés:

- `evals/hierarchy_eval.py`: fixtures, backends fake, ejecución y métricas.
- `scripts/eval/run_hierarchy_eval.py`: nueve escenarios reproducibles.
- `tests/unit/test_hierarchy_eval.py`: pruebas unitarias del contrato.

## Escenarios cubiertos

Se incluyen: selected suficiente; selected insuficiente con expansión local; `UPLOADED_ONLY` insuficiente sin expansión; external permitido; fallo parcial de external; external requerido pero no disponible; payload inactivo (`DELETED`, representación válida del estado no activo); el mismo chunk en varias consultas; cobertura falsa; y fuga de fuente en SELECTED.

La cobertura falsa y la fuga son casos adversariales intencionales: permiten comprobar que el evaluador las reporta, no que la implementación actual las resuelva automáticamente. `inactive_accepted` también es una alarma deliberada para verificar que un backend fake malicioso no quede oculto.

## Métricas

Cada caso registra:

- `stages` y `stop_stage`: etapas ejecutadas y última etapa observada.
- `source_leakage`: un chunk devuelto en SELECTED cuyo `source_id` no pertenece a los `source_ids` pedidos.
- `expansion_unnecessary`: expansión posterior a una etapa cuya cobertura ya era suficiente.
- `false_coverage`: la cobertura interna dice suficiente, pero no hay intersección con los IDs relevantes declarados por el caso.
- `inactive_accepted`: apareció un payload cuyo estado no es `ACTIVE`.
- `external_required` y `external_executed`: señales del trace y evidencia de ejecución de la etapa external.
- `duplicate_count`: duplicados reportados por el resolver.
- `latency_ms`: tiempo extremo a extremo del caso, incluyendo el arnés fake.

`external_required` no significa que el proveedor haya respondido correctamente; se conserva exactamente la señal del trace actual. Los fallos parciales se observan mediante `external_executed` y no se convierten en una afirmación de disponibilidad externa.

## Ejecución y resultado reproducible

```text
.venv\Scripts\python.exe -m pytest tests/unit/test_hierarchy_eval.py -q
6 passed (aprox. 0.35s)

.venv\Scripts\python.exe scripts/eval/run_hierarchy_eval.py
```

La corrida del script produjo 10 casos: 7 limpios según las alarmas del arnés, 1 payload inactivo aceptado, 1 cobertura falsa y 1 fuga de fuente. Las latencias fake fueron 0–1 ms; no deben interpretarse como latencia de Qdrant, Ollama o internet. El caso `same-chunk-dedup` reportó `duplicate_count=1`. Los casos de external llegaron a `EXTERNAL`; el caso sin conector marcó `external_required=true` y `external_executed=false`; `UPLOADED_ONLY` permaneció en `SELECTED`.

No se ejecutó smoke live contra `tutor_eval_bge_m3_v1`: esta ola queda determinista y reproducible sin depender de servicios activos. Si se añade ese smoke, debe limitarse a dicha colección de evaluación y registrar disponibilidad, latencia y errores por separado.

## Criterios de aceptación para la siguiente iteración

1. Los escenarios de política deben conservar su etapa de parada esperada.
2. Cualquier fuga de fuente, estado no `ACTIVE`, expansión innecesaria o cobertura falsa debe aparecer como alarma explícita.
3. La ejecución external debe distinguir “permitida”, “requerida por el trace”, “ejecutada” y “fallida”.
4. Un smoke live debe usar únicamente la colección `tutor_eval_*`; nunca `tutor_documents`.
5. Las métricas de recuperación (Recall/MRR/nDCG) deben provenir del dataset de retrieval y no mezclarse con estas métricas de política.
