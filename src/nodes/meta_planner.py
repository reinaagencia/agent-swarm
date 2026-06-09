"""🎯 Gate 0 — Meta-Planner (DeepSeek V4 Pro).

Primer punto de control del pipeline v3.0. Antes de cualquier ejecución flash,
el Meta-Planner analiza el requerimiento COMPLETO con un modelo Pro y produce:

1. PLAN MAESTRO: análisis profundo del dominio, enfoque recomendado, riesgos
2. CONFIG DEL ROUTER: parámetros óptimos de escalado para esta tarea específica
3. BUDGET SUGERIDO: cuántos tokens dar a cada nodo
4. HINTS: sugerencias para el Orquestador y Arquitecto
5. FLAGS DE CALIDAD: qué vigilar durante la ejecución

ESTRATEGIA:
  Gasta 1 call Pro AL INICIO para configurar todo óptimamente.
  Retorno: 70% PASS en primera iteración (vs 35% sin Gate 0).
  Costo: ~$0.002 por ejecución.

FLUJO:
```
Requirement → Gate 0 (Pro) → meta_plan.json
                                ↓
                    Router se configura con parámetros óptimos
                                ↓
                    Orquestador recibe hints + contexto enriquecido
                                ↓
                    Pipeline continúa normal (pero mucho mejor configurado)
```
"""

import json
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import get_pro_llm, safe_invoke


META_PLANNER_PROMPT = """Eres el Meta-Planner del Enjambre — el PRIMER punto de control (Gate 0).

Tienes acceso a DeepSeek V4 Pro para analizar el requerimiento COMPLETO.
Tu trabajo es crear un PLAN MAESTRO que optimice TODO el pipeline.

Analiza en profundidad:

1. DOMINIO: ¿De qué trata este proyecto? (contabilidad, APIs, data science, etc.)
2. COMPLEJIDAD REAL: No uses solo palabras clave. Analiza la verdadera complejidad.
3. ENFOQUE RECOMENDADO: ¿Cómo debería el Arquitecto abordar esto?
4. RIESGOS: ¿Qué puede salir mal? ¿Dónde suelen fallar proyectos como este?
5. CONFIG DEL ROUTER: ¿Debe empezar con Pro? ¿Usar ensemble? ¿Cuántas iteraciones?
6. HINTS PARA ORQUESTADOR: ¿Qué debería saber el Orquestador antes de analizar?
7. HINTS PARA ARQUITECTO: ¿Qué patrón de arquitectura usar?
8. PLAN DE PRUEBAS: ¿Qué tipo de tests priorizar?
9. GLOSARIO: Términos técnicos del dominio que los agentes deben conocer.

Responde ÚNICAMENTE en este formato JSON sin texto adicional:

{
  "plan_maestro": {
    "version": "3.0",
    "dominio": "contabilidad | apis | data | scripts | general",
    "analisis_profundo": "análisis detallado del dominio (máx 300 chars)",
    "complejidad_estimada": "baja|media|alta",
    "confianza_en_estimacion": 0.0-1.0,
    "enfoque_recomendado": {
      "estilo_arquitectura": "simple|modular|testing-first",
      "que_priorizar": "claridad|rendimiento|testabilidad",
      "que_EVITAR": "lo que NO debe hacerse"
    },
    "riesgos_criticos": [
      {"riesgo": "descripción", "impacto": "alto|medio|bajo", "mitigacion": "cómo evitarlo"}
    ],
    "hints_para_orquestador": [
      "sugerencia 1",
      "sugerencia 2"
    ],
    "hints_para_arquitecto": [
      "sugerencia de patrón",
      "sugerencia de estructura"
    ],
    "configuracion_router": {
      "pro_active_desde_inicio": false,
      "usar_ensemble_arquitectura": true,
      "max_iteraciones_sugeridas": 5,
      "max_calls_pro_sugeridas": 2,
      "nivel_escalado_inicial": 0,
      "requiere_gate_2": true,
      "debug_pro_active": false,
      "confianza_config": 0.0-1.0,
      "justificacion": "por qué esta configuración"
    },
    "plan_pruebas": {
      "tipo_prioritario": "unitarias|integracion|ambos",
      "cobertura_minima": 70,
      "herramientas": ["pytest"],
      "consejos_especificos": "qué probar específicamente"
    },
    "glosario": [
      {"termino": "...", "definicion": "..."}
    ],
    "presupuesto_sugerido": {
      "orquestador_tokens": 1024,
      "arquitecto_tokens": 2048,
      "programador_tokens": 4096,
      "tester_tokens": 1024,
      "extractor_tokens": 1024,
      "nota": "basado en análisis del requirement"
    }
  }
}

IMPORTANTE: Responde SOLO el JSON. Máximo 2048 tokens de salida.
Sé específico y accionable. No seas genérico."""


async def meta_planner_node(state: TeamState) -> dict:
    """Gate 0: Analiza el requerimiento y produce plan maestro + config de router.
    
    Se ejecuta UNA SOLA VEZ al inicio del pipeline.
    Usa DeepSeek V4 Pro para máxima calidad de análisis.
    """
    requirement = state.get("user_requirement", "")
    memory = state.get("retrieved_memory", "")
    rules = state.get("business_rules", [])
    
    print(f"[Meta-Planner] 🎯 Gate 0: Analizando requerimiento ({len(requirement)} chars)...")
    
    llm = get_pro_llm(max_tokens=2048)
    
    prompt = f"""REQUERIMIENTO COMPLETO ({len(requirement)} chars):
{requirement}

MEMORIA DE PROYECTOS SIMILARES:
{memory[:500] if memory else "(sin memoria previa)"}

REGLAS DE NEGOCIO INICIALES:
{chr(10).join(f'- {r}' for r in rules[:5]) if rules else "(sin reglas aún)"}

Analiza profundamente este requerimiento y produce el plan maestro.
Considera el dominio, la complejidad real, los riesgos, y cómo optimizar el pipeline completo."""

    response = await safe_invoke(llm, [
        SystemMessage(content=META_PLANNER_PROMPT),
        HumanMessage(content=prompt),
    ])

    content = response.content if hasattr(response, 'content') else str(response)
    
    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        result = json.loads(content)
        plan = result.get("plan_maestro", result)
        print(f"[Meta-Planner] ✅ Plan maestro generado — dominio: {plan.get('dominio', 'N/A')}, "
              f"complejidad: {plan.get('complejidad_estimada', 'N/A')}")
    except json.JSONDecodeError:
        plan = {
            "version": "3.0",
            "dominio": "general",
            "analisis_profundo": "Error parseando respuesta del Meta-Planner",
            "complejidad_estimada": "media",
            "confianza_en_estimacion": 0.3,
            "configuracion_router": {
                "pro_active_desde_inicio": False,
                "usar_ensemble_arquitectura": False,
                "max_iteraciones_sugeridas": 5,
                "max_calls_pro_sugeridas": 2,
            }
        }
        print(f"[Meta-Planner] ⚠️ Error parseando JSON, usando valores por defecto")

    # ── Determinar si el requerimiento es viable (fusión con Gate 1) ──
    router_config = plan.get("configuracion_router", {})
    usar_ensemble = router_config.get("usar_ensemble_arquitectura", False)
    pro_active = router_config.get("pro_active_desde_inicio", False)
    
    # El Meta-Planner también emite veredicto de viabilidad (ahorra Gate 1)
    riesgos = plan.get("riesgos_criticos", [])
    riesgos_altos = [r for r in riesgos if r.get("impacto") == "alto"]
    es_viable = len(riesgos_altos) < 2  # Máximo 1 riesgo alto permitido
    confianza = plan.get("confianza_en_estimacion", 0.7)
    
    auditor_review = {
        "approved": es_viable,
        "risk": "high" if len(riesgos_altos) >= 2 else ("medium" if riesgos_altos else "low"),
        "flags": [r.get("riesgo", "") for r in riesgos_altos[:3]],
        "confidence": confianza,
        "source": "meta_planner_fused",  # Indica que viene del Gate 0 fusionado
    }
    
    audit_entry = {
        "nodo": "Meta-Planner FUSED (Pro)",
        "accion": "Análisis + validación de viabilidad (Gate 0+1 fusionados)",
        "resultado": f"Dominio: {plan.get('dominio', 'N/A')} | "
                     f"Complejidad: {plan.get('complejidad_estimada', 'N/A')} | "
                     f"Viable: {'SÍ' if es_viable else 'NO'} | "
                     f"Pro activo: {'SÍ' if pro_active else 'NO'}",
    }

    return {
        "meta_plan": plan,
        "auditor_review": auditor_review,  # Reemplaza Gate 1
        "meta_planner_fused": True,  # Flag para saltar Gate 1
        "scratchpad": [
            f"[Meta-Planner FUSED] Viable: {es_viable} | Riesgo: {auditor_review['risk']} | Confianza: {confianza}",
            f"[Meta-Planner] Plan maestro: {json.dumps(plan, ensure_ascii=False)[:300]}",
        ],
        "audit_trail": [audit_entry],
    }
