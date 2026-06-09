"""Nodo 0 — Preparación Paralela OPTIMIZADA.
Ejecuta Investigator (RAG) + LessonsEngine en paralelo.
SkillResolver eliminado (P0: simplificación x10).

OPTIMIZACIONES:
  - Cache RAG persistente (evita recarga en ejecuciones repetidas)
  - Sin SkillResolver (ahorra 1-2 calls flash por ejecución)
  - Solo RAG + lecciones aprendidas (lo esencial)
  - TokenJuice integrado
"""

import asyncio
import hashlib
import json
import time
import os
from pathlib import Path
from src.state import TeamState
from src.nodes.investigator import investigator_node
from src.lessons_engine import get_lessons_context, generate_business_rules
from src.token_juice import compress

# ── Cache de RAG ──
_RAG_CACHE_DIR = Path.home() / ".agents" / "rag_cache"
_RAG_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Cache en memoria para evitar lecturas de disco repetidas
_memory_cache = {}


def _get_rag_cache_key(requirement: str) -> str:
    """Genera un hash del requirement para usar como clave de cache."""
    normalized = ' '.join(requirement.lower().split())
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


def _load_rag_cache(requirement: str) -> dict | None:
    """Carga resultado cacheado si existe."""
    cache_key = _get_rag_cache_key(requirement)
    
    # Check memory cache first
    if cache_key in _memory_cache:
        print(f"[ParallelPrep] 🎯 Memory cache HIT")
        return _memory_cache[cache_key]
    
    cache_file = _RAG_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            if time.time() - cached.get("timestamp", 0) < 3600:
                print(f"[ParallelPrep] 🎯 Disk cache HIT")
                _memory_cache[cache_key] = cached.get("result")
                return cached.get("result")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_rag_cache(requirement: str, result: dict):
    """Guarda resultado en cache."""
    cache_key = _get_rag_cache_key(requirement)
    cache_file = _RAG_CACHE_DIR / f"{cache_key}.json"
    
    try:
        has_content = (
            len(result.get("retrieved_memory", "")) > 100
            or len(result.get("business_rules", [])) > 0
        )
        if has_content:
            cache_data = {
                "timestamp": time.time(),
                "result": {
                    "retrieved_memory": result.get("retrieved_memory", ""),
                    "business_rules": result.get("business_rules", []),
                    "scratchpad": result.get("scratchpad", []),
                }
            }
            with open(cache_file, "w") as f:
                json.dump(cache_data, f)
            _memory_cache[cache_key] = cache_data["result"]
    except (OSError, json.JSONEncodeError):
        pass


async def parallel_prep_node(state: TeamState) -> dict:
    """Preparación paralela OPTIMIZADA: RAG + lecciones, sin SkillResolver."""
    requirement = state.get("user_requirement", "")
    
    # ── Intentar cache ──
    cached = _load_rag_cache(requirement)
    if cached:
        print(f"[ParallelPrep] Usando cache — saltando Investigador")
        lessons = get_lessons_context(requirement)
        if lessons:
            cached["retrieved_memory"] = f"{cached.get('retrieved_memory', '')}\n\n{lessons}"
        lesson_rules = generate_business_rules(requirement)
        if lesson_rules:
            existing = set(cached.get("business_rules", []))
            for rule in lesson_rules:
                if rule not in existing:
                    cached["business_rules"].append(rule)
                    existing.add(rule)
        
        # TokenJuice
        raw = cached.get("retrieved_memory", "")
        if len(raw) > 500:
            compressed, report = compress(raw, max_tokens=2000)
            if report["compressed"]:
                cached["retrieved_memory"] = compressed
        
        print(f"[ParallelPrep] Cache OK: memoria={len(cached.get('retrieved_memory',''))} chars")
        return cached
    
    # ── Cache MISS ──
    print("[ParallelPrep] Cache MISS — ejecutando Investigador...")
    inv_result = await investigator_node(dict(state))
    
    # Lessons engine
    lessons = get_lessons_context(requirement)
    if lessons:
        inv_result["retrieved_memory"] = f"{inv_result.get('retrieved_memory', '')}\n\n{lessons}"
        print(f"[ParallelPrep] 📚 {len(lessons)} chars de lecciones inyectadas")
    
    lesson_rules = generate_business_rules(requirement)
    if lesson_rules:
        existing_rules = set(inv_result.get("business_rules", []))
        for rule in lesson_rules:
            if rule not in existing_rules:
                inv_result["business_rules"] = inv_result.get("business_rules", []) + [rule]
                existing_rules.add(rule)
    
    merged = {
        "retrieved_memory": inv_result.get("retrieved_memory", "[Sin memoria]"),
        "business_rules": inv_result.get("business_rules", []),
        "injected_skills": {"matched": [], "rules": [], "blueprint": "", "code": "", "checks": ""},
        "scratchpad": inv_result.get("scratchpad", []),
        "audit_trail": inv_result.get("audit_trail", []),
        "messages": inv_result.get("messages", []),
    }
    
    # TokenJuice
    raw = merged["retrieved_memory"]
    if len(raw) > 500:
        compressed, report = compress(raw, max_tokens=2000)
        if report["compressed"]:
            merged["retrieved_memory"] = compressed
            print(f"[ParallelPrep] 🧃 TokenJuice: {report['tokens_before']}→{report['tokens_after']} tokens")
    
    print(f"[ParallelPrep] OK: memoria={len(merged['retrieved_memory'])} chars, rules={len(merged['business_rules'])}")
    
    # Cachear
    _save_rag_cache(requirement, merged)
    
    return merged
