# AI Tutor Claudio

MVP multiagente para generar temarios didácticos estructurados, con resolución
jerárquica de fuentes, Qdrant, Ollama y Gemini.

## Preparación

1. Copia `.env.example` a `.env` y completa únicamente las variables que vayas a usar.
2. Activa el entorno virtual en PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. Inicia la API:

   ```powershell
   python -m uvicorn app.main:app --reload
   ```

4. Abre `http://127.0.0.1:8000/docs`.

## Estado actual

- `GET /health`: comprueba que el backend está activo.
- `POST /v1/tutor/query`: clasifica la petición y selecciona ruta local, cloud o RAG.
- `POST /v1/documents`: recibe archivos TXT, PDF o DOCX (máximo 20 MB), los segmenta y los indexa en Qdrant.
- `GET /v1/documents`: lista las fuentes y su procedencia; el detalle y eliminación
  están en `GET/DELETE /v1/documents/{source_id}`.
- `POST /v1/documents/search`: recupera los fragmentos más cercanos semánticamente.
- `POST /v1/curricula`: resuelve evidencia y ejecuta los agentes de arquitectura,
  didáctica y crítica para devolver un temario validado.
- `POST /v1/external-sources`: encola una página web o video de YouTube para ingesta.
- `POST /v1/external-sources/audio`: carga audio/video local para transcripción.
- `GET /v1/external-sources/jobs/{job_id}`: consulta progreso y resultado sin bloquear
  la petición HTTP.
- Las preguntas con `requires_sources=true` recuperan contexto, responden con Qwen local y devuelven citas verificables.
- La ruta local usa Ollama. La ruta cloud se activa al configurar una clave de Gemini.

## Probar el currículo

Para una propuesta sin fuentes, que siempre queda marcada como `UNSUPPORTED`:

```json
{
  "topic": "Suma de fracciones",
  "target_level": "Secundaria",
  "duration_weeks": 2,
  "hours_per_week": 2,
  "source_policy": "NO_SOURCES"
}
```

Para usar sólo un documento subido, cambia la política a `UPLOADED_ONLY` y agrega su
`source_id`. Si los documentos no alcanzan la cobertura mínima, el endpoint responde
`INSUFFICIENT_CONTEXT` sin llamar a Gemini ni consumir tokens de generación. Con
`LOCAL_FIRST`, el sistema amplía a la biblioteca y curso autorizados. Consulta
`source_trace`, `models_used`, `token_usage` y `stage_latencies` para auditar la
decisión y el costo de cada ejecución.

Con `EXTERNAL_ALLOWED`, la prioridad completa es:

```text
source_ids seleccionados -> Qdrant autorizado -> web/YouTube público
```

Internet sólo se consulta si las dos primeras etapas no alcanzan la cobertura. Las
páginas aceptadas pueden guardarse en Qdrant para que la siguiente solicitud las use
localmente.

## Ingresar una fuente externa

Ejemplo web en `POST /v1/external-sources`:

```json
{
  "source_type": "WEB",
  "source_id": "algebra-sep",
  "url": "https://aprendeencasa.sep.gob.mx/secundaria/algebra/",
  "library_id": "default",
  "course_id": "matematicas-secundaria",
  "language": "es"
}
```

Para YouTube usa `source_type: "YOUTUBE"`. El sistema intenta primero subtítulos
públicos; sólo descarga audio y usa `faster-whisper` cuando no existen. `start_time_seconds`
y `end_time_seconds` permiten limitar el fragmento. La respuesta `202` contiene un
`job_id` que se consulta en `GET /v1/external-sources/jobs/{job_id}`.

Errores esperados: `404` si una fuente seleccionada no existe, `422` si la política
contradice los campos y `503` si Gemini no puede generar el currículo.

## Servicios locales

```powershell
docker compose up -d qdrant
```

Modelos esperados en Ollama: `qwen2.5:3b`, `qwen2.5:7b`, `phi4-mini` y `nomic-embed-text`.
El modelo `small` de faster-whisper se descarga de forma perezosa la primera vez que
un audio realmente requiere transcripción.

Detalles y checklist: [`docs/BLOCK_2_EXTERNAL_SOURCES_PLAN.md`](docs/BLOCK_2_EXTERNAL_SOURCES_PLAN.md).
