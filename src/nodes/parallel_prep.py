"""Nodo 0 — Preparación Paralela.
Ejecuta Investigator (RAG), SkillResolver (inyección de skills), y
LessonsEngine (inyección de lecciones aprendidas) en paralelo.

Optimización Fase 2: Reduce tiempo de preparación de secuencial a paralelo.
Mejora RL: Inyecta lecciones aprendidas como contexto + business_rules.
"""

import asyncio
from src.state import TeamState
from src.nodes.investigator import investigator_node
from src.nodes.skill_resolver import skill_resolver_node
from src.lessons_engine import get_lessons_context, generate_business_rules
from src.token_juice import compress


async def parallel_prep_node(state: TeamState) -> dict:
    """Ejecuta Investigator + SkillResolver + inyección de lecciones en paralelo."""
    print("[ParallelPrep] Lanzando Investigator + SkillResolver en paralelo...")
    print("[ParallelPrep] 🧠 Cargando lecciones aprendidas para inyección...")

    # Ejecutar ambos nodos concurrentemente
    inv_future = asyncio.create_task(investigator_node(dict(state)))
    skill_future = asyncio.create_task(skill_resolver_node(dict(state)))

    inv_result, skill_result = await asyncio.gather(inv_future, skill_future)

    # Fusionar resultados
    merged = {}

    # Investigator produce: retrieved_memory, audit_trail, messages
    merged["retrieved_memory"] = inv_result.get(
        "retrieved_memory",
        "[Sin memoria previa — paralelo]"
    )

    # SkillResolver produce: business_rules, retrieved_memory (ampliada),
    #                        injected_skills, scratchpad, audit_trail
    merged["business_rules"] = skill_result.get("business_rules", [])

    # 🧠 INYECCIÓN DE LECCIONES APRENDIDAS (Ciclo RL)
    requirement = state.get("user_requirement", "")
    
    # 1. Lecciones como contexto en retrieved_memory
    lessons_context = get_lessons_context(requirement)
    if lessons_context:
        merged["retrieved_memory"] = (
            f"{merged.get('retrieved_memory', '')}\n\n"
            f"{lessons_context}"
        )
        print(f"[ParallelPrep] 🧠 {len(lessons_context)} chars de lecciones inyectadas")

    # 2. Reglas de negocio desde lecciones
    lesson_rules = generate_business_rules(requirement)
    if lesson_rules:
        existing_rules = merged.get("business_rules", [])
        # Evitar duplicados
        existing_set = set(existing_rules)
        for rule in lesson_rules:
            if rule not in existing_set:
                existing_rules.append(rule)
                existing_set.add(rule)
        merged["business_rules"] = existing_rules
        print(f"[ParallelPrep] 📋 {len(lesson_rules)} reglas desde lessons engine")

    # La memoria combinada: investigator + skills
    inv_memory = inv_result.get("retrieved_memory", "")
    skill_memory = skill_result.get("retrieved_memory", "")
    if skill_memory and skill_memory != inv_memory:
        merged["retrieved_memory"] = f"{inv_memory}\n\n[Skills inyectadas]\n{skill_memory}"
    else:
        merged["retrieved_memory"] = inv_memory

    merged["injected_skills"] = skill_result.get("injected_skills", {
        "matched": [], "rules": [], "blueprint": "", "code": "", "checks": ""
    })

    # Combinar scratchpads
    merged["scratchpad"] = (
        inv_result.get("scratchpad", []) +
        skill_result.get("scratchpad", [])
    )

    # Combinar audit_trails
    merged["audit_trail"] = (
        inv_result.get("audit_trail", []) +
        skill_result.get("audit_trail", [])
    )

    # Combinar messages
    merged["messages"] = (
        inv_result.get("messages", []) +
        skill_result.get("messages", [])
    )

    # 🧃 TOKENJUICE: comprimir la memoria recuperada antes de enviar al LLM
    raw_memory = merged["retrieved_memory"]
    if len(raw_memory) > 500:
        compressed_memory, juice_report = compress(raw_memory, max_tokens=2000)
        if juice_report["compressed"]:
            merged["retrieved_memory"] = compressed_memory
            merged["token_juice_report"] = juice_report
            print(f"[ParallelPrep] 🧃 TokenJuice: {juice_report['tokens_before']}→"
                  f"{juice_report['tokens_after']} tokens "
                  f"({juice_report['saved_pct']}% ahorro en RAG context)")

    print(f"[ParallelPrep] Completo: "
          f"memoria={len(merged['retrieved_memory'])} chars, "
          f"rules={len(merged['business_rules'])} reglas, "
          f"skills={len(merged['injected_skills'].get('matched', []))} activadas")

    return merged
