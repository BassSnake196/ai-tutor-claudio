# Reranker experimental

Modelo: `bge`; casos calibration/dev (test excluido): 24; errores: 0.

| Configuración | Hit@5 | MRR@5 | nDCG@5 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| Baseline bge-m3 top-20→5 | 0.850 | 0.710 | 0.711 | 0.0 | 0.0 |
| Reranked bge top-20→5 | 1.000 | 0.722 | 0.767 | 24020.9 | 32273.3 |

Decisión: `defer` hasta medir recall/latencia/RAM con el modelo real.
