# Evaluación curricular offline

La Ola 3 evalúa respuestas JSON grabadas con validadores deterministas. No llama a Gemini ni utiliza un juez LLM. `calibration` es el split predeterminado; `test` permanece excluido salvo una bandera explícita.

El registro de cada corrida contiene hashes de prompt, modelo y configuración. Los validadores comprueban schema, horas totales, objetivos observables, número de unidades, alineación actividad-evaluación, campos didácticos, citas autorizadas y límites de conteo.

Las tareas versionadas están en `data/eval/curriculum/tasks.v1.jsonl` y deben conservar sus identificadores y splits.
