# Dataset de evaluación de recuperación en español

## Alcance

`retrieval-es-live-seed` (`data/eval/retrieval/`) es una semilla versionada, no
gold humano ni benchmark estadísticamente representativo. `corpus.v1.jsonl` es
un snapshot payload-only reproducible de los 27 puntos reales de la colección
Qdrant `tutor_documents`, sin vectores. Contiene 23 chunks de SEP álgebra, 3
chunks de YouTube Math Antics en inglés y 1 chunk de pedagogía.

La semilla contiene 48 consultas: 24 `calibration`, 12 `dev` y 12 `test`. Tras el
rebalanceo, `calibration` incluye 18 answerable, 2 ambiguous y 4 unanswerable;
`dev` incluye 9 answerable y 3 unanswerable. Incluye
consultas directas, paráfrasis, relevancia parcial, abstención, fuera de tema,
prompt injection, filtros `UPLOADED_ONLY`, idioma inglés/español, fuga de fuente
y casos `EXTERNAL_ALLOWED` sin gold externo.

Sólo se consideran candidatos los IDs que el validador encuentra en el snapshot.
No se han inventado IDs. Todas las etiquetas de esta ola son
`needs_human_curation`; los qrels son hipótesis de relevancia generadas por
coincidencia textual/temática, no anotaciones humanas.

## Contrato QueryCase.v1

Cada línea de `dataset.v1.jsonl` es JSON con:

- `query_id`, `split`, `query`, `language`.
- `source_policy`: `UPLOADED_ONLY`, `LOCAL_FIRST`, `EXTERNAL_ALLOWED` o `NO_SOURCES`.
- `source_ids`, `library_id`, `course_id`: filtros que debe respetar el evaluador.
- `expected_categories`: categorías esperadas de investigación.
- `qrels`: mapa `chunk_id -> 0|1|2`; 0 irrelevante, 1 parcial, 2 directo.
- `answerability`: `answerable`, `unanswerable` o `ambiguous`.
- `tags`, `annotation_status` y `notes` para auditoría humana.

Un caso `unanswerable` debe tener `qrels` vacío. El validador rechaza IDs no
presentes en el corpus y hashes inconsistentes.

## Validación y hashes

Desde la raíz del proyecto:

```text
python scripts/eval_dataset_validate.py
```

Para regenerar hashes después de una modificación intencional del dataset o
fixture:

```text
python scripts/eval_dataset_validate.py --refresh-hashes
python scripts/eval_dataset_validate.py
```

El manifest fija el hash SHA-256 del JSONL y del snapshot. La validación no
requiere Ollama, Qdrant, red ni modelos; la exportación inicial sí requiere
Qdrant local y se ejecuta explícitamente con:

```text
python scripts/eval_dataset_validate.py --export-live-corpus data/eval/retrieval/corpus.v1.jsonl
```

## Curación pendiente

Antes de comparar Nomic/BGE-M3 o publicar métricas, revisar todas las etiquetas,
incorporar hard negatives, añadir diversidad por fuente y completar qrels para
expansión `LOCAL_FIRST`/`EXTERNAL_ALLOWED`. No ejecutar el split `test` contra
modelos durante esta ola; congelar una versión posterior sólo después de la
curación humana.
