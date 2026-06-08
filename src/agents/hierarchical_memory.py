"""Hierarchical Memory — Sistema de 3 tiers para el Enjambre 4.0.

ARQUITECTURA:
  L1 — Short-term (SessionMemory): Scratchpad, turnos recientes, dedup cache.
        Vive una sesión. Acceso instantáneo. ~5KB.
  L2 — Medium-term (Supabase pgvector): Conocimiento vectorizado, lecciones,
        extractos de proyectos pasados. Persiste entre sesiones. ~50MB.
  L3 — Long-term (LessonsEngine + Rules): Patrones destilados, reglas de negocio
        auto-generadas, skills. Consolidado tras N ocurrencias. ~500KB.

FLUJO DE INFORMACIÓN:
  L1 ──[consolidate]──→ L2 ──[pattern detect]──→ L3
  L3 rules inyectadas como business_rules en futuras tareas
  L2 provee contexto RAG a nuevas tareas
  L1 mantiene el hilo de la conversación actual

USO:
  mem = HierarchicalMemory(smith_session=smith.memory)
  await mem.remember("task_type", "contenido", metadata={})
  context = await mem.recall("qué necesito saber sobre APIs REST?")
  rules = await mem.get_rules()
  mem.consolidate()  # mueve L1→L2→L3 si hay patrones
"""

from __future__ import annotations

import json
import time
import hashlib
import logging
from pathlib import Path
from collections import defaultdict
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Constantes ──
L1_MAX_ENTRIES = 50         # Máximo de entradas en short-term activas
L1_TTL_SECONDS = 3600 * 2   # 2 horas antes de consolidar a L2
CONSOLIDATE_THRESHOLD = 10   # Número de entradas L1 antes de consolidar
PATTERN_MIN_FREQ = 2         # Frecuencia mínima para detectar patrón L3
RULE_CONFIDENCE_MIN = 0.6    # Confianza mínima para generar regla

MEMORY_DIR = Path.home() / ".agents" / "memory"
RULES_FILE = MEMORY_DIR / "l3_rules.json"
PATTERNS_FILE = MEMORY_DIR / "l3_patterns.json"
CONSOLIDATION_LOG = MEMORY_DIR / "consolidation_log.json"


@dataclass
class MemoryEntry:
    """Entrada unificada para cualquier tier."""
    id: str
    tier: str             # "L1", "L2", "L3"
    content: str
    metadata: dict = field(default_factory=dict)
    embedding: list = field(default_factory=list)  # solo L2
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    consolidated_to: str = ""  # a qué tier fue consolidado


class HierarchicalMemory:
    """Sistema de memoria 3-tier con consolidación automática.
    
    Integra:
      - L1: SessionMemory de Smith (en RAM)
      - L2: Supabase pgvector (persistente, vectorizado)
      - L3: Reglas destiladas en disco (lecciones → reglas)
    """
    
    def __init__(self, smith_session=None):
        self._smith_session = smith_session  # L1: SessionMemory (externo)
        self._l1_buffer: List[MemoryEntry] = []
        self._l3_rules: Dict[str, dict] = {}
        self._l3_patterns: Dict[str, List[dict]] = defaultdict(list)
        self._domain_stats: Dict[str, dict] = defaultdict(lambda: {"count": 0, "successes": 0})
        self._last_consolidation = 0.0
        
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._load_l3()
    
    # ── API pública ──────────────────────────────────────────────
    
    async def remember(self, task_type: str, content: str,
                       metadata: dict = None, tier: str = "L1",
                       success: bool = True) -> str:
        """Guarda información en la memoria jerárquica.
        
        Args:
            task_type: Tipo de tarea (ej: "api_rest", "data_pipeline")
            content: Contenido a recordar (texto libre)
            metadata: Metadatos adicionales (archivos, lenguaje, etc.)
            tier: "L1" (short-term) o "L2" (directo a Supabase)
            success: Si la ejecución fue exitosa
            
        Returns:
            entry_id de la entrada creada
        """
        entry_id = hashlib.md5(f"{task_type}:{content[:100]}:{time.time()}".encode()).hexdigest()[:16]
        
        metadata = metadata or {}
        metadata.update({
            "task_type": task_type,
            "success": success,
            "timestamp": time.time(),
        })
        
        entry = MemoryEntry(
            id=entry_id,
            tier=tier,
            content=content[:5000],
            metadata=metadata,
        )
        
        if tier == "L1":
            self._l1_buffer.append(entry)
            if len(self._l1_buffer) > L1_MAX_ENTRIES:
                self._l1_buffer = self._l1_buffer[-L1_MAX_ENTRIES:]
            
            # También añadir al scratchpad de Smith si está disponible
            if self._smith_session:
                summary = f"[{task_type}] {'✅' if success else '❌'} {content[:150]}"
                self._smith_session.add_to_scratchpad(summary)
        
        elif tier == "L2":
            # Guardar directamente en Supabase
            try:
                from src.supabase_utils import save_to_memory
                await save_to_memory(
                    task_type=task_type,
                    content=content,
                    metadata=metadata,
                )
                entry.tier = "L2"
                logger.info(f"L2 saved: {task_type} ({len(content)} chars)")
            except Exception as e:
                logger.warning(f"L2 save failed (Supabase): {e}. Fallback to L1 buffer.")
                self._l1_buffer.append(entry)
        
        # Actualizar estadísticas de dominio
        self._domain_stats[task_type]["count"] += 1
        if success:
            self._domain_stats[task_type]["successes"] += 1
        
        return entry_id
    
    async def recall(self, query: str, max_results: int = 5,
                     tiers: tuple = ("L1", "L2", "L3")) -> Dict[str, Any]:
        """Recupera información relevante de todos los tiers.
        
        Args:
            query: Texto de búsqueda
            max_results: Máximo de resultados por tier
            tiers: Qué tiers consultar (default: todos)
            
        Returns:
            {"L1": [...], "L2": "...", "L3": [...], "summary": "..."}
        """
        results = {}
        
        # L1: Búsqueda local en buffer + SessionMemory
        if "L1" in tiers:
            l1_results = self._search_l1(query, max_results)
            results["L1"] = l1_results
        
        # L2: Búsqueda vectorial en Supabase
        if "L2" in tiers:
            try:
                from src.supabase_utils import hybrid_search
                l2_raw = await hybrid_search(query, limit=max_results)
                # Comprimir si es muy largo
                if len(l2_raw) > 3000:
                    from src.token_juice import compress
                    l2_raw, _ = compress(l2_raw, max_tokens=1000)
                results["L2"] = l2_raw[:3000]
            except Exception as e:
                logger.warning(f"L2 recall failed: {e}")
                results["L2"] = "(L2 no disponible)"
        
        # L3: Reglas y patrones destilados
        if "L3" in tiers:
            l3_results = self._search_l3(query, max_results)
            results["L3"] = l3_results
        
        # Summary para el LLM
        results["summary"] = self._build_recall_summary(results, query)
        
        return results
    
    async def get_context_for_task(self, requirement: str) -> str:
        """Genera contexto consolidado de todos los tiers para una tarea.
        
        Este es el método principal que usa el estratega antes de planificar.
        """
        all_context = await self.recall(requirement, max_results=5)
        
        parts = []
        
        # L3 primero (reglas destiladas — más importante)
        if all_context.get("L3"):
            rules_text = all_context["L3"]
            if rules_text:
                parts.append(f"## Reglas Destiladas (L3)\n{rules_text}")
        
        # L2 (conocimiento vectorizado)
        if all_context.get("L2") and all_context["L2"] != "(L2 no disponible)":
            parts.append(f"## Conocimiento Previo (L2)\n{all_context['L2']}")
        
        # L1 (sesión actual)
        if all_context.get("L1"):
            parts.append(f"## Contexto de Sesión (L1)\n{all_context['L1']}")
        
        # Estadísticas de dominio
        relevant_stats = self._get_relevant_stats(requirement)
        if relevant_stats:
            parts.append(f"## Estadísticas del Dominio\n{relevant_stats}")
        
        return "\n\n".join(parts) if parts else "(sin contexto previo)"
    
    async def get_rules(self) -> List[str]:
        """Devuelve reglas L3 activas como lista de strings."""
        active_rules = []
        for rule_id, rule in self._l3_rules.items():
            if rule.get("active", True):
                active_rules.append(f"[{rule.get('domain', 'general')}] {rule['rule']}")
        return active_rules
    
    async def consolidate(self, force: bool = False) -> dict:
        """Consolida memoria entre tiers: L1→L2, patrones L2→L3.
        
        Args:
            force: Si True, consolida aunque no se alcancen los thresholds
            
        Returns:
            {"consolidated_l1": N, "new_patterns": N, "new_rules": N}
        """
        result = {"consolidated_l1": 0, "new_patterns": 0, "new_rules": 0}
        
        now = time.time()
        if not force and now - self._last_consolidation < 300:  # 5 min cooldown
            return result
        
        # ── L1 → L2: Mover entradas viejas a Supabase ──
        to_consolidate = []
        still_active = []
        
        for entry in self._l1_buffer:
            age = now - entry.created_at
            if force or age > L1_TTL_SECONDS or len(self._l1_buffer) > CONSOLIDATE_THRESHOLD:
                to_consolidate.append(entry)
            else:
                still_active.append(entry)
        
        for entry in to_consolidate:
            try:
                from src.supabase_utils import save_to_memory
                await save_to_memory(
                    task_type=entry.metadata.get("task_type", "general"),
                    content=entry.content,
                    metadata=entry.metadata,
                )
                entry.consolidated_to = "L2"
                result["consolidated_l1"] += 1
            except Exception as e:
                logger.warning(f"Consolidation L1→L2 failed: {e}")
                still_active.append(entry)  # mantener en buffer
        
        self._l1_buffer = still_active
        
        # ── L2 → L3: Detectar patrones y generar reglas ──
        try:
            from src.supabase_utils import hybrid_search
            # Buscar patrones por dominio
            for domain, stats in self._domain_stats.items():
                if stats["count"] >= PATTERN_MIN_FREQ:
                    success_rate = stats["successes"] / max(stats["count"], 1)
                    
                    # Dominio con alta tasa de éxito → pattern
                    if success_rate >= RULE_CONFIDENCE_MIN:
                        pattern_key = f"success_{domain}"
                        if pattern_key not in self._l3_patterns:
                            self._l3_patterns[pattern_key] = []
                        
                        existing = self._l3_patterns[pattern_key]
                        if len(existing) < 10:  # máximo 10 ejemplos por patrón
                            existing.append({
                                "timestamp": now,
                                "success_rate": success_rate,
                                "samples": stats["count"],
                            })
                            result["new_patterns"] += 1
                            
                            # Si tenemos suficientes muestras, generar regla
                            if stats["count"] >= 3 and success_rate >= 0.8:
                                rule_id = f"rule_{domain}_{int(now)}"
                                if rule_id not in self._l3_rules:
                                    self._l3_rules[rule_id] = {
                                        "rule": f"Para tareas tipo '{domain}', aplicar el patrón de arquitectura validado en {stats['count']} ejecuciones previas (tasa de éxito: {success_rate:.0%})",
                                        "domain": domain,
                                        "confidence": success_rate,
                                        "samples": stats["count"],
                                        "active": True,
                                        "created_at": now,
                                    }
                                    result["new_rules"] += 1
                    
                    # Dominio con baja tasa de éxito → anti-pattern
                    elif success_rate <= 0.3 and stats["count"] >= 2:
                        rule_id = f"rule_caution_{domain}_{int(now)}"
                        if rule_id not in self._l3_rules:
                            self._l3_rules[rule_id] = {
                                "rule": f"⚠️ Precaución con tareas tipo '{domain}': tasa de éxito baja ({success_rate:.0%} en {stats['count']} intentos). Revisar enfoque antes de ejecutar.",
                                "domain": domain,
                                "confidence": 1 - success_rate,
                                "samples": stats["count"],
                                "active": True,
                                "created_at": now,
                            }
                            result["new_rules"] += 1
        
        except Exception as e:
            logger.warning(f"L2→L3 consolidation failed: {e}")
        
        if result["consolidated_l1"] or result["new_rules"]:
            self._save_l3()
            logger.info(
                f"Consolidation: {result['consolidated_l1']} L1→L2, "
                f"{result['new_patterns']} patterns, {result['new_rules']} rules"
            )
        
        self._last_consolidation = now
        return result
    
    def get_stats(self) -> dict:
        """Estadísticas de la memoria jerárquica."""
        return {
            "l1_entries": len(self._l1_buffer),
            "l3_rules": len(self._l3_rules),
            "l3_patterns": sum(len(v) for v in self._l3_patterns.values()),
            "domains_tracked": len(self._domain_stats),
            "total_domain_entries": sum(s["count"] for s in self._domain_stats.values()),
            "last_consolidation": self._last_consolidation,
        }
    
    # ── Búsqueda interna ─────────────────────────────────────────
    
    def _search_l1(self, query: str, limit: int) -> str:
        """Búsqueda por keywords en L1 buffer + SessionMemory."""
        results = []
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        for entry in self._l1_buffer:
            score = 0
            content_lower = entry.content.lower()
            for word in query_words:
                if word in content_lower:
                    score += 1
            if score > 0:
                results.append((score, entry))
        
        # También del SessionMemory si existe
        if self._smith_session:
            for turn in self._smith_session.turns[-10:]:
                turn_text = turn.get("user", "") + " " + turn.get("response", "")
                score = sum(1 for w in query_words if w in turn_text.lower())
                if score > 0:
                    results.append((score, turn_text[:300]))
        
        # Ordenar por score descendente
        results.sort(key=lambda x: x[0] if isinstance(x, tuple) else 0, reverse=True)
        
        if not results:
            return "(sin resultados en L1)"
        
        items = []
        for score, entry in results[:limit]:
            if isinstance(entry, MemoryEntry):
                items.append(f"[{entry.metadata.get('task_type', '?')}] {entry.content[:200]}")
            else:
                items.append(str(entry)[:200])
        
        return "\n".join(f"- {item}" for item in items)
    
    def _search_l3(self, query: str, limit: int) -> str:
        """Busca reglas y patrones L3 relevantes."""
        query_lower = query.lower()
        relevant_rules = []
        
        for rule_id, rule in self._l3_rules.items():
            domain = rule.get("domain", "")
            rule_text = rule.get("rule", "")
            if domain in query_lower or any(w in rule_text.lower() for w in query_lower.split()):
                relevant_rules.append(rule)
        
        if not relevant_rules:
            return "(sin reglas L3 relevantes)"
        
        rules_text = []
        for rule in relevant_rules[:limit]:
            domain = rule.get("domain", "general")
            confidence = rule.get("confidence", 0.5)
            active = "✅" if rule.get("active") else "⚠️"
            rules_text.append(
                f"{active} [{domain}] (conf: {confidence:.0%}, {rule.get('samples', '?')} muestras)\n"
                f"   {rule['rule']}"
            )
        
        return "\n".join(rules_text)
    
    def _get_relevant_stats(self, requirement: str) -> str:
        """Encuentra estadísticas de dominio relevantes al requerimiento."""
        req_lower = requirement.lower()
        relevant = []
        
        for domain, stats in self._domain_stats.items():
            # Coincidencia difusa: si alguna palabra del dominio está en el requerimiento
            domain_words = set(domain.replace("_", " ").split())
            if any(w in req_lower for w in domain_words):
                success_rate = stats["successes"] / max(stats["count"], 1)
                relevant.append(
                    f"  {domain}: {stats['count']} ejecuciones, "
                    f"{success_rate:.0%} éxito"
                )
        
        return "\n".join(relevant) if relevant else ""
    
    def _build_recall_summary(self, results: dict, query: str) -> str:
        """Genera un resumen consolidado para el LLM."""
        parts = [f"Contexto recuperado para: '{query[:100]}'"]
        
        if results.get("L3") and results["L3"] != "(sin reglas L3 relevantes)":
            parts.append(f"\n### Reglas Activas (L3)\n{results['L3']}")
        
        if results.get("L2") and results["L2"] != "(L2 no disponible)":
            l2 = results["L2"]
            preview = l2[:500] + ("..." if len(l2) > 500 else "")
            parts.append(f"\n### Conocimiento Previo (L2)\n{preview}")
        
        if results.get("L1") and results["L1"] != "(sin resultados en L1)":
            parts.append(f"\n### Sesión Actual (L1)\n{results['L1']}")
        
        return "\n".join(parts)
    
    # ── Persistencia L3 ─────────────────────────────────────────
    
    def _save_l3(self):
        """Guarda reglas y patrones L3 a disco."""
        try:
            RULES_FILE.write_text(json.dumps(self._l3_rules, indent=2, ensure_ascii=False))
            patterns_serializable = {
                k: v for k, v in self._l3_patterns.items()
            }
            PATTERNS_FILE.write_text(json.dumps(patterns_serializable, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Failed to save L3: {e}")
    
    def _load_l3(self):
        """Carga reglas y patrones L3 desde disco."""
        try:
            if RULES_FILE.exists():
                self._l3_rules = json.loads(RULES_FILE.read_text())
                logger.info(f"L3 loaded: {len(self._l3_rules)} rules")
        except Exception as e:
            logger.warning(f"Failed to load L3 rules: {e}")
            self._l3_rules = {}
        
        try:
            if PATTERNS_FILE.exists():
                loaded = json.loads(PATTERNS_FILE.read_text())
                self._l3_patterns = defaultdict(list, loaded)
        except Exception:
            self._l3_patterns = defaultdict(list)
    
    def clear_l1(self):
        """Limpia el buffer L1 (útil al cambiar de tarea)."""
        self._l1_buffer = []
