# Arquitectura del MVP

## Objetivo

Crear un asistente docente trazable que use recursos locales para routing, búsqueda y validación; y Gemini únicamente para generación pedagógica compleja cuando se configure una clave.

## Flujo

```text
Solicitud del docente
  -> validación y sanitización
  -> router determinístico
  -> [consulta general] proveedor local Ollama
  -> [consulta con fuentes] retrieval Qdrant -> proveedor seleccionado
  -> [temario / actividad compleja] Gemini con salida estructurada
  -> validador Pydantic + validador de citas
  -> respuesta con estado de grounding
```

## Límites de responsabilidad

- `app/ai/interfaces`: contratos independientes de proveedor.
- `app/ai/providers`: implementaciones de Ollama y Gemini, configurables por variables de entorno.
- `app/ai/router`: reglas de clasificación; no decide un LLM por sí mismo.
- `app/rag`: chunking, almacenamiento y recuperación de fuentes.
- `app/agents`: coordinación de las rutas de generación, recuperación y auditoría.
- `app/schemas`: contratos de entrada y salida validados con Pydantic.
- `app/api`: endpoints HTTP sin lógica de IA incrustada.

## Decisiones de seguridad

- Los documentos recuperados son datos no confiables, nunca instrucciones de sistema.
- Solo se permiten URLs HTTP(S) para ingesta web y se deberán restringir las redes privadas antes de habilitar scraping.
- Una respuesta basada en fuentes sin evidencia suficiente debe devolver `INSUFFICIENT_CONTEXT`.
- Las citas deben referirse exclusivamente a identificadores de fragmentos recuperados.
