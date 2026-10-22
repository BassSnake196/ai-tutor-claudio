# Secuencia de ejecución — Bloque 1 Curriculum + Qdrant

Este documento convierte el plan arquitectónico en una cola de implementación. El
orden es obligatorio por dependencias: ningún agente generador debe consumir evidencia
hasta que el alcance y la procedencia puedan demostrarse con pruebas.

## Supuestos de trabajo

- El MVP sigue siendo local y de un solo entorno docente.
- `library_id="default"` será el ámbito local mientras no exista autenticación.
- `LOCAL_FIRST` será la política predeterminada.
- Nomic de 768 dimensiones y distancia coseno permanecen sin cambios en este bloque.
- Web y YouTube no se consultan todavía; `EXTERNAL_ALLOWED` sólo dejará una señal
  `external_search_required=true` cuando Qdrant sea insuficiente.
- La generación será síncrona para el MVP. Los jobs en segundo plano pertenecen al
  bloque multimedia.

## Forma final de la API

### Solicitud

```json
{
  "topic": "Álgebra básica",
  "target_level": "Secundaria",
  "duration_weeks": 4,
  "hours_per_week": 3,
  "prior_knowledge": ["Aritmética con números enteros"],
  "desired_outcomes": ["Resolver ecuaciones lineales de una incógnita"],
  "pedagogical_approach": "Aprendizaje basado en problemas",
  "constraints": ["Sin calculadora durante la evaluación"],
  "source_ids": ["algebra-institucional-2026"],
  "library_id": "default",
  "course_id": "matematicas-secundaria",
  "source_policy": "LOCAL_FIRST"
}
```

### Respuesta envolvente

`POST /v1/curricula` devolverá un `CurriculumGenerationResponse`:

- `request_id`;
- `status`: `COMPLETED`, `INSUFFICIENT_CONTEXT` o `PROVIDER_UNAVAILABLE`;
- `curriculum`: `CurriculumResponse` o `null` cuando la política exija evidencia y no
  exista contexto suficiente;
- `grounding_status`;
- `source_trace`;
- `warnings`;
- `models_used` sin credenciales;
- `latency_ms` y latencias por etapa.

Esto permite abstenerse sin fabricar unidades vacías para satisfacer el schema.

### Semántica HTTP

- `200`: ejecución válida, incluyendo `INSUFFICIENT_CONTEXT` como resultado de dominio.
- `404`: un `source_id` seleccionado no existe.
- `422`: solicitud inválida o combinación de política/campos incoherente.
- `503`: todos los proveedores de generación fallaron temporalmente.
- `500`: la salida siguió siendo inválida después de la reparación controlada.

## Ola 0 — Congelar línea base

### Acciones

- Conservar las 13 pruebas actuales como regresión mínima.
- Crear fixtures separados de matemáticas y pedagogía.
- Registrar el estado actual de `tutor_documents` y crear un snapshot de Qdrant antes
  de migrar payloads.
- No borrar `tutor_documents_live_test`; las nuevas pruebas usarán nombres de colección
  aislados por ejecución o limpieza dirigida.

### Puerta de salida

- Suite actual en verde.
- Snapshot creado y restauración documentada.
- Ninguna prueba depende del único punto `pedagogy-api-fixture` existente.

## Ola 1 — Contratos y validaciones

### Archivos previstos

- `app/schemas/curriculum_schema.py`: ampliar unidades y diferenciar borrador/respuesta.
- `app/schemas/source_resolution.py`: políticas, etapas, cobertura y trazas.
- `app/schemas/requests.py`: añadir `CurriculumRequest`.
- `app/schemas/responses.py`: añadir `CurriculumGenerationResponse`.
- `tests/unit/test_curriculum_schemas.py`.

### Decisiones

- `source_ids` se deduplican conservando orden.
- `duration_weeks`: 1–52.
- `hours_per_week`: mayor que 0 y con límite prudente de 40.
- `source_ids` es obligatorio para `UPLOADED_ONLY`.
- `NO_SOURCES` no acepta `source_ids`, para evitar una intención contradictoria.
- `EXTERNAL_ALLOWED` queda admitida aunque todavía no ejecute conectores externos.
- Campos extra quedan prohibidos para detectar errores de escritura del cliente.

### Puerta de salida

- Serialización JSON estable.
- Pruebas de límites, políticas incompatibles y campos extra.
- OpenAPI muestra ejemplos comprensibles en Swagger.

## Ola 2 — Payload Qdrant v2 y catálogo de fuentes

### Archivos previstos

- `app/schemas/sources.py`.
- `app/rag/source_metadata.py`.
- `app/rag/vector_store.py`.
- `app/rag/ingestion.py`.
- `app/api/routes/documents.py`.
- `scripts/migrate_qdrant_payload_v2.py`.
- `tests/unit/test_source_metadata.py`.

### Payload mínimo v2

```text
schema_version, source_id, document_id, library_id, course_id,
title, source_type, language, chunk_index, content_hash,
page_number, timestamp_start, timestamp_end, url,
ingested_at, status, content
```

Los campos que no aplican se guardan como `null` o se omiten consistentemente; los
filtros sólo se aplican a campos normalizados.

### Índices de payload

Crear índices keyword para:

- `source_id`;
- `document_id`;
- `library_id`;
- `course_id`;
- `source_type`;
- `status`;
- `schema_version`.

### Migración no destructiva

1. Crear snapshot.
2. Recorrer puntos con `scroll` sin vectores.
3. Calcular `content_hash` desde `content`.
4. Asignar `library_id="default"`, `status="ACTIVE"` y `schema_version="2"`.
5. Aplicar `set_payload` de manera idempotente.
6. Crear índices.
7. Verificar conteo e IDs antes/después.

No se recreará la colección porque dimensión y distancia no cambian. Cuando se evalúe
BGE-M3 y cambie el tamaño vectorial, se usará una colección nueva y un alias, no una
migración in-place.

### Operaciones de catálogo

- `GET /v1/documents`: listar fuentes agregadas.
- `GET /v1/documents/{source_id}`: metadata y cantidad de chunks.
- `DELETE /v1/documents/{source_id}`: eliminar puntos y archivo, con objetivo exacto.
- La eliminación se probará primero sobre una colección de test.

### Puerta de salida

- El conteo de puntos se conserva durante la migración.
- Cualquier chunk puede trazarse hasta su fuente.
- Un hash repetido genera conflicto controlado o respuesta idempotente, no duplicado.
- Listar y eliminar una fuente tiene pruebas.

## Ola 3 — Filtros y motor de resolución

### Archivos previstos

- `app/rag/filters.py`.
- `app/rag/research_queries.py`.
- `app/rag/coverage.py`.
- `app/rag/source_resolver.py`.
- `app/rag/service.py`.
- `tests/unit/test_source_resolver.py`.
- `tests/integration/test_qdrant_hierarchy_live.py`.

### Consultas de investigación iniciales

El Director generará como máximo cinco consultas controladas:

1. conceptos fundamentales y prerrequisitos;
2. secuencia y progresión apropiada al nivel;
3. errores frecuentes y estrategias didácticas;
4. actividades y práctica aplicada;
5. evaluación formativa e integradora.

Para el primer corte serán plantillas determinísticas construidas desde
`CurriculumRequest`. Esto ahorra una llamada cloud y hace reproducibles las pruebas. Un
Director asistido por SLM sólo se añadirá si las métricas muestran beneficio.

### Resolución

1. Ejecutar consultas en paralelo, filtradas por `source_ids`.
2. Etiquetar cada resultado con categoría y etapa `SELECTED`.
3. Eliminar resultados por debajo de `RAG_MIN_SCORE`.
4. Deduplicar por `chunk_id` y después por `content_hash`.
5. Evaluar cobertura.
6. Si es insuficiente y la política es `LOCAL_FIRST` o `EXTERNAL_ALLOWED`, repetir en
   `library_id/course_id`, excluyendo los `source_ids` ya consultados.
7. Fusionar conservando prioridad de la etapa seleccionada.
8. Limitar el contexto final a 12 chunks y registrar descartes.

### Cobertura inicial configurable

- Categorías requeridas: conceptos, progresión, didáctica y evaluación.
- Una categoría queda cubierta si tiene al menos un chunk relevante.
- Conceptos es obligatoria.
- Baseline suficiente: al menos 3 de 4 categorías y 4 chunks distintos.
- `coverage_score = categorías_cubiertas / categorías_requeridas`.
- El valor será configuración y se calibrará con fixtures; no se tratará como verdad
  universal.

### Resultado de resolución

`EvidenceBundle` contendrá:

- chunks seleccionados y su score;
- categoría de investigación;
- etapa `SELECTED` o `LOCAL_LIBRARY`;
- filtros aplicados;
- fuentes consultadas;
- categorías cubiertas y faltantes;
- `external_search_required`;
- advertencias y contradicciones detectadas.

### Puerta de salida

- `UPLOADED_ONLY` jamás recupera otra fuente.
- `LOCAL_FIRST` se detiene si los seleccionados bastan.
- Si amplía, sólo consulta el ámbito autorizado.
- Los resultados seleccionados mantienen precedencia.
- La ausencia produce una traza explicable.

## Ola 4 — Agentes curriculares y structured output

### Archivos previstos

- `app/agents/research_agent.py`.
- `app/agents/curriculum_agent.py`.
- `app/agents/teaching_agent.py`.
- `app/ai/interfaces/structured_llm.py`.
- `app/ai/providers/gemini.py`.
- `app/ai/curriculum_orchestrator.py`.
- `tests/unit/test_curriculum_orchestrator.py`.

### Cadena de artefactos

1. Research Agent traduce `EvidenceBundle` en hechos, vacíos y restricciones citables.
2. Curriculum Agent usa Gemini para producir estructura, objetivos, secuencia, horas y
   briefs de unidad.
3. Teaching Agent enriquece todas las unidades en una llamada por currículo, sin
   alterar objetivos ni tiempos bloqueados.
4. Cada salida se valida inmediatamente con Pydantic.

No se hará una llamada por unidad: aumentaría latencia y presión sobre la cuota de
Gemini. Las etapas son conceptualmente independientes, pero se agrupan por artefacto.

### Reparación controlada

- Primer intento con response schema.
- Si el JSON no valida, un único intento de reparación recibe errores Pydantic y el
  JSON inválido, sin volver a investigar.
- Si vuelve a fallar, se detiene con error explícito; no se rellenan campos con texto
  inventado.

### Puerta de salida

- Todas las salidas son parseables y sin campos extra.
- Horas y número de semanas respetan la solicitud.
- Cada objetivo se enlaza con actividad y evaluación.
- Las citas sólo usan chunks del `EvidenceBundle`.
- `NO_SOURCES` no genera citas y se etiqueta como no fundamentado.

## Ola 5 — Endpoint, Crítico y entrega

### Archivos previstos

- `app/api/routes/curricula.py`.
- `app/agents/critic_agent.py`.
- `app/main.py`.
- `tests/test_curricula_api.py`.
- `tests/integration/test_curriculum_live.py`.
- `README.md` y ejemplos OpenAPI.

### Auditoría en dos capas

- Determinística: schema, suma de horas, IDs de cita, source policy y correspondencia
  objetivo–actividad–evaluación.
- Semántica local: adecuación del nivel, respaldo de afirmaciones, contradicciones y
  calidad didáctica mediante Qwen local.

El Crítico no reescribe silenciosamente. Devuelve hallazgos; el orquestador puede hacer
una única corrección dirigida si hay errores reparables.

### Puerta de salida end-to-end

- Swagger permite crear un currículo con y sin `source_ids`.
- Dos documentos de dominios distintos demuestran que no existe fuga de fuentes.
- `LOCAL_FIRST` amplía correctamente cuando el documento seleccionado es incompleto.
- `UPLOADED_ONLY` se abstiene sin buscar globalmente.
- Una respuesta final incluye currículo, grounding y traza de resolución.
- Fallos de Gemini devuelven `503`, no una respuesta `200` con texto de error.

## Matriz de escenarios obligatorios

### Contratos

- Petición mínima válida.
- Semanas u horas fuera de rango.
- `UPLOADED_ONLY` sin `source_ids`.
- `NO_SOURCES` con documentos seleccionados.
- Campo desconocido.

### Qdrant

- Documento nuevo.
- Documento duplicado.
- Filtro por fuente.
- Filtro por biblioteca y curso.
- Eliminación completa de una fuente.
- Migración ejecutada dos veces sin cambiar conteos.

### Jerarquía

- Seleccionados suficientes: no amplía.
- Seleccionados insuficientes + `LOCAL_FIRST`: amplía localmente.
- Seleccionados insuficientes + `UPLOADED_ONLY`: se abstiene.
- Qdrant insuficiente + `EXTERNAL_ALLOWED`: marca búsqueda externa pendiente.
- Qdrant vacío.
- Resultados duplicados o por debajo del umbral.

### Curriculum

- Currículo sin fuentes.
- Currículo sustentado por una fuente.
- Currículo con varias fuentes.
- Fuentes contradictorias.
- JSON inválido reparable y no reparable.
- Proveedor temporalmente no disponible.

## Riesgos y controles

- **Biblioteca casi vacía:** cargar al menos dos documentos representativos antes de
  evaluar cobertura; el punto de prueba actual no basta.
- **Latencia de Gemini:** limitar reparaciones y llamadas; conservar fallback entre
  modelos y medir cada etapa.
- **Falsa precisión del umbral 0.35:** calibrarlo con consultas etiquetadas y no subirlo
  o bajarlo por intuición.
- **Aislamiento sólo lógico:** `library_id` no sustituye autenticación; documentar esta
  limitación hasta el bloque multiusuario.
- **PDF escaneado:** no prometer extracción si no tiene capa de texto; OCR queda fuera
  del bloque.
- **Contaminación de pruebas:** usar colecciones dedicadas y limpieza dirigida, nunca
  vaciar la colección principal.

## Checklist de ejecución inmediato

- [x] Ola 0: fixtures separados y snapshots documentados.
- [x] Ola 1: contratos y validaciones.
- [x] Ola 2: payload v2, índices, migración y catálogo.
- [x] Ola 3: filtros, consultas, cobertura y SourceResolver.
- [x] Ola 4: agentes curriculares y structured output.
- [x] Ola 5: endpoint, Crítico, integración y documentación.

Verificación de cierre: 76 pruebas aprobadas, 2 integraciones opcionales omitidas por
marcador, migración idempotente de la colección principal, Qdrant en estado `green` y
smoke test real del crítico local con conteo de tokens de Ollama.

Snapshots previos a la migración conservados por Qdrant:

- `tutor_documents-2548486558963989-2026-08-27-23-32-46.snapshot`;
- `tutor_documents-2548486558963989-2026-08-27-23-33-31.snapshot`.

Antes de una restauración se debe detener la API, crear un snapshot nuevo del estado
actual y usar la operación de recuperación de Qdrant sobre el nombre exacto. Restaurar
reemplaza el estado de la colección y por eso no forma parte de una prueba automática.
