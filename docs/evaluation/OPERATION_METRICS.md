# Métricas operativas

Las corridas deben registrar sólo metadatos sanitizados: modelo efectivo, tipo de operación, estado, latencia, tokens, fallback, repair y tipo de error. Nunca se registran API keys, prompts, respuestas completas ni contenido de fuentes.

`evals.operation_eval.summarize` agrega llamadas, fallbacks, repairs, tokens, latencia p50/p95 y errores tipados. Los eventos se pueden emitir por intento y conservarse junto al manifest de evaluación.
