"""🧠 MoA Engine — Mixture-of-Agents Intelligence Amplifier.

INTEGRACIÓN EN PRODUCCIÓN del patrón MoA (Wang et al. 2024).
Transforma decisiones individuales en consensos multi-modelo.

ARQUITECTURA:
```
Proposer 1 (deepseek-v4-flash) ───┐
Proposer 2 (kimi-k2.5) ───────────┤──→ Aggregator (deepseek-v4-pro) → Consensus
Proposer 3 (qwen3.7-plus) ────────┘
```

USO EN PIPELINE:
    from src.moa_engine import MoAOrchestrator
    moa = MoAOrchestrator()
    result = await moa.solve(problem, context)

MODELOS:
    3 proposers: flash, kimi, qwen (paralelo, ~$0.001 total)
    1 aggregator: deepseek-v4-pro (secuencial, ~$0.002)
    Costo total por decisión MoA: ~$0.003 — 1 call Pro + 3 calls Go
"""

import json
import asyncio
import time
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from langchain_core.messages import HumanMessage, SystemMessage

from src.config import (
    get_llm, get_pro_llm, get_kimi_llm, get_deepseek_pro_llm,
    get_model_llm, safe_invoke, TEMPERATURE_CREATIVE
)


# ── Data Classes ───────────────────────────────────────────────

@dataclass
class MoAResponse:
    """Respuesta de un proposer en el MoA."""
    agent_id: str
    content: str
    confidence: float
    model: str
    latency_ms: float
    metadata: Dict = field(default_factory=dict)


@dataclass
class MoAConfig:
    """Configuración del MoA Orchestrator."""
    use_proposer_pro: bool = False       # True = 1 proposer con Pro (más caro)
    use_aggregator_pro: bool = True      # True = aggregator con Pro (recomendado)
    timeout_per_proposer: float = 45.0   # Timeout por proposer
    min_consensus: float = 0.6           # Mínimo agreement para early exit
    parallel_proposers: bool = True      # Ejecutar proposers en paralelo


# ── Proposer Registry ──────────────────────────────────────────

# Registro de proposers disponibles para MoA
PROPOSER_REGISTRY = {
    "flash": {
        "name": "Flash (práctico)",
        "model": "deepseek-v4-flash",
        "temperature": 0.4,
        "max_tokens": 2048,
        "get_llm": lambda mt: get_llm(temperature=0.4, max_tokens=mt or 2048),
        "rol": "Enfoque práctico y directo. Soluciones que funcionan.",
    },
    "kimi": {
        "name": "Kimi (estratégico)",
        "model": "opencode-go/kimi-k2.5",
        "temperature": 0.5,
        "max_tokens": 2048,
        "get_llm": lambda mt: get_kimi_llm(temperature=0.5, max_tokens=mt or 2048),
        "rol": "Visión estratégica y creativa. Alternativas innovadoras.",
    },
    "qwen": {
        "name": "Qwen (pragmático)",
        "model": "qwen3.7-plus",
        "temperature": 0.3,
        "max_tokens": 2048,
        "get_llm": lambda mt: get_pro_llm(max_tokens=mt or 2048),
        "rol": "Análisis pragmático. Costo-beneficio, riesgos, viabilidad.",
    },
    "pro": {
        "name": "Pro (máxima calidad)",
        "model": "deepseek-v4-pro",
        "temperature": 0.2,
        "max_tokens": 2048,
        "get_llm": lambda mt: get_deepseek_pro_llm(temperature=0.2, max_tokens=mt or 2048),
        "rol": "Razonamiento extremo. Decisiones críticas de alta precisión.",
    },
}


# ── MoA Orchestrator ────────────────────────────────────────────

class MoAOrchestrator:
    """Orquestador MoA: ejecuta proposers en paralelo + aggregator con consenso.
    
    Uso:
        moa = MoAOrchestrator()
        result = await moa.solve(
            problem="¿Qué arquitectura usar para...?",
            proposers=["flash", "kimi", "qwen"],
            system_prompt="Eres un arquitecto de software experto...",
            context={"requirement": "...", "rules": [...]},
        )
    """
    
    def __init__(self, config: MoAConfig = None):
        self.config = config or MoAConfig()
        self._cache: Dict[str, Any] = {}
    
    async def solve(
        self,
        problem: str,
        proposers: List[str] = None,
        system_prompt: str = None,
        context: Dict = None,
        aggregator_prompt: str = None,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """Resuelve un problema usando MoA con proposers en paralelo + aggregator.
        
        Args:
            problem: El problema/pregunta a resolver
            proposers: Lista de IDs de proposers (ej: ["flash", "kimi", "qwen"])
            system_prompt: System prompt para los proposers
            context: Contexto adicional para los proposers
            aggregator_prompt: Prompt específico para el aggregator
            max_tokens: Máximo de tokens de salida por proposer
        
        Returns:
            Dict con la respuesta consensuada + metadata
        """
        start = time.time()
        proposers = proposers or ["flash", "kimi", "qwen"]
        context = context or {}
        
        # Cache key
        cache_key = hashlib.md5(
            f"{problem}{json.dumps(proposers)}".encode()
        ).hexdigest()[:16]
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # ── Fase 1: Ejecutar proposers en paralelo ──
        print(f"\n{'='*50}")
        print(f"  🧠 MoA: {len(proposers)} proposers en paralelo")
        print(f"{'='*50}")
        
        tasks = []
        for prop_id in proposers:
            task = self._run_proposer(
                prop_id=prop_id,
                problem=problem,
                system_prompt=system_prompt,
                context=context,
                max_tokens=max_tokens,
            )
            tasks.append(task)
        
        if self.config.parallel_proposers:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            responses = [await t for t in tasks]
        
        # Filtrar respuestas válidas
        valid_responses = [
            r for r in responses
            if isinstance(r, MoAResponse) and r.content
        ]
        
        if not valid_responses:
            print(f"  [MoA] ⚠️ Todos los proposers fallaron")
            return {
                "answer": None,
                "confidence": 0.0,
                "proposers_used": 0,
                "error": "Todos los proposers fallaron",
            }
        
        # Mostrar resumen de proposers
        for r in valid_responses:
            content_preview = r.content[:100].replace('\n', ' ')
            print(f"  [{r.agent_id}] ✅ confianza={r.confidence:.2f} "
                  f"({r.latency_ms:.0f}ms): {content_preview}...")
        
        # ── Fase 2: Aggregator (consenso) ──
        if self.config.use_aggregator_pro and len(valid_responses) >= 2:
            answer = await self._aggregate(
                problem=problem,
                responses=valid_responses,
                aggregator_prompt=aggregator_prompt,
                context=context,
            )
        else:
            # Sin aggregator: tomar la de mayor confianza
            best = max(valid_responses, key=lambda r: r.confidence)
            answer = {
                "answer": best.content,
                "confidence": best.confidence,
                "source": best.agent_id,
            }
        
        # Calcular consenso
        consensus = self._compute_consensus(valid_responses)
        
        result = {
            "answer": answer.get("answer", valid_responses[0].content),
            "confidence": answer.get("confidence", consensus["agreement"]),
            "consensus": consensus,
            "proposers_used": len(valid_responses),
            "proposers_total": len(proposers),
            "total_time_ms": (time.time() - start) * 1000,
            "responses": [r.__dict__ for r in valid_responses],
            "aggregator_used": self.config.use_aggregator_pro and len(valid_responses) >= 2,
        }
        
        # Cachear
        self._cache[cache_key] = result
        
        elapsed = result["total_time_ms"]
        print(f"  [MoA] ✅ Consenso: confianza={consensus['agreement']:.2f} "
              f"| {result['proposers_used']}/{result['proposers_total']} proposers "
              f"| {elapsed:.0f}ms")
        print(f"{'='*50}\n")
        
        return result
    
    async def _run_proposer(
        self,
        prop_id: str,
        problem: str,
        system_prompt: str = None,
        context: Dict = None,
        max_tokens: int = 2048,
    ) -> MoAResponse:
        """Ejecuta un proposer individual."""
        t0 = time.time()
        
        registry = PROPOSER_REGISTRY.get(prop_id)
        if not registry:
            return MoAResponse(
                agent_id=prop_id,
                content="",
                confidence=0.0,
                model="unknown",
                latency_ms=0,
            )
        
        try:
            llm = registry["get_llm"](max_tokens)
            
            # Construir prompt del proposer
            rol = registry["rol"]
            context_str = ""
            if context:
                context_str = "\n\nContexto:\n" + json.dumps(
                    {k: str(v)[:500] for k, v in context.items()},
                    indent=2, ensure_ascii=False
                )[:1500]
            
            proposer_system = system_prompt or f"""Eres un analista experto con el siguiente rol:
{rol}

Genera tu mejor respuesta al problema planteado.
Sé específico, concreto y accionable.
Máximo {max_tokens} tokens de salida."""
            
            proposer_prompt = f"""Problema:
{problem}
{context_str}

Desde tu perspectiva como {registry['name']}, analiza y responde."""
            
            response = await safe_invoke(llm, [
                SystemMessage(content=proposer_system),
                HumanMessage(content=proposer_prompt),
            ])
            
            content = response.content if hasattr(response, 'content') else str(response)
            elapsed = (time.time() - t0) * 1000
            
            return MoAResponse(
                agent_id=prop_id,
                content=content[:max_tokens],
                confidence=0.7 + (hash(prop_id) % 30) / 100,  # Heurística base
                model=registry["model"],
                latency_ms=elapsed,
            )
            
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            print(f"  [MoA] ⚠️ Proposer '{prop_id}' falló: {str(e)[:80]}")
            return MoAResponse(
                agent_id=prop_id,
                content="",
                confidence=0.0,
                model=registry.get("model", "unknown"),
                latency_ms=elapsed,
                metadata={"error": str(e)},
            )
    
    async def _aggregate(
        self,
        problem: str,
        responses: List[MoAResponse],
        aggregator_prompt: str = None,
        context: Dict = None,
    ) -> Dict:
        """Agrega múltiples respuestas de proposers usando deepseek-v4-pro.
        
        El aggregador:
        1. Lee todas las respuestas de los proposers
        2. Evalúa calidad, completitud y relevancia
        3. Produce una respuesta fusionada o elige la mejor
        4. Asigna confianza
        """
        llm = get_deepseek_pro_llm(temperature=0.15, max_tokens=2048)
        
        # Formatear respuestas de proposers para el aggregator
        proposers_text = "\n\n".join([
            f"=== {r.agent_id.upper()} ({r.model}) [confianza: {r.confidence:.2f}] ===\n{r.content[:1500]}"
            for r in responses
        ])
        
        context_str = ""
        if context:
            context_str = "\nContexto:\n" + json.dumps(
                {k: str(v)[:300] for k, v in context.items()},
                indent=2, ensure_ascii=False
            )[:1000]
        
        aggregator_system = aggregator_prompt or """Eres el Aggregator del MoA — el modelo más inteligente del enjambre.

Tu tarea es:
1. REVISAR todas las respuestas de los proposers
2. EVALUAR cuál tiene el mejor razonamiento
3. SINTETIZAR una respuesta final que incorpore lo mejor de cada una
4. ASIGNAR una confianza a tu respuesta final

Responde ÚNICAMENTE en este formato JSON:
{
    "answer": "tu respuesta sintetizada aquí",
    "confidence": 0.0-1.0,
    "reasoning": "por qué elegiste esta respuesta sobre las otras",
    "source_proposers": ["flash", "kimi"],
    "key_differences": ["diferencia clave entre proposers"]
}"""
        
        aggregator_prompt_text = f"""Problema original:
{problem}{context_str}

Respuestas de los proposers a evaluar:
{proposers_text}

Analiza, sintetiza y produce la mejor respuesta posible."""
        
        response = await safe_invoke(llm, [
            SystemMessage(content=aggregator_system),
            HumanMessage(content=aggregator_prompt_text),
        ])
        
        content = response.content if hasattr(response, 'content') else str(response)
        
        try:
            content_clean = content.strip()
            if content_clean.startswith("```"):
                lines = content_clean.split("\n")
                content_clean = "\n".join(lines[1:-1])
            result = json.loads(content_clean)
        except json.JSONDecodeError:
            result = {
                "answer": content[:2000],
                "confidence": 0.5,
                "reasoning": "Error parseando JSON del aggregator",
                "source_proposers": [r.agent_id for r in responses[:2]],
            }
        
        return result
    
    def _compute_consensus(self, responses: List[MoAResponse]) -> Dict:
        """Calcula nivel de consenso entre proposers.
        
        Usa heurística de longitud y diversidad de contenido.
        En producción ideal: embedding similarity.
        """
        if not responses:
            return {"agreement": 0.0, "confidence": 0.0}
        
        # Confianza promedio
        avg_confidence = sum(r.confidence for r in responses) / len(responses)
        
        # Diversidad de contenidos (aproximación por longitud)
        lengths = [len(r.content) for r in responses]
        if lengths:
            avg_len = sum(lengths) / len(lengths)
            variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
            # Baja varianza → alta similitud (todos respondieron similar longitud)
            similarity = max(0, 1.0 - (variance / (avg_len ** 2 + 1)))
        else:
            similarity = 0.5
        
        # Agreement compuesto
        agreement = (avg_confidence * 0.6 + similarity * 0.4)
        
        return {
            "agreement": round(agreement, 3),
            "avg_confidence": round(avg_confidence, 3),
            "content_similarity": round(similarity, 3),
            "num_responses": len(responses),
        }
    
    def clear_cache(self):
        """Limpia la caché de resultados MoA."""
        self._cache.clear()
