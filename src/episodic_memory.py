"""🧠 Episodic Memory Buffer — Memoria Episódica con Reflexión Verbal.

Basado en el framework Reflexion (Shinn et al., 2023):
  "Language Agents with Verbal Reinforcement Learning"

ARQUITECTURA:
  ```
  Ejecución completa
         ↓
  1. Archivar episodio en buffer (requerimiento, plan, código, errores)
         ↓
  2. Generar auto-crítica (reflective text)
         ↓
  3. Extraer heurísticas aprendidas
         ↓
  4. Inyectar heurísticas en prompts de futuras ejecuciones
         ↓
  5. Detectar patrones de mejora/empeoramiento
  ```

DIFERENCIA CON lessons_engine.py:
  - LessonsEngine: extrae lecciones genéricas del dominio (knowledge)
  - EpisodicMemory: guarda episodios COMPLETOS con auto-crítica (experience)
  - Se complementan: LessonsEngine = qué aprender, EpisodicMemory = cómo aprenderlo
"""

import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── Constantes ──
EPISODIC_DIR = Path.home() / ".agents" / "episodic_memory"
EPISODES_FILE = EPISODIC_DIR / "episodes.json"
HEURISTICS_FILE = EPISODIC_DIR / "heuristics.json"
MAX_EPISODES = 100          # Máximo de episodios en memoria activa
MAX_HEURISTICS_IN_CONTEXT = 5  # Heurísticas visibles por inyección


def _ensure_dirs():
    """Crea directorios de memoria episódica."""
    EPISODIC_DIR.mkdir(parents=True, exist_ok=True)


def _load_episodes() -> list[dict]:
    """Carga todos los episodios almacenados."""
    _ensure_dirs()
    if EPISODES_FILE.exists():
        try:
            with open(EPISODES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_episodes(episodes: list[dict]):
    """Guarda episodios, manteniendo máximo activo."""
    _ensure_dirs()
    # Mantener solo los más recientes
    episodes = sorted(episodes, key=lambda e: e.get("timestamp", ""), reverse=True)
    episodes = episodes[:MAX_EPISODES]
    try:
        with open(EPISODES_FILE, "w") as f:
            json.dump(episodes, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[EpisodicMemory] ⚠️ Error guardando: {e}")


def _load_heuristics() -> list[dict]:
    """Carga heurísticas aprendidas."""
    _ensure_dirs()
    if HEURISTICS_FILE.exists():
        try:
            with open(HEURISTICS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_heuristics(heuristics: list[dict]):
    """Guarda heurísticas."""
    _ensure_dirs()
    try:
        with open(HEURISTICS_FILE, "w") as f:
            json.dump(heuristics, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[EpisodicMemory] ⚠️ Error guardando heurísticas: {e}")


# ═══════════════════════════════════════════════════════════════
# 1. ARCHIVAR EPISODIO
# ═══════════════════════════════════════════════════════════════

def archive_episode(
    requirement: str,
    blueprint: dict,
    source_code: dict,
    test_report: dict,
    audit_trail: list,
    iteration_count: int,
    success: bool,
    scratchpad: list = None,
    self_reflection: str = "",
    heuristics_learned: list = None,
) -> dict:
    """Archiva un episodio completo de ejecución en el buffer.
    
    Args:
        requirement: Requerimiento original
        blueprint: Arquitectura diseñada
        source_code: Código generado
        test_report: Reporte de tests
        audit_trail: Trazabilidad del pipeline
        iteration_count: Iteraciones usadas
        success: Si fue exitoso
        scratchpad: Notas de iteración
        self_reflection: Auto-crítica generada
        heuristics_learned: Heurísticas extraídas
    
    Returns:
        El episodio archivado
    """
    scratchpad = scratchpad or []
    heuristics_learned = heuristics_learned or []
    
    # Resumir errores para búsqueda rápida
    errors = test_report.get("errors", [])
    error_summary = [str(e)[:150] for e in errors[:5]]
    
    episode = {
        "episode_id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "requirement": requirement[:300],
        "domain": _infer_domain(requirement),
        "success": success,
        "iteration_count": iteration_count,
        "error_count": len(errors),
        "error_summary": error_summary,
        "file_count": len(source_code) if source_code else 0,
        "self_reflection": self_reflection,
        "heuristics_learned": heuristics_learned,
        # Para futuro análisis: datos compactos
        "metadata": {
            "blueprint_files": list(blueprint.get("archivos", {}).keys()) if blueprint else [],
            "technologies": blueprint.get("tecnologias_sugeridas", []) if blueprint else [],
            "iterations_breakdown": _count_node_calls(audit_trail),
        },
    }
    
    # Guardar en buffer
    episodes = _load_episodes()
    episodes.append(episode)
    _save_episodes(episodes)
    
    print(f"[EpisodicMemory] 📝 Episodio {episode['episode_id']} archivado "
          f"({'✅' if success else '❌'} {iteration_count} iter, {len(errors)} errors)")
    
    return episode


def _infer_domain(requirement: str) -> str:
    """Infiera el dominio del requerimiento."""
    req_lower = requirement.lower()
    domains = {
        "api": "api_rest",
        "rest": "api_rest",
        "flask": "api_flask",
        "database": "base_de_datos",
        "db": "base_de_datos",
        "csv": "procesamiento_datos",
        "json": "procesamiento_datos",
        "pipeline": "pipeline_datos",
        "cli": "herramienta_cli",
        "script": "script",
        "mcp": "mcp_server",
        "web": "web",
        "html": "web",
        "test": "testing",
        "pytest": "testing",
    }
    for keyword, domain in domains.items():
        if keyword in req_lower:
            return domain
    return "general"


def _count_node_calls(audit_trail: list) -> dict:
    """Cuenta llamadas por nodo para análisis de eficiencia."""
    counts = {}
    for entry in audit_trail:
        nodo = entry.get("nodo", "unknown")
        counts[nodo] = counts.get(nodo, 0) + 1
    return counts


# ═══════════════════════════════════════════════════════════════
# 2. GENERAR AUTO-CRÍTICA (Reflective Text)
# ═══════════════════════════════════════════════════════════════

def generate_self_reflection(
    requirement: str,
    test_report: dict,
    iteration_count: int,
    source_code: dict,
    scratchpad: list,
    blueprint: dict = None,
) -> str:
    """Genera auto-crítica estructurada del episodio.
    
    Sigue el patrón Reflexion: analiza qué salió mal y por qué.
    
    Returns:
        Texto de auto-crítica para inyectar en futuras ejecuciones
    """
    status = test_report.get("status", "UNKNOWN")
    success = status == "PASS"
    errors = test_report.get("errors", [])
    
    lines = []
    lines.append(f"## Auto-Crítica: {'✅ Éxito' if success else '❌ Fallo'}")
    lines.append(f"Iteraciones: {iteration_count}")
    lines.append(f"")
    
    if success:
        lines.append("### ¿Qué funcionó bien?")
        lines.append(f"- El requerimiento '{requirement[:100]}' se completó exitosamente")
        files = list(source_code.keys()) if source_code else []
        if files:
            lines.append(f"- Archivos generados: {', '.join(files[:5])}")
        lines.append("")
        lines.append("### ¿Qué se puede mejorar?")
        lines.append(f"- Se usaron {iteration_count} iteraciones. Ideal: <3.")
        lines.append("- Revisar si el código es óptimo o hay redundancia")
    else:
        lines.append("### ¿Qué salió mal?")
        for error in errors[:3]:
            lines.append(f"- ERROR: {str(error)[:200]}")
        lines.append("")
        
        # Analizar causas desde scratchpad
        scratch_entries = scratchpad[-5:] if scratchpad else []
        if scratch_entries:
            lines.append("### Intentos de correción:")
            for entry in scratch_entries:
                lines.append(f"- {str(entry)[:150]}")
        
        lines.append("")
        lines.append("### Hipótesis de causa raíz:")
        lines.append("- [Auto-análisis pendiente]")
        
        lines.append("")
        lines.append("### Recomendación para próxima iteración:")
        lines.append("- Verificar imports y dependencias primero")
        lines.append("- Probar el código antes de asumir que funciona")
        lines.append("- Dividir el problema en partes más pequeñas")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 3. EXTRAER HEURÍSTICAS APRENDIDAS
# ═══════════════════════════════════════════════════════════════

def extract_heuristics(episode: dict) -> list[str]:
    """Extrae heurísticas generalizables de un episodio.
    
    Las heurísticas son reglas "si → entonces" que capturan
    conocimiento reutilizable para futuros episodios similares.
    
    Args:
        episode: Episodio archivado
    
    Returns:
        Lista de strings de heurísticas
    """
    heuristics = []
    errors = episode.get("error_summary", [])
    domain = episode.get("domain", "general")
    success = episode.get("success", False)
    
    if success:
        # De episodios exitosos: patrones a repetir
        heuristics.append(
            f"[HEURÍSTICA: {domain}] Las tareas que requieren "
            f"{episode.get('file_count', 0)} archivos y "
            f"{episode.get('iteration_count', 0)} iteraciones "
            f"suelen ser exitosas con el approach actual"
        )
    else:
        # De episodios fallidos: anti-patrones
        for error in errors[:2]:
            if "import" in error.lower():
                heuristics.append(
                    f"[HEURÍSTICA: {domain}] Error de import detectado. "
                    f"Siempre verificar que las dependencias están en requirements.txt "
                    f"y se instalan antes de ejecutar"
                )
            elif "syntax" in error.lower() or "Syntax" in error:
                heuristics.append(
                    f"[HEURÍSTICA: {domain}] Error de sintaxis. "
                    f"Usar linter automático antes de considerar el código finalizado"
                )
            elif "name" in error.lower() and "not defined" in error.lower():
                heuristics.append(
                    f"[HEURÍSTICA: {domain}] Variable/función no definida. "
                    f"Verificar que todos los nombres están correctamente importados o definidos"
                )
    
    return heuristics


# ═══════════════════════════════════════════════════════════════
# 4. INYECTAR HEURÍSTICAS EN PROMPTS
# ═══════════════════════════════════════════════════════════════

def get_heuristics_context(domain: str = None) -> str:
    """Genera texto de heurísticas para inyectar en prompts de agentes.
    
    Args:
        domain: Si se especifica, filtra heurísticas por dominio
    
    Returns:
        Texto formateado para inyectar en system prompt
    """
    heuristics = _load_heuristics()
    
    if not heuristics:
        return ""
    
    # Filtrar por dominio si se especifica
    if domain:
        domain_heuristics = [
            h for h in heuristics
            if domain.lower() in h.get("domain", "").lower()
        ]
        # Si no hay del dominio específico, usar generales
        if domain_heuristics:
            heuristics = domain_heuristics
    
    # Ordenar por frecuencia de uso (más usadas primero)
    heuristics.sort(key=lambda h: h.get("applied_count", 0), reverse=True)
    
    # Tomar las más relevantes
    selected = heuristics[:MAX_HEURISTICS_IN_CONTEXT]
    
    lines = [
        "\n" + "─" * 50,
        "  🧠 HEURÍSTICAS APRENDIDAS (Memoria Episódica)",
        "─" * 50,
    ]
    
    for i, h in enumerate(selected, 1):
        text = h.get("text", "")
        frequency = h.get("applied_count", 0)
        source = h.get("source_episode", "?")
        lines.append(f"\n  [{i}] (x{frequency}) {text}")
    
    lines.append("─" * 50)
    lines.append("")
    
    return "\n".join(lines)


def learn_heuristic(heuristic_text: str, domain: str, source_episode: str):
    """Registra una nueva heurística o refuerza una existente.
    
    Args:
        heuristic_text: Texto de la heurística
        domain: Dominio al que aplica
        source_episode: ID del episodio que la originó
    """
    heuristics = _load_heuristics()
    
    # Buscar si ya existe una similar
    for h in heuristics:
        if h.get("text") == heuristic_text:
            h["occurrences"] = h.get("occurrences", 1) + 1
            h["last_seen"] = datetime.now().isoformat()
            _save_heuristics(heuristics)
            print(f"[EpisodicMemory] 🔄 Heurística reforzada (x{h['occurrences']}): {heuristic_text[:60]}")
            return
    
    # Nueva heurística
    new_h = {
        "id": f"heur_{len(heuristics) + 1}",
        "text": heuristic_text,
        "domain": domain,
        "source_episode": source_episode,
        "occurrences": 1,
        "applied_count": 0,
        "created": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
    }
    heuristics.append(new_h)
    _save_heuristics(heuristics)
    print(f"[EpisodicMemory] ✅ Nueva heurística: {heuristic_text[:60]}")


# ═══════════════════════════════════════════════════════════════
# 5. DETECTAR PATRONES DE MEJORA
# ═══════════════════════════════════════════════════════════════

def analyze_trends(domain: str = None) -> dict:
    """Analiza tendencias de rendimiento en episodios recientes.
    
    Args:
        domain: Filtrar por dominio
    
    Returns:
        Dict con análisis de tendencias
    """
    episodes = _load_episodes()
    
    if domain:
        episodes = [e for e in episodes if e.get("domain") == domain]
    
    if len(episodes) < 3:
        return {"message": "Se necesitan al menos 3 episodios para análisis de tendencias"}
    
    # Ordenar por timestamp
    episodes.sort(key=lambda e: e.get("timestamp", ""))
    
    # Últimos N episodios
    recent = episodes[-10:]
    
    # Calcular tendencias
    success_rate = sum(1 for e in recent if e.get("success")) / len(recent)
    avg_iterations = sum(e.get("iteration_count", 0) for e in recent) / len(recent)
    avg_errors = sum(e.get("error_count", 0) for e in recent) / len(recent)
    
    # Mejora/empeoramiento (comparar primeros 5 vs últimos 5)
    if len(recent) >= 10:
        first_half = recent[:5]
        second_half = recent[-5:]
        
        first_success = sum(1 for e in first_half if e.get("success")) / len(first_half)
        second_success = sum(1 for e in second_half if e.get("success")) / len(second_half)
        
        trend = "mejorando" if second_success > first_success else "empeorando" if second_success < first_success else "estable"
    else:
        trend = "insuficientes_datos"
    
    return {
        "domain": domain or "todos",
        "total_episodes": len(episodes),
        "recent_episodes": len(recent),
        "success_rate": round(success_rate, 3),
        "avg_iterations": round(avg_iterations, 1),
        "avg_errors": round(avg_errors, 1),
        "trend": trend,
    }


# ═══════════════════════════════════════════════════════════════
# 6. API PRINCIPAL PARA EL NODO DE REFLEXIÓN
# ═══════════════════════════════════════════════════════════════

def process_episode(state: dict) -> dict:
    """Procesa un episodio completo: archiva, reflexiona, aprende.
    
    Este es el método principal que se llama desde reflection.py.
    
    Args:
        state: TeamState completo de la ejecución
    
    Returns:
        dict con resultados del procesamiento episódico
    """
    requirement = state.get("user_requirement", "")
    blueprint = state.get("architecture_blueprint", {})
    source_code = state.get("source_code", {})
    test_report = state.get("test_report", {})
    audit_trail = state.get("audit_trail", [])
    scratchpad = state.get("scratchpad", [])
    iteration_count = state.get("iteration_count", 0)
    success = test_report.get("status") == "PASS"
    
    # 1. Generar auto-crítica
    self_reflection = generate_self_reflection(
        requirement=requirement,
        test_report=test_report,
        iteration_count=iteration_count,
        source_code=source_code,
        scratchpad=scratchpad,
        blueprint=blueprint,
    )
    
    # 2. Extraer heurísticas del episodio
    raw_episode = {
        "success": success,
        "error_summary": [str(e)[:150] for e in test_report.get("errors", [])[:5]],
        "domain": _infer_domain(requirement),
        "file_count": len(source_code) if source_code else 0,
        "iteration_count": iteration_count,
    }
    heuristics = extract_heuristics(raw_episode)
    
    # 3. Archivar episodio
    domain = _infer_domain(requirement)
    episode = archive_episode(
        requirement=requirement,
        blueprint=blueprint,
        source_code=source_code,
        test_report=test_report,
        audit_trail=audit_trail,
        iteration_count=iteration_count,
        success=success,
        scratchpad=scratchpad,
        self_reflection=self_reflection,
        heuristics_learned=heuristics,
    )
    
    # 4. Aprender heurísticas
    for h in heuristics:
        learn_heuristic(h, domain, episode["episode_id"])
    
    # 5. Analizar tendencias
    trends = analyze_trends(domain)
    
    # 6. Generar contexto de heurísticas
    context = get_heuristics_context(domain)
    
    return {
        "episode_id": episode["episode_id"],
        "self_reflection": self_reflection,
        "heuristics_extracted": len(heuristics),
        "trends": trends,
        "heuristics_context": context,
    }


# ═══════════════════════════════════════════════════════════════
# 7. UTILIDADES DE DIAGNÓSTICO
# ═══════════════════════════════════════════════════════════════

def show_status() -> str:
    """Muestra el estado completo de la memoria episódica."""
    episodes = _load_episodes()
    heuristics = _load_heuristics()
    
    active = [e for e in episodes if not e.get("archived", False)]
    total_success = sum(1 for e in active if e.get("success"))
    total_fail = sum(1 for e in active if not e.get("success"))
    
    # Por dominio
    by_domain = {}
    for e in active:
        d = e.get("domain", "unknown")
        if d not in by_domain:
            by_domain[d] = {"total": 0, "success": 0}
        by_domain[d]["total"] += 1
        if e.get("success"):
            by_domain[d]["success"] += 1
    
    lines = [
        "=" * 60,
        "  🧠 EPISODIC MEMORY — Estado del Sistema",
        "=" * 60,
        f"  Episodios totales: {len(active)}",
        f"  ✅ Éxitos: {total_success}",
        f"  ❌ Fallos: {total_fail}",
        f"  📊 Tasa de éxito: {(total_success / len(active) * 100):.1f}%" if active else "  📊 Tasa de éxito: N/A",
        f"  💡 Heurísticas aprendidas: {len(heuristics)}",
        "",
        "  Por dominio:",
    ]
    
    for domain, stats in sorted(by_domain.items(), key=lambda x: -x[1]["total"]):
        rate = (stats["success"] / stats["total"] * 100) if stats["total"] else 0
        lines.append(f"    • {domain}: {stats['total']} runs, {rate:.0f}% éxito")
    
    lines.append("")
    if heuristics:
        lines.append("  Últimas heurísticas:")
        for h in heuristics[-5:]:
            lines.append(f"    • [{h.get('domain', '?')}] x{h.get('occurrences', 1)}: {h.get('text', '')[:80]}")
    
    lines.append("=" * 60)
    return "\n".join(lines)


def reset_memory():
    """Resetea toda la memoria episódica."""
    _ensure_dirs()
    if EPISODES_FILE.exists():
        EPISODES_FILE.unlink()
    if HEURISTICS_FILE.exists():
        HEURISTICS_FILE.unlink()
    print("[EpisodicMemory] 🔄 Memoria episódica reseteada")
