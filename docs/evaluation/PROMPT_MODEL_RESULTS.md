# Evaluación generativa de prompts/modelos

El CLI `scripts/eval/generate_curriculum_responses.py` ejecuta tareas de `tasks.v1.jsonl` con `NO_SOURCES` por defecto, bloquea `test`, limita por split/cantidad y opera en modo `architecture` o `full`. `--dry-run` no crea llamadas ni artefactos. La variante `observable-v2` está disponible de forma explícita y no sustituye al baseline hasta superar una comparación válida.

Los artefactos registran hashes de prompts de arquitectura/enriquecimiento, modelo efectivo, tokens, reutilización de arquitectura, latencia y errores tipados; nunca guardan prompts completos ni claves.

## Ejecución acotada 2026-08-31

Se ejecutaron tres llamadas de arquitectura con `observable-v2` y sin teaching: `cur-001` (calibration), `cur-008` y `cur-010` (dev, ambos `NO_SOURCES`). El artefacto de calibration quedó en `data/eval/runs/curriculum_observable_v2_cur002/cur-001.json` por compatibilidad con la corrida inicial; los dev están en `data/eval/runs/curriculum_observable_v2_dev/`. Modelo efectivo: `gemini-3.5-flash`; no hubo fallback ni repair. Los tokens/latencias están registrados por evento en cada JSON.

Nota de control: el filtro `--limit 1` seleccionó `cur-001`, no `cur-002`; por tanto esta ejecución no constituye el A/B solicitado para `cur-002`. No se consume otra llamada automáticamente. El resultado observable-v2 queda como exploratorio y requiere una futura ejecución específica de `cur-002` para comparación válida.
