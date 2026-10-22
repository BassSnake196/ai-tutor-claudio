# BGE-M3 — Ola 2, Luna D

## Alcance y aislamiento

Se descargó `bge-m3` con Ollama y se indexó exclusivamente el snapshot
payload-only de `data/eval/retrieval/corpus.v1.jsonl` en la colección nueva
`tutor_eval_bge_m3_v1`. No se leyó ni modificó `tutor_documents` durante la
indexación, y el indexador rechaza destinos que no empiecen con
`tutor_eval_`.

La evaluación ejecutó únicamente `calibration` y `dev` con `k=5` y umbral
`0.35`. El split `test` no fue ejecutado. Las métricas son exploratorias: los
qrels están marcados `needs_human_curation` y no son gold humano.

## Indexación

Artefacto: `data/eval/runs/bge_m3_index.json`.

- Modelo: `bge-m3` vía Ollama.
- Puntos verificados: 27.
- Dimensión: 1024.
- Embeddings: dimensión constante y valores finitos; validación aprobada.
- Tiempo de embeddings: 36 651 ms.
- Escritura/verificación Qdrant: 463 ms.
- Tiempo total: 38 757 ms.
- Medición RSS/disco: no disponible de forma fiable sin dependencia adicional;
  se deja como `null`, sin inventar valores.

## Resultados exploratorios

| Split | Queries | Recall@5 | MRR@5 | nDCG@5 | Precision@5 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| calibration | 24 | 0.7917 | 0.7306 | 0.7167 | 0.2250 | 1288.9 | 1609.9 |
| dev | 12 (5 con qrels positivos) | 0.8000 | 0.7400 | 0.7248 | 0.2400 | 1214.8 | 1517.4 |

Comparación raw existente con Nomic en `data/eval/runs/nomic_calibration_k5_t035`:
calibration obtuvo Recall@5
0.7292, MRR@5 0.5847, nDCG@5 0.6000, Precision@5 0.2083, p50 1107.1 ms y
p95 1345.5 ms. Esta comparación no debe interpretarse como conclusión de
calidad porque los qrels siguen pendientes de revisión humana y el corpus es
pequeño y dominado por un documento SEP.

## Comandos reproducibles

```text
.venv\Scripts\python.exe scripts/eval/index_ollama_collection.py --collection tutor_eval_bge_m3_v1 --model bge-m3 --output data/eval/runs/bge_m3_index.json
.venv\Scripts\python.exe scripts/eval/run_retrieval_eval.py --mode qdrant --cases data/eval/retrieval/dataset.v1.jsonl --output data/eval/runs/bge_m3_calibration_k5_t035 --collection tutor_eval_bge_m3_v1 --model bge-m3 --embedding-model bge-m3 --split calibration --k 5 --threshold 0.35
.venv\Scripts\python.exe scripts/eval/run_retrieval_eval.py --mode qdrant --cases data/eval/retrieval/dataset.v1.jsonl --output data/eval/runs/bge_m3_dev_k5_t035 --collection tutor_eval_bge_m3_v1 --model bge-m3 --embedding-model bge-m3 --split dev --k 5 --threshold 0.35
```

## Hashes y pruebas

- `corpus.v1.jsonl`: `9453bb914c46d41bf919998d1ba95bfcc6bd307ebdf0f522af06584ce3a311c7`
- `dataset.v1.jsonl`: `6924b30dbf49cf52231c04c749ee20ba9c485512f9a9f3cfd347214a8fc2d497`
- `bge_m3_index.json`: generado por el indexador; verificar con `Get-FileHash` antes de distribuir.
- `tests/unit/test_eval_indexing.py`: 3 pruebas aprobadas.

El split `test` se ejecutó posteriormente, de forma sellada y con una colección
experimental aislada; no se cambiaron `app/**` ni la colección productiva.
