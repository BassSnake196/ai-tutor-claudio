# Registro inicial de modelos

| Uso | Proveedor | Modelo | Estado |
| --- | --- | --- | --- |
| Routing y consultas simples | Ollama local | `qwen2.5:3b` (Q4_K_M) | Instalado |
| Alternativa local de mayor calidad | Ollama local | `qwen2.5:7b` (Q4_K_M) | Instalado |
| Generación pedagógica compleja | Google Gemini | Modelo configurable por `GEMINI_MODEL` | Requiere API key |
| Embeddings del MVP | Ollama local | `nomic-embed-text` | Instalado |
| Embeddings objetivo | Ollama local | `bge-m3` (F16, 1024 dim) | Evaluado; candidato experimental |
| Reranking | Transformers CPU | `BAAI/bge-reranker-v2-m3` | Evaluado; diferido por 24–32 s/consulta |
| Alternativa local compacta | Ollama local | `phi4-mini` (Q4_K_M) | Instalado |
| Transcripción | faster-whisper | `small` int8 | Diferido a fase posterior |

Los nombres se configuran en `.env`; el código no debe acoplarse a un proveedor o modelo concreto.
