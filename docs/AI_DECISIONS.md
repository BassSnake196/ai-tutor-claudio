# Decisiones de IA

## ADR-001 — MVP incremental

**Problema:** El repositorio no contiene una implementación previa, aunque el diseño conceptual describe seis agentes.

**Decisión:** Implementar primero router + herramientas + RAG + proveedores intercambiables; los agentes serán servicios especializados, no procesos autónomos.

**Por qué:** Es verificable en un equipo de 16 GB y evita complejidad prematura. Los flujos que requieran planificación de múltiples pasos se añadirán tras medir el MVP.

**Costo:** Sin consumo cloud hasta configurar Gemini y enviar una solicitud compleja.

## ADR-002 — Abstención basada en evidencia

Una respuesta basada en fuentes devuelve `INSUFFICIENT_CONTEXT` si no hay fragmentos suficientes. Las citas solo pueden usar IDs recuperados.

## ADR-003 — Configuración mediante entorno

URLs, claves y modelos se configuran en `.env`, que no se versiona. Así se evitan secretos en el código y el proveedor puede cambiarse sin modificar la lógica.

## ADR-004 — Embeddings ligeros para validar el MVP

**Decisión:** Usar `nomic-embed-text` mediante Ollama durante la validación inicial de RAG. Mantener BGE-M3 como modelo objetivo para una comparación posterior.

**Por qué:** Nomic ya está disponible localmente, evita añadir PyTorch al proceso de la API y permite medir recuperación, latencia y RAM antes de asumir el costo operativo de BGE-M3.

## ADR-005 — No activar reranker por defecto

**Decisión:** Mantener `BAAI/bge-reranker-v2-m3` como experimento offline y no
incorporarlo a la ruta productiva del MVP.

**Evidencia:** En 24 consultas mejoró Hit@5 de 0.850 a 1.000 y nDCG@5 de 0.711 a
0.767, pero añadió p50 24.0 s, p95 32.3 s y aproximadamente 1.3 GB de RAM en CPU.

**Siguiente criterio:** reconsiderar sólo con una variante cuantizada, presupuesto
de latencia explícito y validación humana de qrels.
