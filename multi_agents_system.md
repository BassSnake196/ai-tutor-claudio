# Laboratorio y Sistema Multi-Agente para Asistente Docente Pedagógico (AI Tutor)
## Documento Maestro de Arquitectura, Roles de Agentes y Guía de Despliegue

---

## 1. Visión del Proyecto y Alcance

El sistema consiste en un **Laboratorio de Agentes Inteligentes Especializados** diseñado para asistir a docentes universitarios y escolares en la creación, estructuración, enriquecimiento y evaluación de **temarios, planes de clase, actividades didácticas y contenido explicativo**.

### Restricciones Económicas y de Infraestructura (Zero Cost / Low Cost Target)
- **Cero dependencia de APIs de pago por consumo elevado**: El sistema se ejecuta 100% con modelos locales de código abierto (SLM cuantizados, embeddings locales, STT local, Vector DB local) combinados exclusivamente con el nivel gratuito de **Google Gemini API (Google AI Studio Free Tier / Gemini 1.5 Flash & 2.0 Flash)** o suscripciones base de Gemini Pro.
- **Hardware de referencia (Consumo acotado en CPU/RAM)**: Optimizado para procesadores x86_64 (como AMD Ryzen 7 / Intel Core i7) con 16 GB de RAM, sin necesidad de GPUs NVIDIA dedicadas (utilizando cuantizaciones `Q4_K_M` en CPU y librerías optimizadas en C++/int8 como `faster-whisper` y `llama.cpp`/`Ollama`).

---

## 2. Topología y Roles del Sistema Multi-Agente

Para evitar cuellos de botella secuenciales y minimizar el consumo de recursos, el sistema se divide en **micro-agentes especializados** que ejecutan tareas en paralelo y asíncronas.

```
                                  ┌──────────────────────────────┐
                                  │      DOCENTE / FRONTEND      │
                                  └──────────────┬───────────────┘
                                                 │
                                  ┌──────────────▼───────────────┐
                                  │  AGENTE 1: DIRECTOR / ROUTER │
                                  │  (Determinístico + SLM 3-4B) │
                                  └──────────────┬───────────────┘
                                                 │
              ┌──────────────────────────────────┼──────────────────────────────────┐
              │                                  │                                  │
┌─────────────▼────────────┐       ┌─────────────▼────────────┐       ┌─────────────▼────────────┐
│ AGENTE 2: INVESTIGADOR   │       │ AGENTE 3: INGESTOR       │       │ AGENTE 4: CURRICULAR     │
│ Y RETRIEVAL (RAG)        │       │ MULTIMEDIA Y WEB         │       │ Y TEMARIOS               │
│ - BGE-M3 (Embeddings)    │       │ - faster-whisper (STT)   │       │ - Gemini Flash /         │
│ - Qdrant (Hybrid Search) │       │ - Web Scraper / Crawler  │       │   Qwen 8B Local          │
│ - bge-reranker-v2-m3     │       │ - Document Parser (PDF)  │       │ - Estructuración Schema  │
└─────────────┬────────────┘       └─────────────┬────────────┘       └─────────────┬────────────┘
              │                                  │                                  │
              └──────────────────────────────────┼──────────────────────────────────┘
                                                 │
                                  ┌──────────────▼───────────────┐
                                  │ AGENTE 5: GENERADOR          │
                                  │ DIDÁCTICO Y EXPLICACIONES    │
                                  │ (Gemini 2.0/1.5 Flash Free)  │
                                  └──────────────┬───────────────┘
                                                 │
                                  ┌──────────────▼───────────────┐
                                  │ AGENTE 6: CRÍTICO Y          │
                                  │ ANTI-ALUCINACIÓN (AUDITOR)   │
                                  │ - Grounding & Citation Check │
                                  │ - JSON Schema Validator      │
                                  └──────────────┬───────────────┘
                                                 │
                                  ┌──────────────▼───────────────┐
                                  │ RESPUESTA FINAL ESTRUCTURADA │
                                  └──────────────────────────────┘
```

---

### Descripción Detallada de Roles

#### 🧑‍✈️ 1. Agente Orquestador & Router (Director)
* **Objetivo:** Recibir el prompt o requerimiento del docente, clasificar la intención, desglosar subtareas paralelas y determinar qué agentes deben actuar.
* **Motor:** Reglas determinísticas (Regex, JSON Schema) + SLM local ultra-rápido (`Qwen3-4B-Instruct` o `Phi-4-mini` en Ollama).
* **Consumo API:** 0 tokens cloud.
* **Tiempo de respuesta:** < 500 ms en CPU.

#### 🔍 2. Agente Investigador & RAG (Context Retriever)
* **Objetivo:** Realizar búsqueda híbrida (semántica y léxica) en la base vectorial sobre los documentos institucionales, temarios previos y bibliografía almacenada. Aplica reordenamiento semántico (Reranker).
* **Motor:** 
  - Embeddings: `BAAI/bge-m3` (local).
  - Vector DB: `Qdrant` (local en Docker o standalone).
  - Reranker: `bge-reranker-v2-m3` (local).
* **Consumo API:** 0 tokens cloud.

#### 🎙️ 3. Agente Ingestor Multimedia & Web (Data Collector)
* **Objetivo:** Transcribir clases grabadas o videos de YouTube pedagógicos (extrayendo timestamps precisos) y scrapear artículos o páginas web oficiales aprobadas.
* **Motor:** `faster-whisper` (int8 en CPU) + `yt-dlp` / `ffmpeg` + `trafilatura` / `BeautifulSoup4`.
* **Consumo API:** 0 tokens cloud.

#### 📐 4. Agente Diseñador Curricular & Temarios (Curriculum Architect)
* **Objetivo:** Modelar la estructura del curso, modularización por semanas/unidades, definición de competencias según la taxonomía de Bloom y distribución de tiempos.
* **Motor:** `Google Gemini 1.5 Flash` / `Gemini 2.0 Flash` (Free Tier) o `Qwen 8B Q4_K_M` en local si no hay internet.
* **Consumo API:** Free Key de Google AI Studio.

#### ✍️ 5. Agente Generador Didáctico & Redactor Pedagógico
* **Objetivo:** Redactar explicaciones paso a paso, analogías, actividades prácticas, preguntas de autoevaluación, rúbricas y material de apoyo adaptado al nivel académico del estudiante.
* **Motor:** `Google Gemini 1.5 Flash / Gemini 2.0 Flash` (vía API oficial con `generationConfig` y `response_schema` JSON).
* **Consumo API:** Free Key de Google AI Studio.

#### 🛡️ 6. Agente Crítico & Auditor de Grounding (Anti-Alucinación)
* **Objetivo:** Verificar que cada concepto generado tenga respaldo en los chunks de documentos o videos recuperados. Valida que el JSON cumpla el schema estricto y asigna el estado de fundamentación: `SUPPORTED`, `PARTIALLY_SUPPORTED`, `INSUFFICIENT_CONTEXT` o `UNSUPPORTED`.
* **Motor:** Verificador determinístico de IDs de citas + SLM local ligero (`Qwen3-4B`).
* **Consumo API:** 0 tokens cloud.

---

## 3. Pila Tecnológica Recomendada (Stack Técnico)

| Componente | Tecnología Seleccionada | Justificación & Ventaja | Costo |
|---|---|---|---|
| **Motor LLM Cloud (Complejo)** | **Google Gemini 2.0 Flash / 1.5 Flash** | Ventana de contexto de 1M tokens, salida estructurada por schema nativa, cuota gratuita generosa (hasta 15 RPM gratis en Google AI Studio). | **Gratis** (Google AI Studio Free Key) |
| **Motor SLM Local (Routing/Auditoría)** | **Ollama con `qwen2.5:3b` / `qwen2.5:7b` o `phi4:mini`** | 10-20 tok/s en CPU x86_64, excelente soporte de español e instrucciones estructuradas. | **Gratis / Local** |
| **Embeddings Semánticos** | **BGE-M3 (`BAAI/bge-m3`)** | Multilingüe nativo, soporta vectores densos + sparse (BM25), contexto de 8192 tokens. Corre en CPU. | **Gratis / Local** |
| **Reranker de Precisión** | **`BAAI/bge-reranker-v2-m3`** | Filtra los 20 mejores resultados de búsqueda a los 5 más relevantes antes de alimentar al LLM. | **Gratis / Local** |
| **Base de Datos Vectorial** | **Qdrant (Local Docker o Embedded)** | Rendimiento nativo en Rust, bajo consumo de RAM (<300 MB), filtrado por metadatos (`tenant_id`, `curso`, `unidad`). | **Gratis / Open Source** |
| **Transcripción Audio/Video** | **`faster-whisper` (modelo `medium` o `small` int8)** | Hasta 4x más rápido que OpenAI Whisper estándar en CPU. VAD integrado para omitir silencios. | **Gratis / Local** |
| **Orquestación Multi-Agente** | **Python (FastAPI + `asyncio` + Pydantic v2)** | Arquitectura asíncrona pura. Permite disparar tareas paralelas concurrentes sin el overhead de frameworks pesados. | **Gratis / Open Source** |
| **Cola de Tareas Asíncronas** | **Redis + RQ (o background tasks nativas de FastAPI para MVP)** | Procesa transcripción de videos e ingesta de documentos pesados en segundo plano. | **Gratis / Open Source** |

---

## 4. Guía Paso a Paso para la Configuración del Entorno

### Paso 1: Instalación de Ollama y Descarga de Modelos Locales
En Windows (PowerShell):
```powershell
# 1. Descargar e instalar Ollama desde https://ollama.com/download
# 2. Descargar los modelos SLM locales ligeros y eficientes en CPU:
ollama pull qwen2.5:3b-instruct-q4_K_M
ollama pull qwen2.5:7b-instruct-q4_K_M
ollama pull phi4-mini
```

### Paso 2: Configuración de Qdrant (Base de Datos Vectorial)
Usando Docker Desktop o binario local:
```powershell
docker run -d -p 6333:6333 -p 6334:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

### Paso 3: Configuración del Entorno Virtual de Python
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install fastapi uvicorn pydantic google-genai sentence-transformers qdrant-client faster-whisper yt-dlp trafilatura beautifulsoup4 pypdf python-docx python-dotenv pytest
```

### Paso 4: Obtención de la API Key Gratuita de Google Gemini
1. Acceder a [Google AI Studio](https://aistudio.google.com/).
2. Crear un proyecto y generar una API Key ("Create API key in new project").
3. Configurar en el archivo `.env`:
```env
GEMINI_API_KEY="AIzaSy..."
OLLAMA_BASE_URL="http://localhost:11434"
QDRANT_URL="http://localhost:6333"
EMBEDDING_MODEL_NAME="BAAI/bge-m3"
RERANKER_MODEL_NAME="BAAI/bge-reranker-v2-m3"
```

---

## 5. Estructura del Código en el Proyecto

```text
A-TutorClaudio/
├── app/
│   ├── core/
│   │   ├── config.py             # Lectura de variables de entorno y settings
│   │   └── security.py           # Sanitización de prompts y aislamiento de datos
│   ├── ai/
│   │   ├── gemini_client.py      # Conector oficial SDK de Google Gemini Free
│   │   ├── ollama_client.py      # Conector local Ollama (SLMs)
│   │   ├── embeddings.py         # Pipeline BGE-M3 local
│   │   └── reranker.py           # Reordenamiento semántico
│   ├── agents/
│   │   ├── router_agent.py       # Agente Director / Clasificador
│   │   ├── rag_agent.py          # Agente de Recuperación Vectorial
│   │   ├── multimedia_agent.py   # Agente de Transcripción (faster-whisper) y Web Scraper
│   │   ├── curriculum_agent.py   # Agente de Diseño de Temarios
│   │   ├── teaching_agent.py     # Agente de Explicaciones y Actividades
│   │   └── critic_agent.py       # Agente de Auditoría / Anti-alucinación
│   ├── rag/
│   │   ├── vector_store.py       # Interfaz con Qdrant
│   │   ├── chunker.py            # Segmentación semántica de documentos
│   │   └── web_scraper.py        # Ingesta de páginas web y fuentes oficiales
│   ├── schemas/
│   │   ├── curriculum_schema.py  # Pydantic Schemas para temarios y planes
│   │   └── responses.py          # Esquemas de respuestas con citas
│   └── main.py                   # API FastAPI y orquestación de endpoints
├── data/
│   ├── raw_documents/            # PDFs, Word institucionales
│   └── videos_audio/             # Audios extraídos para transcripción
├── .env.example
├── requirements.txt
└── README.md
```

---

## 6. Esquema de Salida Estructurada (JSON Schema Garantizado)

El sistema garantiza que cada temario generado retorne con la siguiente estructura limpia y validada por Pydantic:

```json
{
  "schema_version": "1.0",
  "topic_title": "Introducción a la Programación Orientada a Objetos",
  "target_level": "Universidad - Semestre 2",
  "pedagogical_approach": "Aprendizaje Basado en Proyectos",
  "learning_objectives": [
    "Comprender los 4 pilares de la POO: Abstracción, Encapsulamiento, Herencia y Polimorfismo.",
    "Modelar un problema del mundo real mediante diagramas de clases simples."
  ],
  "syllabus_units": [
    {
      "unit_number": 1,
      "unit_name": "Fundamentos y Clases",
      "estimated_hours": 4,
      "subtopics": ["Objetos vs Clases", "Atributos y Métodos", "Constructores"],
      "didactic_explanation": "Una clase es como un plano arquitectónico, y el objeto es la casa construida...",
      "practical_activities": [
        "Crear una clase `CuentaBancaria` con métodos `depositar()` y `retirar()`."
      ],
      "evaluation_questions": [
        {
          "question": "¿Cuál es la diferencia entre una clase y una instancia?",
          "expected_answer": "La clase es la definición o molde; la instancia es el objeto concreto en memoria."
        }
      ],
      "citations": [
        {
          "source_id": "DOC_INSTITUCIONAL_POO_2024",
          "fragment_reference": "Sección 2.1 - Metodología Curricular",
          "timestamp": null
        }
      ]
    }
  ],
  "grounding_status": "SUPPORTED"
}
```

---

## 7. Plan de Ejecución y Próximos Hitos

1. **Hito 1 (Fundación del Laboratorio):**
   - Configurar `app/core/config.py`, conectores `gemini_client.py` y `ollama_client.py`.
   - Inicializar Qdrant y la ingesta de documentos locales con `BGE-M3`.
2. **Hito 2 (Agentes Paralelos en Acción):**
   - Implementar el pipeline de `router_agent.py` que distribuye peticiones.
   - Conectar el `rag_agent.py` con el `curriculum_agent.py` y `teaching_agent.py`.
3. **Hito 3 (Transcriptor Multimedia & Scraper):**
   - Integrar `faster-whisper` para videos de clases y YouTube.
4. **Hito 4 (Auditoría Anti-Alucinación y Pruebas):**
   - Ejecutar batería de tests de consistencia y precisión en `critic_agent.py`.
