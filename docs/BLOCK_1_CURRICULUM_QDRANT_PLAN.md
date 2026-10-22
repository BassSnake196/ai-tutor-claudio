# Bloque 1 — Curriculum y resolución jerárquica en Qdrant

La secuencia concreta por archivos, puertas de calidad, migración y escenarios de
prueba está en [`BLOCK_1_EXECUTION_PLAN.md`](BLOCK_1_EXECUTION_PLAN.md).

## Resultado buscado

Crear un flujo `POST /v1/curricula` que genere un temario didáctico estructurado y
trazable para un profesor. La recuperación seguirá esta prioridad:

1. documentos que el profesor seleccionó expresamente;
2. biblioteca local autorizada en Qdrant;
3. fuentes externas, únicamente en un bloque posterior y cuando la política lo permita.

Al terminar este bloque, internet y YouTube todavía no se descargarán. Sin embargo, el
contrato y el historial de resolución quedarán preparados para añadir ese tercer nivel
sin cambiar el endpoint curricular.

## Decisiones de alcance

- `UPLOADED_ONLY`: usa exclusivamente `source_ids` seleccionados; si no bastan, se
  abstiene.
- `LOCAL_FIRST`: usa primero `source_ids`; después amplía a la biblioteca Qdrant
  autorizada. Será la política predeterminada.
- `EXTERNAL_ALLOWED`: tendrá el mismo comportamiento local durante este bloque y
  marcará que una etapa futura puede consultar web/YouTube.
- `NO_SOURCES`: permite una propuesta pedagógica basada en el modelo, identificada
  explícitamente como no fundamentada.
- Los documentos y chunks son datos no confiables. Nunca pueden reemplazar prompts de
  sistema ni ordenar acciones al modelo.
- No se mezclan fuentes fuera de `library_id`, `course_id` o `source_ids` permitidos.

## Flujo del bloque

```text
CurriculumRequest
  -> validación de campos y política
  -> Director crea preguntas de investigación
  -> SourceResolver
       etapa A: source_ids seleccionados
       evaluar cobertura
       etapa B: biblioteca Qdrant autorizada
       deduplicar + ordenar + limitar contexto
  -> EvidenceBundle
  -> Curriculum Architect genera CurriculumDraft estructurado
  -> Teaching Agent enriquece unidades
  -> Critic valida esquema, alineación y citas
  -> CurriculumResponse + SourceResolutionTrace
```

## Entregable 1 — Contratos del dominio curricular

### Trabajo

- Crear `CurriculumRequest` con:
  - `topic`;
  - `target_level`;
  - `duration_weeks`;
  - `hours_per_week`;
  - `prior_knowledge`;
  - `desired_outcomes`;
  - `pedagogical_approach` opcional;
  - `constraints`;
  - `source_ids`;
  - `library_id` y `course_id` opcional;
  - `source_policy`.
- Separar `CurriculumDraft` de `CurriculumResponse`: el borrador no debe afirmar que
  está respaldado antes de pasar por el Crítico.
- Añadir `SourceResolutionTrace` con etapas consultadas, filtros, cantidad recuperada,
  cobertura y razón de detención.
- Ampliar las unidades con prerrequisitos, resultados, conceptos esenciales, errores
  frecuentes, actividad guiada, actividad autónoma, evaluación formativa, evidencia de
  aprendizaje y tiempo.

### Criterios de aceptación

- Una petición mínima válida requiere tema, nivel, duración y horas.
- Pydantic rechaza duraciones, horas o identificadores inválidos.
- La política determina de forma inequívoca si puede ampliarse la búsqueda.
- El schema generado puede convertirse a JSON sin campos abiertos o ambiguos.

### Razón del orden

Qdrant, los agentes y el endpoint necesitan compartir un mismo lenguaje. Diseñar este
contrato primero evita filtros improvisados y respuestas imposibles de validar.

## Entregable 2 — Catálogo y metadatos de fuentes

### Trabajo

- Extender el payload de cada punto Qdrant con:
  - `source_id`, `document_id`, `library_id`, `course_id`;
  - `title`, `source_type`, `language`;
  - `chunk_index`, `page_number`, `timestamp_start`, `timestamp_end`;
  - `url`, `content_hash`, `ingested_at`, `status` cuando correspondan.
- Calcular `content_hash` para evitar duplicados.
- Crear índices de payload para `source_id`, `library_id`, `course_id`, `source_type` y
  `status`.
- Añadir endpoints para listar fuentes, consultar una fuente y eliminar sus puntos.
- Mantener los archivos originales en `data/raw_documents` y los vectores en
  `data/qdrant_storage`.

### Criterios de aceptación

- Se puede identificar de qué documento salió cualquier chunk.
- Un documento repetido no crea una segunda copia silenciosa.
- El sistema puede listar y eliminar una fuente completa por `source_id`.
- Los filtros no dependen de buscar texto dentro del payload.

### Razón del orden

La jerarquía no puede respetarse con el payload actual porque sólo existen datos
básicos y no hay índices de filtrado. Primero se debe volver consultable la procedencia.

## Entregable 3 — Búsqueda filtrada y resolución jerárquica

### Trabajo

- Ampliar `QdrantVectorStore.search` para aceptar filtros inclusivos y exclusivos.
- Crear `search_many` para ejecutar varias preguntas de investigación y deduplicar por
  `chunk_id`.
- Crear `SourceResolver` con etapas explícitas:
  1. buscar dentro de `source_ids`;
  2. calcular cobertura;
  3. si la política lo permite y falta cobertura, buscar en `library_id/course_id`;
  4. fusionar sin duplicados y conservar la etapa de procedencia.
- Generar consultas separadas para:
  - conceptos y prerrequisitos;
  - progresión y secuencia;
  - errores frecuentes y estrategias didácticas;
  - actividades y evaluación;
  - requisitos curriculares cuando existan fuentes para ellos.
- Introducir un `EvidenceBundle` con chunks, puntuaciones, fuentes, vacíos y
  contradicciones.
- Mantener inicialmente embeddings Nomic y distancia coseno. BGE-M3 y reranking se
  evaluarán después con métricas comparables.

### Criterios de aceptación

- `UPLOADED_ONLY` nunca devuelve chunks de otro `source_id`.
- `LOCAL_FIRST` sólo amplía la búsqueda cuando la primera etapa es insuficiente.
- Las fuentes seleccionadas tienen prioridad sobre resultados globales equivalentes.
- Cada resultado conserva score, filtro, etapa y metadatos para auditoría.
- Una ausencia real produce `INSUFFICIENT_CONTEXT`, no una respuesta inventada.

### Razón del orden

La recuperación debe ser confiable antes de pedirle al modelo que redacte. De lo
contrario, un buen prompt sólo maquillaría evidencia mezclada o irrelevante.

## Entregable 4 — Generación curricular estructurada

### Trabajo

- Crear `POST /v1/curricula`.
- El Director transforma la solicitud en plan y consultas de investigación.
- El Diseñador Curricular recibe parámetros y `EvidenceBundle`, y genera JSON con el
  schema de `CurriculumDraft` mediante structured output de Gemini.
- El Generador Didáctico enriquece las unidades sin alterar objetivos ni horas.
- Validar con Pydantic después de cada agente; un JSON inválido no pasa a la siguiente
  etapa.
- Guardar modelo utilizado, supuestos y fuentes empleadas en la respuesta.

### Criterios de aceptación

- El endpoint siempre devuelve JSON estructurado o un error explícito y accionable.
- La suma y distribución de horas respetan la solicitud.
- Cada objetivo tiene al menos una actividad y una evaluación alineadas.
- Cada unidad contiene contenido aplicable por un profesor, no sólo títulos.
- Una propuesta sin fuentes se etiqueta como no fundamentada y no inventa citas.

### Razón del orden

Con contrato y evidencia estables, el modelo puede concentrarse en diseño pedagógico
sin decidir por su cuenta qué fuentes tenía permitido usar.

## Entregable 5 — Auditoría, pruebas y observabilidad

### Trabajo

- Ampliar el Crítico para validar afirmaciones contra los chunks exactos.
- Comprobar que cada cita corresponde a una fuente recuperada y sostiene el texto.
- Auditar alineación objetivo–actividad–evaluación, nivel, tiempos y contradicciones.
- Crear pruebas unitarias para políticas, filtros, cobertura y schemas.
- Crear pruebas de integración con dos documentos deliberadamente separados para
  demostrar que no hay fuga entre `source_ids`.
- Registrar latencia por etapa, modelo, consultas, puntos recuperados y decisión de
  ampliar o detener la búsqueda.

### Criterios de aceptación

- El Crítico puede devolver `SUPPORTED`, `PARTIALLY_SUPPORTED`,
  `INSUFFICIENT_CONTEXT`, `UNSUPPORTED` o `CONTRADICTORY_SOURCES` con una causa.
- Ninguna cita puede apuntar a un chunk no recuperado.
- Las pruebas demuestran aislamiento de fuentes y jerarquía.
- Los logs no contienen API keys ni el vector completo.

## Checklist del bloque 1

### Ya disponible

- [x] FastAPI y configuración por entorno.
- [x] Ollama local y Gemini con fallback.
- [x] Prompts especializados de los seis agentes.
- [x] Ingesta básica de TXT, PDF y DOCX.
- [x] Chunking con solapamiento.
- [x] Embeddings Nomic de 768 dimensiones.
- [x] Colección Qdrant con distancia coseno.
- [x] Búsqueda semántica básica y citas por `source_id`/`chunk_id`.
- [x] Schema inicial `CurriculumResponse`.

### Implementado en este bloque

- [x] Crear `CurriculumRequest`, `CurriculumDraft` y `SourcePolicy`.
- [x] Añadir `SourceResolutionTrace` y `EvidenceBundle`.
- [x] Completar metadata y hashes de documentos.
- [x] Crear índices de payload en Qdrant.
- [x] Añadir filtros por fuente, biblioteca, curso, tipo y estado.
- [x] Implementar búsqueda por múltiples consultas y deduplicación.
- [x] Implementar medición de cobertura.
- [x] Implementar `SourceResolver` jerárquico.
- [x] Crear endpoints para listar, inspeccionar y eliminar fuentes.
- [x] Crear `POST /v1/curricula`.
- [x] Conectar structured output de Gemini con Pydantic y reparación limitada.
- [x] Separar borrador curricular y enriquecimiento didáctico.
- [x] Integrar Crítico determinístico y auditor semántico local al flujo real.
- [x] Añadir pruebas de aislamiento, jerarquía y citas.
- [x] Añadir logs y telemetría por etapa sin secretos.
- [x] Documentar ejemplos de Swagger y errores esperados.

### Pendiente del sistema maestro después de este bloque

- [ ] Evaluar BGE-M3 contra Nomic con un conjunto de consultas en español.
- [ ] Integrar `bge-reranker-v2-m3` si mejora la precisión de forma medible.
- [x] Crear conector web seguro con protección SSRF y priorización educativa.
- [x] Integrar YouTube con subtítulos públicos y fallback `yt-dlp`.
- [x] Transcribir con `faster-whisper` y conservar timestamps.
- [x] Procesar ingestas largas en segundo plano para el MVP local.
- [ ] Añadir autenticación y aislamiento real por usuario/organización.
- [ ] Construir interfaz para profesores.
- [ ] Añadir exportación de temarios y observabilidad operativa.

## Estado actual de Qdrant verificado

- Servicio: `ai-tutor-qdrant`, activo.
- Colección principal: `tutor_documents`, estado `green`.
- Configuración: vectores de 768 dimensiones, distancia `Cosine`.
- Datos actuales: 1 punto en la colección principal.
- Las pruebas nuevas crean colecciones únicas y las eliminan al terminar; una colección
  histórica `tutor_documents_live_test` puede seguir visible hasta que se decida
  retirarla expresamente.
- Almacenamiento persistente local: `data/qdrant_storage`.
- Payload principal migrado a `schema_version=2` y nueve índices verificados.

Que `indexed_vectors_count` sea 0 mientras `points_count` es 1 no representa un error:
la colección está por debajo del umbral de indexación y Qdrant puede recorrer esos
pocos puntos directamente.

## Cómo inspeccionar los datos

1. Abrir `http://127.0.0.1:6333/dashboard`.
2. Entrar en **Collections**.
3. Seleccionar `tutor_documents`.
4. Abrir la vista de puntos/datos para ver ID, payload y vector.

El payload legible contiene `chunk_id`, texto, `source_id`, título, tipo y posición.
El vector es una lista de 768 números; normalmente se oculta porque no resulta útil
leerlo manualmente.

También puede usarse la API REST:

```powershell
Invoke-RestMethod http://127.0.0.1:6333/collections
Invoke-RestMethod http://127.0.0.1:6333/collections/tutor_documents

$body = @{ limit = 10; with_payload = $true; with_vector = $false } | ConvertTo-Json
Invoke-RestMethod `
  -Uri http://127.0.0.1:6333/collections/tutor_documents/points/scroll `
  -Method Post `
  -ContentType 'application/json' `
  -Body $body
```

No se deben editar manualmente los archivos binarios de `data/qdrant_storage`. Qdrant
debe leer y modificar ese directorio mediante su API o dashboard.
