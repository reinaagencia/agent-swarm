"""Agentes especializados del Enjambre 4.0.

Cada agente es un módulo independiente con prompt propio, herramientas y memoria.
Smith 1.0 es el orquestador principal que delega a los demás agentes.

Agentes disponibles:
    - smith:          Orquestador principal con model router flash↔pro ✅
    - investigador:   Búsqueda RAG en Supabase (pgvector) ✅ Fase 3
    - arquitecto:     Diseño de sistemas, blueprints JSON ✅ Fase 3
    - programador:    Generación de código + verificación bash ✅ Fase 3
    - tester:         QA — pytest real + análisis LLM ✅ Fase 3
    - auditor:        Validación de calidad (pro) ✅ (vía OpenCode subagent)
    - trader:         Análisis financiero ✅ (vía OpenCode subagent)
    - visor:          Análisis multimodal ✅ (vía OpenCode subagent)
    - extractor:      Destilación de conocimiento (pendiente Fase 4)
    - estratega:      Planificación y descomposición de tareas (pendiente Fase 4)
    - desplegador:    Instalación y despliegue multi-cliente (pendiente Fase 5)
"""

from src.agents.smith import SmithAgent, SessionMemory, SMITH_SYSTEM_PROMPT
from src.agents.smith_router import SmithRouter, RouterDecision, ModelTier

__all__ = [
    "SmithAgent", "SessionMemory", "SMITH_SYSTEM_PROMPT",
    "SmithRouter", "RouterDecision", "ModelTier",
]
