# Bloque 3 — Evaluación cuantitativa, búsqueda y agentes

Fecha del plan: 31 de agosto de 2026.

## 1. Objetivo del bloque

Medir con datos reproducibles qué combinación de recuperación, modelos y prompts
produce los temarios más útiles y fundamentados, sin comprometer la jerarquía de
fuentes ni sobrepasar los recursos de una computadora de 16 GB de RAM.

Este bloque no empieza sustituyendo Nomic ni reescribiendo prompts. Primero congela
el comportamiento actual como línea base. Después cambia una sola variable por
experimento y sólo propone llevar a producción una variante cuando los resultados lo
justifiquen.

El producto sigue siendo el mismo: un asistente que ayuda a profesores a crear
temarios y contenido didáctico a partir de:

1. fuentes elegidas explícitamente por el profesor;
2. documentos ya guardados en su biblioteca o curso;
3. fuentes externas web o YouTube cuando la política lo permita y falte cobertura.

## 2. Estado real que recibe este bloque

### Recuperación y datos

- Qdrant está operativo y conserva payload v2, filtros jerárquicos y procedencia.
- La jerarquía `SELECTED → LOCAL_LIBRARY → EXTERNAL` ya funciona.
- La colección viva contiene 27 puntos y 3 fuentes; sirve como prueba funcional,
  pero es demasiado pequeña para extraer conclusiones estadísticas.
- El embedding actual es `nomic-embed-text` mediante Ollama y la búsqueda es densa
  con similitud coseno.
- `rag_min_score=0.35` no ha sido calibrado con consultas etiquetadas.
- BGE-M3 y `BAAI/bge-reranker-v2-m3` están contemplados, pero todavía no forman
  parte del camino real de recuperación.
- BM25/RRF sparse-híbrido ya existe en el harness experimental; el reranker real
  todavía no forma parte del camino de recuperación.
- Las consultas de investigación son deterministas y separan conceptos,
  progresión, didáctica y evaluación. Esto favorece la reproducibilidad.
- La cobertura actual exige conceptos, tres de cuatro categorías y cuatro chunks
  distintos. Es una regla útil, pero puede confundir score vectorial con relevancia
  pedagógica.
- El buscador externo usa un score de posición sintético; ese valor no debe
  compararse ni calibrarse como si fuera similitud coseno.

### Modelos, agentes y prompts

- `RouterAgent` opera con reglas; su prompt documentado no participa en runtime.
- `ResearchAgent` empaqueta evidencia de forma determinista; su prompt tampoco se
  ejecuta.
- La ingesta web, YouTube y documentos es código determinista; no usa el prompt de
  ingestor.
- `CurriculumAgent` usa Gemini con salida estructurada para producir la arquitectura
  del currículo.
- `TeachingAgent` hace una segunda llamada estructurada a Gemini para enriquecer la
  propuesta didáctica.
- `CurriculumCritic` valida IDs y grounding de forma determinista; el crítico
  semántico local sólo puede degradar el veredicto.
- `qwen2.5:3b` es el modelo local activo. No existe todavía una comparación válida
  contra 7B o `phi4-mini`.
- Los prompts son más completos que al inicio, pero sus pruebas actuales verifican
  principalmente estructura y palabras clave, no calidad pedagógica medida.
- El endpoint heredado `/v1/tutor/query` y el flujo estructurado `/v1/curricula`
  tienen contratos distintos y deben evaluarse por separado.

### Línea base verificable

- 128 pruebas aprobadas.
- 2 pruebas de integración opcionales omitidas.
- Qdrant en estado `green`.
- Resolución externa, persistencia y reutilización local ya demostradas.

## 3. Estado de ejecución y pendientes (2 de septiembre de 2026)

Ya existe un harness aislado con manifests, candidatos raw, scores, latencias,
colecciones de evaluación y métricas deterministas. El dataset actual contiene 24
consultas de calibration, 12 de dev y 12 de test selladas para retrieval, además de 12 tareas curriculares
(6 calibration, 4 dev y 2 test). El corpus de retrieval sigue siendo pequeño y sus
labels tienen `annotation_status=needs_human_curation`; por tanto los resultados son
benchmark técnico, no todavía un gold humano.

Resultados disponibles: Nomic raw top-20 obtuvo Recall@20 0.85/0.72 (calibration/dev),
nDCG@20 0.63/0.66 y p95 1456.6/1388.1 ms. BGE-M3 obtuvo 1.00/1.00, nDCG@20
0.77/0.81 y p95 1399.8/1391.2 ms. En híbrida Nomic, Recall@5 fue 0.75 y MRR
0.684 frente a dense 0.729/0.585; en híbrida BGE, Recall@5 fue 0.646 y MRR
0.639 frente a dense 0.792/0.731. Estas cifras no autorizan aún un cambio productivo.

La calibración offline cubre thresholds 0.20–0.90 y k 3/5/10/20 sin volver a
embeber. `quality` es pool potencial; `context` está limitado a k<=10 porque el
runtime limita el contexto a 12. El test sellado ya se ejecutó con Qdrant disponible;
el reranker real mejoró el orden pero quedó diferido por su coste de CPU/RAM.

Resultados del test sellado: BGE-M3 dense k10/t0.45 Recall 0.667, MRR 0.625,
nDCG 0.577 y p95 2234 ms; Nomic híbrido k5/t0.35 Recall 0.750, MRR 0.458,
nDCG 0.550 y p95 2431 ms. Sólo seis casos tienen qrels y el conjunto no es gold
humano.

## 4. Problemas que deben resolverse antes de optimizar

1. El dataset existe, pero requiere curación humana y ampliación a 8–12 fuentes/100+
   chunks antes de llamarse gold.
2. No se puede distinguir todavía si una mejora proviene del embedding, del
   umbral, del prompt, del reranker o de una variación de Gemini.
3. El score denso, el score externo y un futuro score de reranker tienen escalas
   diferentes.
4. El harness ya registra manifests de corpus/modelo/parámetros/hardware/semilla;
   falta unificar esos manifests con los artefactos curriculares y el costo agregado.
5. Validar que un `chunk_id` existe no demuestra que la cita respalde la afirmación.
6. Algunos fallos de proveedor se convierten en texto normal y podrían contaminar
   las métricas si no se tipifican.
7. Los contenidos recuperados están delimitados como evidencia, pero necesitan una
   prueba adversarial explícita contra prompt injection y delimitadores falsos.
8. La colección productiva no debe usarse para comparar dimensiones o modelos.

## 4. Principios del protocolo

- Congelar primero, optimizar después.
- Una variable principal por experimento.
- Usar colecciones Qdrant aisladas; nunca sobrescribir `tutor_documents`.
- Conservar corpus, chunking, IDs, filtros y splits al comparar modelos.
- Ajustar parámetros sólo con `dev`; abrir `test` una vez para el veredicto final.
- Separar métricas de retrieval, grounding, pedagogía, operación y costo.
- No usar al mismo LLM generador como único juez de su propia respuesta.
- Reutilizar embeddings, candidatos y resultados guardados para no repetir costo.
- Cero llamadas a Gemini en las fases puras de recuperación.
- Ningún cambio llega a producción sin la puerta de aprobación de Sol.

## 5. Orden de ejecución y por qué

### Fase 0 — Congelar el contrato experimental

**Qué se hará**

- Registrar versión de código, configuración, hardware, modelos instalados, corpus,
  colección, dimensión, chunking, `top_k`, umbral y semilla.
- Definir esquemas para `QueryCase`, `RelevanceJudgment`, `ExperimentManifest` y
  `RunResult`.
- Congelar la línea base: Nomic, dense-only, `top_k=5`, umbral actual `0.35`, sin
  reranker.
- Definir presupuesto de RAM, latencia, disco y llamadas cloud antes de ejecutar.

**Por qué va primero**

Sin un contrato congelado dos ejecuciones pueden parecer comparables cuando usan
corpus, parámetros o hardware distintos.

**Requisitos**

- Qdrant y Ollama disponibles.
- Inventario del equipo y espacio libre.
- Convención de IDs para datasets, índices, prompts y runs.

**Producto**

- Manifiesto reproducible y criterios de aceptación aprobados.

**Puerta de salida**

- Sol puede reconstruir una ejecución únicamente con su manifiesto.

### Fase 1 — Crear el dataset dorado en español

**Qué se hará**

- Ampliar el corpus de evaluación a un mínimo inicial de 8–12 fuentes y al menos
  100 chunks, sin depender sólo de las tres fixtures actuales.
- Crear 40–60 consultas para la primera versión, estratificadas por:
  - conceptos, progresión, didáctica y evaluación;
  - coincidencia exacta, paráfrasis, sinonimia y términos técnicos;
  - fuente seleccionada, biblioteca local y expansión externa;
  - respuesta completa, evidencia parcial y ausencia de respuesta;
  - duplicados, contradicciones, prompt injection y filtros de curso/biblioteca.
- Etiquetar relevancia graduada por chunk: `0` irrelevante, `1` parcial y `2`
  directa.
- Registrar fuente esperada, categorías esperadas y fuentes prohibidas.
- Separar `calibration/dev/test`, conservando `test` sellado.

**Por qué va antes de cambiar modelos**

Sin etiquetas humanas sólo mediríamos que un modelo devuelve scores, no que recupera
la evidencia correcta para un profesor.

**Requisitos**

- Guía de etiquetado.
- Revisión humana de casos ambiguos; idealmente una segunda revisión parcial por un
  docente.
- Hash de cada dataset y trazabilidad a documento/chunk.

**Producto**

- Dataset JSONL versionado, manifiesto, guía de etiquetado y reporte de cobertura.

**Puerta de salida**

- Todas las consultas tienen juicio de relevancia y no hay solapamiento accidental
  entre los splits.

### Fase 2 — Construir el harness y medir Nomic

**Qué se hará**

- Crear un ejecutor local reproducible que pueda indexar, consultar, medir y emitir
  resultados JSON/CSV/Markdown.
- Medir `Hit@k`, `Recall@k`, `Precision@k`, `MRR@k` y `nDCG@k` para
  `k=1,3,5,10,20`.
- Medir por categoría, política de fuente y tipo de consulta.
- Medir fuga de fuentes, duplicación, diversidad de fuente, abstención correcta,
  p50/p95, RAM pico, tiempo de indexación, disco y throughput.
- Persistir candidatos antes y después de cada filtro.

**Por qué**

Nomic ya está instalado y define el costo y la calidad que cualquier alternativa
debe superar.

**Producto**

- Baseline Nomic reproducible, resultados crudos y reporte de errores.

**Puerta de salida**

- Dos ejecuciones con el mismo manifiesto producen métricas equivalentes y no hacen
  llamadas cloud.

### Fase 3 — Calibrar la lógica actual sin cambiar el modelo

**Qué se hará**

- Barrer `top_k` y umbral en `dev`; la rejilla ejecutada cubre `0.20–0.90` en
  pasos de `0.05`.
- Comparar consulta única contra consultas por categorías y requisitos.
- Medir falsos positivos/falsos negativos de `coverage.sufficient`.
- Exigir `status=ACTIVE` en las pruebas de aislamiento.
- Separar explícitamente umbrales de dense, external, híbrido y reranker.

**Por qué**

Es la mejora potencialmente más barata. Si Nomic mejora con calibración, evita una
descarga grande o reduce el trabajo que se atribuiría erróneamente a BGE-M3.

**Producto**

- Curvas precisión–recall, matriz de cobertura y configuración candidata de Nomic.

**Puerta de salida**

- Los parámetros se eligen con `dev`; `test` sigue cerrado.

### Fase 4 — Comparar Nomic contra BGE-M3

**Qué se hará**

- Instalar BGE-M3 sólo después de aprobar las fases anteriores.
- Implementarlo detrás de la misma interfaz de embeddings.
- Indexar exactamente los mismos chunks en colecciones aisladas, por ejemplo
  `tutor_eval_nomic_v1` y `tutor_eval_bge_m3_v1`.
- Medir dimensión real, carga inicial, RAM, disco, indexación, p50/p95 y calidad en
  español.

**Por qué**

Cambiar embeddings obliga a reindexar y puede elevar mucho RAM/latencia. Su valor
debe demostrarse contra una línea base calibrada, no contra el valor arbitrario
`0.35`.

**Producto**

- Benchmark comparable Nomic/BGE-M3 y recomendación `adoptar/rechazar/diferir`.

**Puerta de salida propuesta**

- BGE-M3 sólo pasa si mejora al menos 5 puntos absolutos de `Recall@5` o 3 puntos
  de `nDCG@5`, no empeora fugas/abstención y cabe en el presupuesto aprobado. Los
  valores son gates iniciales y se confirman al congelar la Fase 0.

### Fase 5 — Búsqueda híbrida y fusión

**Qué se hará**

- Comparar dense-only, sparse/léxica-only y dense+sparse.
- Evaluar RRF o una fusión normalizada conservando por separado `dense_score`,
  `sparse_score` y `fused_score`.
- Probar términos exactos, nombres, fórmulas, siglas y errores ortográficos.
- Validar nuevamente filtros, procedencia y deduplicación.

**Por qué**

Los embeddings semánticos y la búsqueda léxica fallan en casos diferentes; la
fusión puede aumentar recall sin cargar otro generador.

**Producto**

- Ablación dense/sparse/híbrida y fórmula de fusión documentada.

**Puerta de salida**

- Mejora consistente en `dev` sin degradación material del p95 ni del aislamiento.

### Fase 6 — Reranker y umbral posterior

**Qué se hará**

- Aplicar `BAAI/bge-reranker-v2-m3` sólo al top-N recuperado; punto inicial:
  candidatos `20` y salida `5/12`.
- Medir orden antes/después, `nDCG`, MRR, precisión, RAM y latencia incremental.
- Calibrar su score por separado y medir cambios de orden útiles/perjudiciales.

**Por qué**

El reranker es relativamente caro en CPU. Debe ordenar un pool ya bueno; introducirlo
antes ocultaría fallas del recuperador y multiplicaría ejecuciones.

**Producto**

- Decisión de activar, dejar opcional o rechazar el reranker.

**Puerta de salida propuesta**

- Al menos 3 puntos de mejora en `nDCG@5` o MRR con latencia y RAM dentro del
  presupuesto. Si no cumple, se documenta formalmente “no adoptar”.

### Fase 7 — Evaluar prompts, modelos y contratos de agentes

La evidencia recuperada se congela para que esta fase mida generación, no retrieval.

**Qué se hará**

- Crear 12–20 tareas curriculares doradas por nivel, tema, duración y política.
- Medir por separado Router, Curriculum, Teaching y Critic.
- Tratar Router, Research e Ingestor como componentes deterministas; retirar o
  reclasificar sus prompts documentales en vez de atribuirles capacidades no usadas.
- Versionar cada prompt por ID/hash y registrar modelo efectivo, fallback, repair,
  tokens, latencia y error tipado.
- Comparar el prompt actual contra variantes dirigidas:
  - contrato de evidencia más seguro;
  - delimitadores/estructura resistentes a injection;
  - versión compacta;
  - ejemplos sólo donde aporten calidad medible.
- Ejecutar ablaciones controladas:
  - arquitectura sola vs arquitectura + Teaching;
  - brief completo vs evidencia comprimida;
  - crítico determinista vs semántico;
  - thinking `0/512/1024` sólo en candidatos;
  - modelo local 3B y una alternativa sólo si el hardware lo permite.

**Métricas**

- Validez de schema al primer intento y tasa de reparación.
- Cumplimiento de horas y consistencia estructural.
- Alineación objetivo–actividad–evaluación.
- Adecuación al nivel, accesibilidad, claridad y utilidad docente.
- Cobertura didáctica y tasa de campos vacíos.
- Precisión/recall de citas y entailment afirmación–chunk.
- Afirmaciones sin respaldo, citas inventadas y resistencia a injection.
- Tokens, llamadas, fallbacks, p50/p95 y respuestas truncadas.

**Por qué va después de retrieval**

Si la evidencia cambia durante la evaluación del prompt, no sabremos si el resultado
mejoró por redacción o por mejores fuentes.

**Producto**

- Matriz costo/calidad por agente, modelo y versión de prompt.

**Puerta de salida**

- Ningún candidato gana si mejora estilo pero empeora grounding, schema, ataques o
  presupuesto.

### Fase 8 — Prueba end-to-end y decisión

**Qué se hará**

- Elegir como máximo dos configuraciones finalistas.
- Ejecutarlas una vez contra el conjunto `test` sellado.
- Repetir generación sólo lo necesario para estimar variabilidad.
- Ejecutar la suite completa, smokes, salud Qdrant y verificación de colección viva.
- Emitir una decisión `adoptar/rechazar/diferir`, plan de rollback y ADR.

**Por qué va al final**

Evita gastar Gemini y CPU en combinaciones ya descartadas y protege el conjunto de
prueba contra sobreajuste.

**Producto**

- Informe final verificable, configuración elegida y diff de producción propuesto.
  La migración productiva es una acción posterior y separada.

## 6. Plan multiagente de bajo costo

La ejecución usa como máximo tres agentes Luna simultáneos, porque el cuarto espacio
lo ocupa Sol. Los agentes Luna reciben tareas cerradas, archivos exclusivos y una
salida contractual. Sol no implementa tareas mecánicas: congela contratos, revisa
resultados, integra y decide.

### Rol de Sol — `gpt-5.6-sol`

- Organizador, arquitecto del experimento y árbitro de calidad.
- Aprueba manifiestos, schemas, gates, ambigüedades y cambios compartidos.
- Revisa resúmenes, diffs, resultados crudos y fallos, no logs completos repetidos.
- Ejecuta el gate integral después de cada ola.
- Es el único que puede recomendar cambios a runtime, configuración o colección
  productiva.
- Detiene un experimento cuando detecta fuga de datos, comparación inválida,
  métrica defectuosa o costo no justificado.

### Ola 1 — Fundamentos, hasta tres agentes `gpt-5.6-luna`

**Luna A — Dataset y etiquetas**

- Propiedad: `data/eval/**`, `tests/fixtures/retrieval/**` y guía de etiquetado.
- Construye manifest, splits, qrels y validador del dataset.
- No modifica `app/**`.
- Entrega: archivos versionados, hash, cobertura y lista de ambigüedades.

**Luna B — Métricas y reportes**

- Propiedad: `evals/metrics.py`, schemas de resultados y pruebas matemáticas.
- Implementa Hit, Recall, Precision, MRR, nDCG, fugas y abstención.
- Usa fixtures pequeñas conocidas para demostrar cada fórmula.
- Entrega: API estable de métricas y pruebas unitarias.

**Luna C — Runner y telemetría experimental**

- Propiedad: `evals/runner.py`, captura de recursos y reporteros.
- No cambia la búsqueda de producción.
- Entrega: baseline Nomic reproducible y resultados raw.

**Gate Sol 1**

- Revisa que dataset, métricas y runner coincidan y reproduce Nomic.
- No permite BGE-M3 si esta ola no es estable.

### Ola 2 — Alternativas de recuperación

**Luna D — Adaptador BGE-M3**

- Implementa el proveedor experimental y validación de dimensión/finitud.
- Sólo usa colección de evaluación y propone cualquier interfaz compartida como diff
  separado.

**Luna E — Sparse/híbrida**

- Construye candidatos léxicos, fusión y trazas de scores separados.
- Prueba filtros y deduplicación sin tocar la configuración productiva.

**Luna F — Reranker**

- Integra el cross-encoder en el harness sobre un top-N limitado.
- Registra orden, scores, RAM y latencia antes/después.

**Gate Sol 2**

- Verifica que cada brazo use el mismo corpus y labels.
- Descarta resultados no comparables y elige las variantes que llegan a generación.

### Ola 3 — Calidad generativa y robustez

**Luna G — Evals de prompts y contratos**

- Versiona casos dorados y validators de schema, horas y campos.
- Prueba cambios de una variable; no edita prompts productivos durante el benchmark.

**Luna H — Grounding y adversariales**

- Evalúa citas, entailment, evidencia contradictoria, delimitadores e injection.
- Entrega ejemplos concretos de falsos positivos y falsos negativos.

**Luna I — Operación y costo**

- Consolida tokens, llamadas, fallbacks, repairs, latencia y recursos.
- Calcula costo por currículo y detecta errores disfrazados como respuestas.

**Gate Sol 3**

- Selecciona como máximo dos finalistas y autoriza el uso limitado de Gemini sobre
  `test`.

### Cierre Sol

- Ejecuta/verifica el end-to-end sellado.
- Emite ADR, reporte ejecutivo, checklist de regresión y propuesta de adopción.
- No realiza el cambio productivo dentro del mismo experimento.

## 7. Reglas para ahorrar usage limit y recursos

- Modelo de los agentes de implementación: `gpt-5.6-luna`.
- Esfuerzo bajo para datos/documentación mecánica; medio para código y pruebas.
- Hasta tres agentes simultáneos; nunca dos editando el mismo archivo.
- Cada tarea recibe contexto mínimo, contrato, archivos permitidos y condición de
  parada; no se copia toda la conversación.
- Las pruebas específicas se ejecutan durante el desarrollo; la suite completa sólo
  se ejecuta en gates de Sol.
- Retrieval y dataset consumen cero tokens cloud.
- Los embeddings y candidatos se cachean por hash de corpus/modelo/configuración.
- No se ejecutan combinaciones factoriales completas. Se usa ablación de una variable
  y se eliminan candidatos pronto.
- Gemini se usa primero en un conjunto `dev` pequeño y sólo los dos finalistas llegan
  al `test` sellado.
- No se descarga BGE-M3, reranker, 7B o nuevos runtimes antes de medir disco/RAM y
  aprobar su fase.
- Una etiqueta ambigua, un fallo de schema compartido o un cambio en `app/**` se
  escala a Sol; Luna no improvisa decisiones de arquitectura.

## 8. Contrato estándar de entrega de cada agente

Cada agente devuelve únicamente:

1. alcance completado;
2. archivos creados/modificados;
3. comando de reproducción;
4. pruebas ejecutadas y resultado;
5. artefactos raw y hash;
6. riesgos/ambigüedades;
7. recomendación sin cambiar producción.

Esto permite que Sol evalúe productos verificables en vez de rehacer el trabajo o
consumir contexto leyendo razonamientos extensos.

## 9. Criterios globales de aceptación

- `test` permanece sellado hasta la fase final.
- La colección productiva conserva conteo, estado y configuración.
- No hay fuga entre `SELECTED`, `LOCAL_LIBRARY` y `EXTERNAL`.
- Los filtros incluyen estado activo y respetan biblioteca/curso.
- Toda métrica tiene pruebas con ejemplos conocidos.
- Toda ejecución registra corpus, prompt, modelo efectivo, parámetros, semilla,
  hardware y código.
- Scores de naturalezas distintas no se mezclan sin normalización documentada.
- Los errores de proveedor se registran como errores, nunca como respuestas válidas.
- Una mejora de estilo no compensa una pérdida de grounding o seguridad.
- El pico conjunto debe considerar API, Ollama, Qdrant, BGE, reranker y Whisper; no
  se asume que caben simultáneamente en 16 GB.
- La adopción incluye rollback y colección/alias nuevo; nunca reindexación destructiva.

## 10. Producto final del bloque

1. Dataset dorado en español y guía de etiquetado.
2. Harness de evaluación reproducible con pruebas.
3. Colecciones experimentales aisladas y versionadas.
4. Baseline Nomic y benchmark Nomic/BGE-M3.
5. Ablaciones dense/sparse/híbrida/reranker/umbral.
6. Evaluación separada de prompts, agentes y modelos.
7. Reportes JSON/CSV/Markdown con calidad, costo, RAM y latencia.
8. Catálogo de fallos y casos adversariales.
9. ADR con la combinación adoptada, rechazada o diferida.
10. Checklist de regresión, seguridad, rollback y despliegue.

Al terminar este bloque sabremos con evidencia qué recuperar, con qué modelo, cómo
ordenarlo, cuánto cuesta y qué prompts producen un currículo útil. Sólo entonces se
abre el bloque siguiente: interfaz docente, exportación y operación multiusuario
sobre una base ya medida.
