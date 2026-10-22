# Estado actual del proyecto

Fecha de actualización: 3 de septiembre de 2026.

## Núcleo operativo

- FastAPI expone salud, tutor, documentos, currículos y fuentes externas.
- Gemini genera artefactos curriculares estructurados y reporta tokens.
- Ollama ejecuta generación/auditoría local y Nomic produce embeddings.
- Qdrant mantiene payload v2, filtros jerárquicos, catálogo y procedencia exacta.
- La resolución ya ejecuta `SELECTED → LOCAL_LIBRARY → EXTERNAL` según política y
  cobertura, sin gastar tokens cloud durante investigación.
- Las fuentes externas aceptadas pueden persistirse para reutilizarse localmente.
- Web, YouTube y audio se procesan en trabajos asíncronos con progreso y fallos
  sanitizados.

## Seguridad e ingesta externa

- Conector web resistente a SSRF, redirects inseguros y DNS rebinding.
- Límites de tiempo, bytes, tipo de contenido y concurrencia.
- YouTube usa subtítulos públicos primero; `yt-dlp + faster-whisper` son fallback.
- Los chunks multimedia conservan URL y timestamps.
- Todo contenido externo se trata como datos no confiables.

## Calidad verificada

- Suite: pendiente de la verificación final de esta sesión; las pruebas específicas
  de Bloque 3 y las integraciones Gemini ya están verdes en sus corridas previas.
- Web real SEP: 23 chunks indexados.
- YouTube real: 3 chunks del intervalo 0–180 s con timestamps validados.
- Qdrant real: `green`, 27 puntos, 3 fuentes y cola vacía.
- Una segunda resolución reutilizó 7 chunks locales y evitó otra búsqueda externa.
- Se conservan los snapshots anteriores a la migración de payload v2.

## Bloque 3 — evaluación verificable

- Dataset retrieval versionado: 24 consultas calibration, 12 dev y 12 test selladas;
  corpus `corpus.v1.jsonl` y qrels en `dataset.v1.jsonl`.
- Colecciones aisladas verificadas: `tutor_eval_nomic_v1` (27 puntos, dimensión 768)
  y `tutor_eval_bge_m3_v1` (27 puntos, dimensión 1024).
- Raw top-20: Nomic Recall@20 0.85 calibration / 0.72 dev; BGE-M3 1.00 / 1.00.
  No es gold humano: varias etiquetas están pendientes de curación.
- BM25 y RRF fueron evaluados offline; no se adopta híbrida por defecto. Nomic
  híbrido mejoró MRR en calibration, mientras BGE híbrido degradó Recall/MRR.
- Calibración offline de k/threshold reutiliza candidatos raw; perfiles `quality`,
  `context` (k<=10), `balanced` y `abstention` son independientes por modelo.
- Currículo: 12 tareas versionadas y seis artefactos Gemini de calibration comparados
  con validadores estructurales/lexicales diagnósticos y riqueza didáctica.
- Gemini ahora registra modelo efectivo, fallback, repair, tokens, latencia y errores
  tipados sin exponer prompts ni claves. La ejecución acotada observable-v2 consumió
  tres llamadas de arquitectura y no modificó el baseline.
- Test sellado ejecutado: BGE dense k10/t0.45 obtuvo Recall 0.667 y p95 2234 ms;
  Nomic híbrido k5/t0.35 obtuvo Recall 0.750 y p95 2431 ms.
- Reranker real offline: Hit@5 0.850→1.000, nDCG@5 0.711→0.767, pero p50 24.0 s
  y p95 32.3 s; queda diferido por coste.
- API live verificada: `/health` `ok` y `/v1/tutor/query` `200` con Gemini,
  respuesta curricular no vacía y `grounding_status=UNSUPPORTED` cuando no se
  solicitaron fuentes.

## Pendientes y gates

Pendientes: curación humana/ampliación del dataset, prueba humana del reranker y
alternativa cuantizada, unificación de telemetría en reportes finales, leases
multi-worker, interfaz visual, DOCX/PDF y autenticación/RBAC.

## Bloque 4 — Fase 4.2 implementada parcialmente

- Biblioteca curricular API-first bajo `/v1/library/curricula`, ahora respaldada por
  SQLite configurable (`CURRICULUM_LIBRARY_DB_PATH`).
- Aislamiento explícito mediante `X-Tenant-ID` y `X-User-ID`; no se presenta como
  autenticación y se rechazan solicitudes sin scope.
- CRUD con IDs opacos, copias profundas y control optimista `expected_version`.
- Exportación determinista JSON/Markdown sólo para currículos auditados, con citas,
  grounding visible y redacción de patrones de secretos.
- Verificación: 208 pruebas aprobadas, 3 omitidas; smoke live de creación/listado y
  OpenAPI comprobó las tres rutas de biblioteca.
- SQLite aplica migración automática, índices, transacciones y recuperación entre
  instancias; la API lo conecta en el arranque. PostgreSQL queda como destino para
  múltiples procesos/escala.
- Gate de reinicio verificado: un currículo creado por API se recuperó después de
  detener y volver a levantar FastAPI, manteniendo ID, versión y contenido.
- La cola de ingesta usa SQLite configurable (`INGESTION_JOBS_DB_PATH`), conserva
  snapshots y marca `QUEUED/RUNNING` huérfanos como `FAILED/JOB_INTERRUPTED` al
  reiniciar; la ejecución del worker sigue siendo process-local.
- La biblioteca define los estados curriculares `DRAFT → READY → ARCHIVED` con
  archivado lógico; los estados de jobs siguen `QUEUED → RUNNING → COMPLETED|FAILED`.

## Retrospectiva del Bloque 4 hasta ahora

### Qué funcionó

- El contrato API-first permitió aislar biblioteca, ownership, versionado y
  exportación sin cambiar el pipeline de agentes.
- Las pruebas de scope de tenant/usuario y exportación determinista están verdes.

### Qué falló o quedó limitado

- SQLite resuelve reinicio local de biblioteca y snapshots de jobs; aún no cubre
  leases multi-worker ni una cola distribuida.
- DOCX/PDF y autenticación/RBAC aún no están implementados.
- Los headers de scope no son autenticación; sólo validan formato y propiedad
  declarada.

### Decisiones y riesgos

- Se eligió SQLite para desarrollo y PostgreSQL como destino, con migraciones y un
  repositorio intercambiable.
- Las versiones publicadas serán inmutables y las ediciones crearán nuevas
  versiones; el borrado será lógico.
- Riesgos prioritarios: pérdida de datos durante la migración, fuga cross-tenant,
  conflictos concurrentes y archivos huérfanos. Se mitigan con pruebas de reinicio,
  filtros obligatorios, `expected_version`, hashes y rutas confinadas.

### Subfase durable documentada

- G4.2 exige migración limpia, recuperación de currículos y jobs tras reinicio,
  idempotencia, leases para jobs huérfanos y conflictos optimistas reproducibles.
- G4.4 exige una matriz cruzada de tenant/usuario/estado/operación para lecturas,
  escrituras, exportaciones, archivos, jobs y filtros Qdrant; cualquier fuga es
  bloqueante.
- La matriz de riesgos y las transiciones de estado están en
  `docs/BLOCK_4_PLAN.md`; la persistencia de snapshots de jobs ya tiene pruebas,
  pero los leases multi-worker siguen pendientes.

### Resultados pendientes

- `[COMPLETADO: migración SQLite y prueba de reinicio de biblioteca]`
- `[PARCIAL: jobs durables; pendiente coordinación multi-worker/leases]`
- `[PENDIENTE: matriz de aislamiento G4.4 para jobs, archivos y Qdrant]`
- `[PENDIENTE: exportación DOCX/PDF con paridad del JSON canónico]`
- `[PENDIENTE: autenticación verificable y RBAC]`

La retrospectiva completa y el mapa de funcionamiento están en
`docs/RETROSPECTIVE_SYSTEM.md`.

El protocolo, las puertas de aceptación y la distribución de trabajo entre agentes
Luna y Sol están definidos en `docs/EVALUATION_PLAN.md`. La evaluación técnica del
Bloque 3 ya se ejecutó; el siguiente gate es curar el dataset, decidir el reranker y
proponer (en una acción separada) cualquier cambio productivo.
