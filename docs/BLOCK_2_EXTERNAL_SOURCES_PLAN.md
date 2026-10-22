# Bloque 2 — Fuentes externas, YouTube y trabajos de ingesta

## Objetivo y orden

Este bloque completa la jerarquía `seleccionados → Qdrant → externo`. El orden elegido
fue contratos, seguridad web, multimedia, integración y pruebas. Así ninguna página o
video entra al contexto antes de existir límites de procedencia, red, tamaño, tiempo y
estado de trabajo.

## Flujo implementado

```text
CurriculumRequest(EXTERNAL_ALLOWED)
  -> buscar source_ids seleccionados
  -> ampliar a library_id/course_id en Qdrant
  -> si la cobertura sigue incompleta: consultas externas concurrentes
       -> búsqueda pública sin API key
       -> página: DNS/SSRF/redirects/tamaño/tipo -> extracción
       -> YouTube: subtítulos públicos -> fallback yt-dlp + faster-whisper
  -> deduplicar y limitar a 12 chunks
  -> guardar evidencia externa aceptada en Qdrant
  -> agentes curricular/didáctico/crítico
```

La ingesta explícita usa trabajos asíncronos en memoria. La respuesta HTTP devuelve
`202` inmediatamente y el docente consulta estado, progreso y resultado por `job_id`.

## Controles de seguridad

- Sólo HTTP/HTTPS; YouTube exige HTTPS y dominios conocidos.
- URLs con credenciales quedan rechazadas.
- Se bloquean IPs privadas, loopback, link-local, multicast, reservadas y no globales.
- DNS se revalida en cada redirección y la conexión queda fijada a la IP validada para
  reducir DNS rebinding.
- Redirects, tiempo total, tamaño descargado y `Content-Type` tienen límites.
- Las fuentes se etiquetan como `UNTRUSTED_EXTERNAL` y nunca se interpretan como
  instrucciones.
- Los errores públicos de trabajos no filtran rutas, excepciones internas ni claves.
- YouTube bloquea playlists, limita duración/tamaño y conserva timestamps por chunk.
- Los archivos cargados sólo se resuelven dentro de `data/videos_audio`.

## Checklist

- [x] Contratos Pydantic WEB, YOUTUBE y FILE_AUDIO.
- [x] Estados QUEUED, RUNNING, COMPLETED y FAILED.
- [x] Gestor asyncio con concurrencia limitada y cierre controlado.
- [x] Conector web con protección SSRF y DNS rebinding.
- [x] Extracción Trafilatura, BeautifulSoup y fallback estándar.
- [x] Búsqueda externa gratuita mediante DDGS.
- [x] Tercera etapa EXTERNAL exclusiva de `EXTERNAL_ALLOWED`.
- [x] Conservación de evidencia local si la consulta externa falla.
- [x] Deduplicación y reevaluación de cobertura después de externo.
- [x] Persistencia de evidencia externa aceptada en Qdrant.
- [x] Subtítulos de YouTube antes de descargar/transcribir.
- [x] Fallback `yt-dlp` y `faster-whisper` local instalados.
- [x] Timestamps y recortes temporales por chunk.
- [x] Carga de audio/video local.
- [x] Endpoints de creación, listado y consulta de trabajos.
- [x] Logs sanitizados y progreso por etapa.
- [x] Pruebas unitarias y smoke tests reales.

## Verificación real

- Página SEP `web-sep-algebra-smoke`: trabajo completado, 23 chunks indexados.
- YouTube `yt-math-antics-algebra-smoke`: subtítulos públicos, rango 0–180 s,
  3 chunks y máximo timestamp exactamente 180 s.
- Resolución posterior: 7 chunks desde `LOCAL_LIBRARY`, cobertura suficiente y ninguna
  nueva salida a Internet.
- Qdrant: estado `green`, cola de actualización vacía, 27 puntos y 3 fuentes.
- Suite: 128 pruebas aprobadas y 2 integraciones opcionales omitidas en la ejecución
  normal; los servicios locales se validaron aparte.

## Limitaciones conscientes

- Los trabajos están en memoria: reiniciar la API pierde su historial. Redis/RQ o una
  tabla persistente será necesario antes de múltiples workers o producción.
- El modelo Whisper se descarga sólo cuando un video/audio carece de subtítulos; esta
  descarga no se fuerza durante el arranque.
- La búsqueda prioriza el texto “fuente educativa oficial”, pero todavía falta una
  puntuación formal de autoridad por dominio y un conjunto de evaluación etiquetado.
- No hay autenticación multiusuario, cuotas por docente ni revisión jurídica de
  licencias/copyright.

## Siguiente bloque recomendado

Medir recuperación en español antes de cambiar modelos: dataset de consultas con
relevancia esperada, comparación Nomic vs BGE-M3, búsqueda híbrida y evaluación del
reranker. Después se puede escoger la mejora con métricas en vez de incrementar RAM y
latencia por intuición.
