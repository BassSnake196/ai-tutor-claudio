# Retrospectiva completa del sistema AI Tutor Claudio

Fecha: 3 de septiembre de 2026

## Objetivo conservado

El producto sigue siendo un asistente para profesores que crea temarios,
explicaciones, actividades y evaluaciones. Puede usar información subida por el
docente, buscar en la biblioteca local y, sólo cuando la política lo permite,
consultar fuentes externas web/YouTube. Las fuentes y sus citas deben permanecer
trazables hasta el chunk original.

## Cómo funciona una consulta

1. FastAPI valida el contrato de entrada y limita el prompt.
2. El router determinista clasifica la intención y decide si requiere fuentes.
3. Para un currículo, `CurriculumOrchestrator` pide evidencia a
   `SourceResolver`, respetando `SELECTED → LOCAL_LIBRARY → EXTERNAL`, filtros de
   biblioteca/curso/estado activo y deduplicación.
4. Qdrant recupera chunks mediante embeddings de Ollama. La colección productiva
   usa `nomic-embed-text`; BGE-M3 sólo se mantiene en colecciones experimentales.
5. El agente arquitecto genera la estructura curricular y el agente didáctico la
   enriquece con explicaciones, actividades y preguntas.
6. El crítico determinista valida esquema, IDs y citas. El crítico semántico local
   puede degradar el veredicto, nunca inventar respaldo.
7. La respuesta devuelve currículo, grounding, trace de fuentes, modelos usados,
   tokens, latencias y advertencias.
8. El docente puede guardar el resultado en `/v1/library/curricula`; el JSON
   validado es la fuente canónica y se exporta a Markdown o JSON sin llamadas LLM.

## Componentes entregados

- **API:** FastAPI, contratos Pydantic estrictos y OpenAPI.
- **Agentes:** router, research/RAG, arquitecto curricular, teaching y critic.
- **RAG:** chunking, catálogo de fuentes, filtros jerárquicos, cobertura,
  procedencia, búsqueda local y fallback externo seguro.
- **Multimedia/web:** ingesta de TXT/PDF/DOCX, páginas web, YouTube y audio; los
  snapshots de jobs se persisten en SQLite y los jobs interrumpidos se recuperan
  como fallos reintentables.
- **Proveedores:** Ollama local para modelos ligeros/embeddings; Gemini con
  `system_instruction` separado, fallback, repair y telemetría sanitizada.
- **Qdrant:** payload v2, estados, IDs de fuente/chunk y colecciones aisladas para
  evaluación.
- **Biblioteca docente:** SQLite configurable por `CURRICULUM_LIBRARY_DB_PATH`,
  IDs opacos, aislamiento por tenant/usuario y versionado optimista.
- **Exportación:** JSON/Markdown determinista, citas y grounding visibles,
  redacción de patrones de secretos.
- **Evaluación:** dataset versionado, calibración, comparación Nomic/BGE/híbrida,
  jerarquías, grounding, prompts y reranker.

## Qué funcionó

- La separación de colecciones evitó contaminar `tutor_documents` al comparar
  modelos de 768 y 1024 dimensiones.
- La política de resolución mantuvo prioridad local y evitó búsquedas externas
  innecesarias; el smoke obtuvo cobertura 1.0 con 7 chunks locales.
- El grounding quedó protegido contra IDs inventados, citas decorativas y prompt
  injection dentro de evidencia.
- El reranker real mejoró nDCG, pero su coste quedó medido y no se ocultó.
- La biblioteca sobrevivió un reinicio de API con SQLite y conservó propiedad,
  versión y contenido.
- La suite final quedó en **208 pruebas aprobadas y 3 omitidas**.

## Qué quedó limitado

- El dataset de evaluación tiene 27 chunks y varias etiquetas requieren curación
  humana; no es todavía un gold estadístico.
- El test sellado favoreció recall a Nomic híbrido y MRR/nDCG a BGE denso, pero no
  justifica migrar producción por el tamaño de muestra.
- `BAAI/bge-reranker-v2-m3` consume aproximadamente 1.3 GB y p95 32.3 s en CPU;
  se difiere hasta disponer de cuantización o presupuesto explícito.
- `X-Tenant-ID` y `X-User-ID` validan scope, no identidad. Aún falta JWT/RBAC.
- SQLite resuelve persistencia local de currículos y snapshots de jobs; aún faltan
  leases, cola distribuida y coordinación multi-worker.
- No existe todavía una interfaz visual docente, DOCX/PDF ni regeneración de una
  unidad desde UI.

## Decisiones actuales

- Mantener Nomic y `tutor_documents` como baseline operativo.
- Mantener BGE-M3, híbrida y reranker como experimentos aislados.
- Mantener el prompt baseline; `observable-v2` queda opt-in hasta un A/B correcto.
- Usar SQLite en desarrollo y dejar PostgreSQL como siguiente destino de escala.
- No integrar autenticación real antes de completar aislamiento en Qdrant, archivos,
  jobs y logs.

## Siguiente orden recomendado

1. Añadir auditoría y mantener historial de versiones inmutables.
2. Añadir leases/reintentos coordinados y probar varios workers.
3. Propagar `TenantContext` a Qdrant, archivos, ingesta y logs.
4. Construir la interfaz docente sobre estos endpoints, sin duplicar lógica de
   agentes.
5. Añadir DOCX y posteriormente PDF con validación visual.
6. Integrar JWT/RBAC y límites de uso.
7. Curar/ampliar el dataset y reevaluar la decisión de retrieval/reranker.

## Estado de operación verificado

- API: `http://127.0.0.1:8000`.
- Swagger: `http://127.0.0.1:8000/docs`.
- Qdrant: `http://localhost:6333/dashboard`.
- Colección productiva: 27 puntos, dimensión 768, estado `green`.
- Colección BGE experimental: 27 puntos, dimensión 1024, estado `green`.
- Ollama: modelos locales disponibles y Gemini configurado mediante `.env` sin
  exponer la clave en código o respuestas.
