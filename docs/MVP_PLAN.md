# Plan del MVP

## Alcance incluido

1. API FastAPI con endpoint de salud y endpoint de consulta.
2. Interfaces intercambiables para LLM, embeddings y STT.
3. Registro de modelos mediante configuración.
4. Router determinístico para clasificar consultas simples, con fuentes y generación pedagógica compleja.
5. Esquemas Pydantic para temarios y estados de grounding.
6. Cliente de Ollama y cliente Gemini preparados por configuración.
7. Ingesta mínima de PDF/DOCX/TXT, segmentación y recuperación en Qdrant.
8. Auditoría básica de citas y abstención si falta contexto.
9. Pruebas unitarias del router, esquemas y grounding.

## Fuera del primer incremento

- Descarga automática de videos, transcripción, Redis/RQ, reranking, observabilidad avanzada y autenticación.

## Orden de implementación

1. Instalar runtime y dependencias autorizadas.
2. Crear la base de FastAPI y sus contratos.
3. Implementar router, conectores y validación sin llamadas reales en pruebas.
4. Levantar Qdrant y completar ingesta/RAG.
5. Configurar Gemini y Ollama con credenciales/modelos aportados por el usuario.
