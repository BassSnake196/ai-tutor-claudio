# Funcionamiento actual del sistema y siguiente bloque

## Objetivo vigente

El sistema sigue orientado a profesores: genera temarios aplicables, permite aportar
material y fundamenta el contenido con una jerarquía explícita. El objetivo original
del documento maestro se mantiene.

## Cómo funciona ahora

```text
Docente -> CurriculumRequest -> validación de política
  -> consultas de investigación determinísticas (0 tokens cloud)
  -> SourceResolver
       1. documentos seleccionados
       2. biblioteca/curso de Qdrant
       3. web o YouTube sólo con EXTERNAL_ALLOWED
  -> EvidenceBundle + cobertura + traza
  -> Arquitecto curricular Gemini (JSON/Pydantic)
  -> Agente didáctico Gemini (estructura y horas bloqueadas)
  -> Crítico determinístico de citas
  -> Auditor semántico Ollama, sólo puede degradar grounding
  -> CurriculumGenerationResponse
```

Si la política exige fuentes y la cobertura no alcanza el mínimo, el flujo se detiene
antes de Gemini con `INSUFFICIENT_CONTEXT` y cero tokens generativos. Con
`NO_SOURCES`, sí genera una propuesta, pero queda marcada `UNSUPPORTED` y sin citas.

## Componentes principales

- Director: construye consultas reproducibles y decide rutas sin llamada cloud.
- Investigador/Resolver: aplica filtros, umbral, deduplicación, cobertura y jerarquía.
- Ingestor: procesa documentos, web, YouTube y audio con procedencia.
- Arquitecto: diseña objetivos, secuencia y carga horaria.
- Didáctico: añade explicaciones, actividades y evaluación sin cambiar la estructura.
- Crítico: impide citas inventadas y audita respaldo/pedagogía.
- Qdrant: guarda texto, embeddings y payload; no guarda prompts del sistema.
- Gestor de trabajos: limita concurrencia y aísla fallos de ingestas largas.

## Uso de tokens y recursos

- Qdrant, embeddings, búsqueda web, subtítulos, Whisper y el crítico local no consumen
  tokens cloud.
- Gemini se usa sólo después de superar cobertura o al elegir `NO_SOURCES`.
- La respuesta muestra tokens por modelo/rol y latencia por etapa.
- Las consultas externas se limitan por consulta y concurrencia.
- YouTube evita descargar y transcribir cuando existen subtítulos públicos.

## Próximo orden recomendado

1. Crear un dataset pequeño de preguntas y relevancia esperada en español.
2. Medir recall/precision/MRR y latencia con Nomic actual.
3. Probar BGE-M3 en una colección separada, nunca reemplazando la actual directamente.
4. Añadir búsqueda léxica/híbrida y medir su aporte.
5. Evaluar `bge-reranker-v2-m3` sobre los mejores resultados.
6. Adoptar sólo la combinación que mejore calidad dentro del límite de RAM/latencia.

Ese orden evita descargar modelos grandes o modificar la colección principal sin una
métrica que demuestre beneficio.
