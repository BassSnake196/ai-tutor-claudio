# Bloque 4 — Producto docente, persistencia y aislamiento

Fecha: 3 de septiembre de 2026  
Estado: Fase 4.2 parcialmente completada; el contrato API-first de la Fase 4.1 ya está disponible

## Objetivo

Convertir el núcleo API del MVP en una herramienta que un profesor pueda usar de
principio a fin: crear un temario, revisarlo, conservar versiones, descargarlo
en formatos docentes y volver a encontrar sus documentos y trabajos. El bloque
debe conservar la arquitectura actual de agentes, el grounding verificable y la
política `SELECTED → LOCAL_LIBRARY → EXTERNAL`.

El orden es deliberado: primero se fija el contrato de producto y la identidad
de los recursos; después se hace durable la información; luego se añade la
interfaz/exportación; finalmente se incorpora autenticación. Así no se construye
una UI sobre respuestas que no puedan recuperarse, ni se confunde un header con
una identidad autenticada.

## Punto de partida comprobado

- FastAPI expone `/v1/tutor/query`, `/v1/curricula`, documentos y fuentes externas.
- Currículos y citas tienen esquemas Pydantic estrictos; Qdrant usa payload v2,
  procedencia y filtros jerárquicos.
- Los trabajos de ingesta persisten snapshots con SQLite; la ejecución del worker
  continúa siendo process-local y aún requiere leases para varios workers.
- El almacenamiento curricular durable ya tiene una implementación SQLite
  conectada a la API; historial completo, jobs multi-worker, usuarios y
  autenticación todavía no están cerrados.
- `app/core/tenant_context.py` contiene el contrato aislado para `X-Tenant-ID` y
  `X-User-ID`. Es validación de formato, no autenticación y aún no limita rutas.
- El corpus y los reportes del Bloque 3 no deben mezclarse con datos de usuario.

## Alcance por fases y productos finales

### Fase 4.1 — Contrato de producto docente (API-first)

Definir un recurso `CurriculumDocument` independiente de la respuesta transitoria
de generación, con `id`, `tenant_id`, `owner_user_id`, `title`, `status`,
`schema_version`, `curriculum`, `grounding_summary`, fechas y `version`. Añadir
estados explícitos (`DRAFT`, `READY`, `ARCHIVED`) y operaciones idempotentes para
crear, consultar, actualizar metadatos, listar y archivar. La generación debe
devolver el identificador del recurso guardado, sin romper el contrato actual.

Producto: esquemas request/response versionados, OpenAPI actualizado, matriz de
errores (`400`, `401`, `403`, `404`, `409`, `422`) y pruebas de contrato.

### Fase 4.2 — Persistencia durable y versionado (en curso)

Introducir una base relacional local (SQLite para desarrollo, PostgreSQL como
destino) para currículos, versiones, fuentes seleccionadas, jobs y auditoría.
Mantener el contenido grande en almacenamiento de archivos/objeto y guardar en
la base únicamente referencias, hashes y metadatos. Usar migraciones, índices por
`tenant_id`, `owner_user_id`, estado y fecha; nunca depender de memoria de proceso.

Cada guardado debe ser transaccional e idempotente. Una versión publicada es
inmutable; editar crea una nueva versión. Borrar/archivar debe ser lógico para
preservar trazabilidad de citas y permitir recuperación administrativa.

Producto: migraciones reproducibles, repositorios testeables, reinicio sin pérdida
de datos, control de concurrencia y prueba de recuperación desde una copia local.

Implementación actual: la biblioteca usa SQLite configurable, con migración,
índices, transacciones y recuperación entre instancias; el contrato continúa
acotado por tenant/usuario y usa `expected_version`. La siguiente entrega debe
hacer durable la cola de ingesta y completar estados/versiones sin romper este
contrato.

#### Contratos de estado que deben conservarse

El recurso curricular debe exponer un estado persistido explícito: `DRAFT` (se
puede editar y todavía no se presenta como definitivo), `READY` (versión validada
y disponible para exportar/usar) y `ARCHIVED` (no aparece en listados activos,
pero conserva historial y citas). Las transiciones permitidas serán
`DRAFT → READY`, `DRAFT → ARCHIVED` y `READY → ARCHIVED`; reactivar o editar una
versión publicada requiere una nueva versión y una operación explícita. Un
currículo sin grounding suficiente no puede pasar a `READY` automáticamente.

Los jobs de ingesta deben mantener el contrato público actual y agregar
persistencia: `QUEUED → RUNNING → COMPLETED|FAILED`. `FAILED` conserva sólo el
error público sanitizado y su indicador `retryable`; un reintento crea un intento
identificable y no duplica silenciosamente la fuente. Tras reiniciar, un job en
`RUNNING` se recupera como reintentable o `FAILED` con causa operacional; nunca se
debe reportar `COMPLETED` sin resultado íntegro y progreso 100%.

#### Diseño de la entrega durable

1. Crear migración versionada para currículo, versiones, estado, ownership,
   idempotency key y timestamps; agregar tabla de jobs con payload mínimo,
   progreso, error sanitizado, intentos y `lease/updated_at`.
2. Implementar repositorios transaccionales con `BEGIN`, constraints de estado,
   índices por `(tenant_id, user_id, status, updated_at)` y comparación atómica de
   `expected_version`.
3. Recuperar jobs huérfanos mediante lease/timeout; limitar reintentos y asegurar
   idempotencia por `source_id` + operación. La ejecución multimedia no debe
   bloquear las consultas de currículos.
4. Probar primero SQLite con dos instancias secuenciales y luego PostgreSQL con
   workers concurrentes; sólo después sustituir el manager en memoria.

### Criterios detallados de los gates

#### G4.2 — Durabilidad y ciclo de vida

- Una migración limpia crea todas las tablas, índices y constraints sin datos
  implícitos de otro tenant.
- Crear/editar/archivar un currículo y reiniciar la API conserva ID, estado,
  versión, citas, grounding y timestamps; una versión `READY` no se sobrescribe.
- La misma idempotency key devuelve el mismo resultado y no crea duplicados.
- Un job en `QUEUED`, `RUNNING`, `COMPLETED` o `FAILED` puede consultarse después
  del reinicio con el mismo contrato; jobs huérfanos no quedan bloqueados.
- Dos actualizaciones con la misma versión producen una sola escritura y un
  `409`/conflicto para la segunda.

#### G4.4 — Aislamiento tenant/usuario

- Dos tenants con el mismo `curriculum_id`, `source_id` y `job_id` lógico no pueden
  observar ni modificar los datos del otro.
- Cada lectura, escritura, exportación, job, archivo y filtro Qdrant exige el
  scope derivado del contexto; no se acepta un scope tomado del cuerpo como
  autoridad.
- `OWNER`, `EDITOR` y `VIEWER` quedan fuera de implementación hasta auth, pero el
  repositorio debe dejar preparada la distinción entre propietario y lector.
- Las respuestas de recurso inexistente/no autorizado no revelan si existe en
  otro tenant; los logs no incluyen prompt, token, contenido completo ni secretos.
- Las pruebas de integración deben ejecutar una matriz cruzada de tenant, usuario,
  estado y operación (listar, leer, actualizar, archivar, exportar, consultar job).

### Matriz de riesgos de la subfase

| Riesgo | Probabilidad | Impacto | Señal de fallo | Mitigación / criterio de salida |
|---|---:|---:|---|---|
| Job perdido al reiniciar | Media | Alto | `RUNNING` sin resolución | lease, recuperación y prueba G4.2 |
| Duplicación por reintento | Media | Alto | dos fuentes o cargos lógicos | idempotency key y constraint por operación |
| Lectura cross-tenant | Baja/Media | Crítico | fixture visible en matriz cruzada | filtros obligatorios y G4.4 bloqueante |
| Estado inválido (`READY` sin auditoría) | Media | Alto | exportación de borrador no validado | máquina de estados + constraint/test |
| Conflicto de versiones | Media | Medio | último guardado pisa cambios | `expected_version` atómico y `409` |
| Migración rompe contrato | Baja | Alto | OpenAPI/respuestas cambian | snapshot de contrato y adaptador |
| Datos sensibles en errores/logs | Media | Alto | prompt/clave en salida | sanitización, allowlist y revisión de logs |

### Fase 4.3 — Interfaz docente mínima y exportación

Implementar una interfaz delgada sobre la API (no lógica pedagógica duplicada):
formulario de tema/nivel/horas, selección o carga de fuentes, progreso de ingesta,
vista de unidades con citas y advertencias del crítico, edición de borrador,
historial y publicación. La interfaz debe mostrar claramente cuándo el resultado
no está fundamentado y permitir regenerar una unidad, no ocultar el estado.

Exportadores deterministas desde el mismo `CurriculumDocument`: Markdown/HTML
para revisión, DOCX para compartir con profesores y PDF como salida posterior
validada visualmente. El JSON canónico siempre es la fuente de verdad; la
exportación no puede cambiar horas, unidades, citas ni grounding.

Producto: flujo docente completo en entorno local, descarga de JSON/Markdown/DOCX,
snapshot de ejemplo y pruebas que comparen el contenido antes y después de exportar.

### Fase 4.4 — Aislamiento tenant/usuario

Propagar `TenantContext` a cada caso de uso, repositorio, búsqueda Qdrant,
archivos, jobs y logs. Todo punto Qdrant debe incluir filtros obligatorios de
`tenant_id` y, cuando corresponda, `library_id`/`owner_user_id`; el acceso a un
recurso de otro tenant debe responder como `404` o `403` según la política pública.
Los IDs no se interpolan en rutas de archivos ni consultas sin validación.

Producto: pruebas negativas de fuga entre dos tenants y dos usuarios, revisión de
logs sin datos sensibles y una política escrita de propiedad/compartición.

### Fase 4.5 — Autenticación y autorización

Conectar un proveedor de identidad o JWT verificable. El servidor deriva el
usuario y tenant de la credencial; los headers pasan a ser opcionales para
correlación o se rechazan si contradicen el token. Definir roles mínimos
`OWNER`, `EDITOR`, `VIEWER`, rotación/expiración de tokens, revocación y límites
de uso. Esta fase no debe iniciarse como sustituto de las pruebas de aislamiento.

Producto: dependencia FastAPI de autenticación, matriz de permisos, pruebas de
token ausente/expirado/manipulado y documentación de configuración local.

## Distribución multi-agente

Cada agente trabaja en una rama/área aislada y entrega cambios pequeños con tests;
Sol integra, revisa contratos y decide los gates.

- **Luna — contratos y repositorios:** Fase 4.1 y 4.2; esquemas, migraciones,
  repositorios, idempotencia y pruebas de reinicio.
- **Luna — experiencia/exportación:** Fase 4.3; cliente docente mínimo y
  exportadores desde el JSON canónico, con pruebas de paridad.
- **Luna — seguridad de scope:** Fase 4.4; propagación del contexto, filtros
  obligatorios, pruebas de aislamiento y revisión de rutas de archivos.
- **Sol — integración/evaluación:** ejecuta cada gate, revisa diffs, mantiene
  compatibilidad con los agentes RAG/critic, verifica API/Qdrant y autoriza el
  paso a autenticación. La autenticación no se considera completa hasta que
  existan pruebas de aislamiento.

## Gates de aceptación

1. **G4.1 Contratos:** OpenAPI y Pydantic cubren ciclo de vida; compatibilidad del
   endpoint existente; tests verdes.
2. **G4.2 Durabilidad:** levantar, detener y volver a levantar conserva un
   currículo, sus versiones, citas y jobs; migración limpia reproducible.
3. **G4.3 Producto:** un profesor puede generar, revisar, guardar, abrir después
   y exportar sin alterar el JSON canónico; fallos se muestran de forma segura.
4. **G4.4 Aislamiento:** ningún test cruzado puede leer/escribir chunks,
   currículos, archivos o jobs de otro tenant/usuario.
5. **G4.5 Auth:** credenciales válidas/ inválidas y roles tienen resultados
   verificables; sin secretos en repositorio o respuestas.

## Fuera de alcance del bloque

No se cambia el modelo de embeddings/reranker decidido en Bloque 3, no se entrena
un LLM, no se introduce colaboración en tiempo real, facturación ni despliegue
multi-región. Redis/cola distribuida puede sustituir la cola en memoria sólo como
parte de la durabilidad, con el mismo contrato público.

## Checklist de seguimiento

- [x] Contrato inicial `CurriculumLibraryRecord`, versionado optimista y API scoped.
- [x] Persistencia local SQLite, migración automática, índices y repositorio.
- [x] Snapshots de jobs durables y recuperación segura tras reinicio; leases multi-worker pendientes.
- [ ] Interfaz docente mínima conectada a API (la capa backend ya está disponible).
- [x] Exportación JSON/Markdown determinista validada; DOCX/PDF quedan pendientes.
- [ ] `TenantContext` integrado en rutas, Qdrant, archivos y jobs.
- [x] Pruebas de aislamiento tenant/usuario para la biblioteca curricular.
- [ ] Autenticación JWT/proveedor y RBAC.
- [ ] Auditoría, límites de uso y observabilidad por tenant.
- [ ] Actualizar `PROJECT_STATE.md`, `MODEL_REGISTRY.md` y decisiones al cerrar cada gate.

## Retrospectiva estructurada

### Qué funcionó

- Separar el contrato de biblioteca de la respuesta de generación permitió añadir
  guardado, consulta, actualización, archivado y exportación sin alterar los
  agentes curriculares existentes.
- El scope explícito y el control optimista de versión hicieron visibles los
  límites de propiedad antes de introducir autenticación.
- Los tests de aislamiento y exportación detectan fugas y cambios accidentales del
  JSON canónico con poco coste de ejecución.

### Qué falló o quedó limitado

- SQLite sobrevive reinicios locales, pero todavía no coordina varios workers ni
  sustituye la cola de ingesta; por tanto, el gate G4.2 integral sigue abierto.
- La exportación DOCX/PDF y la coordinación multi-worker aún no existen; no se debe
  presentar el MVP actual como producto multiusuario autenticado.
- Los headers `X-Tenant-ID`/`X-User-ID` validan formato y scope, pero no prueban la
  identidad del solicitante. La autenticación sigue siendo una fase separada.

### Decisiones tomadas

- Mantener el JSON curricular auditado como fuente canónica y hacer exportadores
  deterministas desde ese objeto.
- Usar SQLite en desarrollo y dejar PostgreSQL como destino de despliegue, detrás
  de un repositorio común y migraciones versionadas.
- Hacer inmutables las versiones publicadas, usar guardado idempotente y conservar
  borrado lógico para trazabilidad.
- SQLite ya está conectado al arranque actual; no se debe sustituir la cola en
  memoria ni activar autenticación hasta verificar jobs durables y aislamiento
  entre tenants.

### Riesgos abiertos y mitigaciones

- **Pérdida de datos al reiniciar:** migración SQLite y prueba de reinicio de la
  biblioteca ya verificadas; falta cubrir jobs y recuperación completa.
- **Fuga entre tenants:** filtros obligatorios en repositorios/Qdrant y pruebas
  negativas con dos tenants antes de G4.4.
- **Conflictos de edición:** `expected_version`, transacciones y respuesta `409`.
- **Archivos huérfanos o secretos exportados:** hashes, rutas confinadas,
  redacción y prueba de limpieza; no guardar contenido sin referencia.
- **Cambio de contrato durante la migración:** adaptador temporal y comparación de
  OpenAPI antes y después.

### Marcadores de resultados aún inexistentes

- `[COMPLETADO: migración SQLite y prueba de recuperación de biblioteca]`
- `[COMPLETADO: snapshots y recuperación segura de jobs tras reinicio]`
- `[PENDIENTE: leases/reintentos coordinados entre workers]`
- `[PENDIENTE: prueba de paridad después de exportar DOCX/PDF]`

## Estado de esta iteración (3 de septiembre de 2026)

Implementado y probado: biblioteca curricular respaldada por SQLite, aislamiento por
`X-Tenant-ID`/`X-User-ID` como boundary explícito, actualización con
`expected_version`, exportación JSON/Markdown y contratos OpenAPI para crear,
listar, consultar, actualizar, eliminar y exportar. La base se configura con
`CURRICULUM_LIBRARY_DB_PATH` y conserva registros entre instancias. Los jobs usan
`INGESTION_JOBS_DB_PATH` y recuperan estados interrumpidos como fallos reintentables.
La Fase 4.2 integral sigue abierta por leases multi-worker, auditoría y cola durable
distribuida.
