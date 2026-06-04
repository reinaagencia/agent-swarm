"""🧠 Lessons Engine — Motor de Aprendizaje por Refuerzo Continuo.

CICLO RL COMPLETO:
1. EXTRACCIÓN: Cada ejecución (PASS/FAIL) produce lecciones estructuradas
2. ALMACENAMIENTO: Lecciones en ~/.agents/lessons/*.json + Supabase
3. DETECCIÓN: Patrones repetidos (2+) generan reglas automáticas
4. INYECCIÓN: Reglas aprendidas → business_rules en futuras tareas
5. REFUERZO: Señal compuesta → router.aprender() ajusta thresholds

CATEGORÍAS DE LECCIONES:
  - pattern:      Éxito repetible (algo que funcionó bien)
  - anti-pattern: Error a evitar (algo que falló sistemáticamente)
  - pitfall:      Error común con solución conocida
  - optimization: Mejora de eficiencia (menos tokens, menos iteraciones)

ARQUITECTURA:
  LessonsEngine (estático, sin estado)
    ├── extract_lessons()          # Extrae lecciones del estado de ejecución
    ├── store_lesson()             # Guarda lección en JSON + Supabase
    ├── load_lessons()             # Carga lecciones recientes/por dominio
    ├── detect_patterns()          # Busca patrones repetidos (2+)
    ├── generate_business_rules()  # Convierte patrones en reglas
    ├── compute_reinforcement_signal() # Señal compuesta 0.0-1.0
    ├── get_scoreboard()           # Rendimiento por tipo de tarea
    ├── archive_old_lessons()      # Archiva lecciones >30 días sin uso
    └── get_lessons_context()      # Texto para inyectar en prompts
"""

import json
import os
import hashlib
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Optional

from src.metrics import get_recent_runs, get_summary

# ── Constantes ──
LESSONS_DIR = Path.home() / ".agents" / "lessons"
LESSONS_FILE = LESSONS_DIR / "lessons.json"
RULES_FILE = LESSONS_DIR / "rules.json"
SCOREBOARD_FILE = LESSONS_DIR / "scoreboard.json"
ARCHIVE_DIR = LESSONS_DIR / "archive"
MAX_LESSONS_IN_CONTEXT = 8       # Máximas lecciones visibles por inyección
LESSON_ACTIVE_DAYS = 30          # Días antes de archivar lección no usada
PATTERN_MIN_OCCURRENCES = 2      # Mínimo de ocurrencias para considerar patrón

# Señal de refuerzo: pesos para cada componente
REINFORCEMENT_WEIGHTS = {
    "success": 0.40,      # ¿Terminó en PASS?
    "efficiency": 0.30,   # ¿Usó pocas iteraciones?
    "quality": 0.30,      # ¿Código limpio, pocos errores?
}

LESSON_CATEGORIES = ("pattern", "anti-pattern", "pitfall", "optimization")


def _ensure_dirs():
    """Crea directorios de lecciones si no existen."""
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def _fingerprint(text: str) -> str:
    """Genera un hash de un texto para detectar lecciones duplicadas."""
    return hashlib.md5(text.strip().lower().encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════
# 1. EXTRACCIÓN DE LECCIONES
# ═══════════════════════════════════════════════════════════════

def extract_lessons(
    requirement: str,
    source_code: dict,
    test_report: dict,
    blueprint: dict,
    audit_trail: list,
    iteration_count: int,
    success: bool,
    scratchpad: list = None,
) -> list[dict]:
    """Extrae lecciones estructuradas del estado de una ejecución.
    
    Analiza:
    - Éxito/fallo y por qué
    - Errores recurrentes detectados
    - Patrones de código que funcionaron
    - Optimizaciones de eficiencia
    - Decisiones técnicas acertadas/erróneas
    
    Returns:
        Lista de lecciones con estructura:
        {
            "id": str (fingerprint),
            "category": "pattern"|"anti-pattern"|"pitfall"|"optimization",
            "title": str,
            "description": str,
            "domain": str (task_type inferido),
            "origin_task": str (requirement resumido),
            "origin_iteration": int,
            "code_snippet": str (opcional),
            "success": bool (vino de ejecución exitosa),
            "occurrences": 1,
            "first_seen": str (ISO datetime),
            "last_seen": str (ISO datetime),
            "applied_count": 0,
            "archived": False,
        }
    """
    scratchpad = scratchpad or []
    lessons = []
    domain = _infer_domain(requirement, blueprint)
    now = datetime.now().isoformat()
    
    # ── 1. Lección de ÉXITO/FRACASO general ──
    if success:
        lessons.append({
            "id": _fingerprint(f"success_pattern_{requirement[:80]}"),
            "category": "pattern",
            "title": f"Ejecución exitosa: {domain}",
            "description": _extract_success_pattern(requirement, source_code, audit_trail),
            "domain": domain,
            "origin_task": requirement[:120],
            "origin_iteration": iteration_count,
            "code_snippet": _get_key_snippet(source_code),
            "success": True,
            "occurrences": 1,
            "first_seen": now,
            "last_seen": now,
            "applied_count": 0,
            "archived": False,
        })
    else:
        lessons.append({
            "id": _fingerprint(f"failure_pattern_{requirement[:80]}"),
            "category": "anti-pattern",
            "title": f"Fallo detectado: {domain}",
            "description": _extract_failure_pattern(requirement, test_report, audit_trail, scratchpad),
            "domain": domain,
            "origin_task": requirement[:120],
            "origin_iteration": iteration_count,
            "code_snippet": "",
            "success": False,
            "occurrences": 1,
            "first_seen": now,
            "last_seen": now,
            "applied_count": 0,
            "archived": False,
        })
    
    # ── 2. Errores específicos del Tester ──
    tester_errors = test_report.get("errors", [])
    seen_errors = set()
    for error in tester_errors[:3]:  # Top 3 errores
        err_text = str(error)[:150]
        err_fp = _fingerprint(err_text)
        if err_text and err_fp not in seen_errors:
            seen_errors.add(err_fp)
            lessons.append({
                "id": err_fp,
                "category": "pitfall",
                "title": f"Error de {domain}: {err_text[:60]}",
                "description": f"Error detectado en tarea de {domain}: {err_text}",
                "domain": domain,
                "origin_task": requirement[:120],
                "origin_iteration": iteration_count,
                "code_snippet": "",
                "success": success,
                "occurrences": 1,
                "first_seen": now,
                "last_seen": now,
                "applied_count": 0,
                "archived": False,
            })
    
    # ── 3. Optimizaciones de eficiencia ──
    max_iter = 10
    if iteration_count <= 2 and success:
        lessons.append({
            "id": _fingerprint(f"efficient_{domain}_{iteration_count}"),
            "category": "optimization",
            "title": f"{domain} resuelto en solo {iteration_count} iteración(es)",
            "description": f"Tarea de {domain} completada en {iteration_count} iteraciones "
                           f"(rápida). El approach usado fue eficiente.",
            "domain": domain,
            "origin_task": requirement[:120],
            "origin_iteration": iteration_count,
            "code_snippet": "",
            "success": True,
            "occurrences": 1,
            "first_seen": now,
            "last_seen": now,
            "applied_count": 0,
            "archived": False,
        })
    elif iteration_count >= 8 and not success:
        lessons.append({
            "id": _fingerprint(f"inefficient_{domain}_{iteration_count}"),
            "category": "optimization",
            "title": f"{domain} requirió {iteration_count} iteraciones sin éxito",
            "description": f"Tarea de {domain} agotó iteraciones. "
                           f"Considerar: dividir en subtareas, proporcionar ejemplos, "
                           f"o escalar a Pro antes.",
            "domain": domain,
            "origin_task": requirement[:120],
            "origin_iteration": iteration_count,
            "code_snippet": "",
            "success": False,
            "occurrences": 1,
            "first_seen": now,
            "last_seen": now,
            "applied_count": 0,
            "archived": False,
        })
    
    return lessons


def _infer_domain(requirement: str, blueprint: dict) -> str:
    """Infiera el dominio/tipo de tarea del requerimiento y blueprint."""
    req_lower = requirement.lower()
    
    # Mapa de indicadores → dominio
    domain_indicators = [
        ("api", "api_rest"),
        ("rest", "api_rest"),
        ("flask", "api_flask"),
        ("database", "base_de_datos"),
        ("db", "base_de_datos"),
        ("csv", "procesamiento_datos"),
        ("json", "procesamiento_datos"),
        ("data", "procesamiento_datos"),
        ("pipeline", "pipeline_datos"),
        ("cli", "herramienta_cli"),
        ("script", "script"),
        ("mcp", "mcp_server"),
        ("server", "servidor"),
        ("web", "web"),
        ("html", "web"),
        ("frontend", "frontend"),
        ("test", "testing"),
        ("pytest", "testing"),
        ("auth", "autenticacion"),
        ("login", "autenticacion"),
        ("deploy", "despliegue"),
        ("docker", "contenedores"),
        ("config", "configuracion"),
    ]
    
    for keyword, domain in domain_indicators:
        if keyword in req_lower:
            return domain
    
    # Intentar extraer del blueprint
    bp_desc = str(blueprint.get("descripcion_general", "")).lower()
    for keyword, domain in domain_indicators:
        if keyword in bp_desc:
            return domain
    
    return "general"


def _extract_success_pattern(requirement: str, source_code: dict, audit_trail: list) -> str:
    """Extrae el patrón que llevó al éxito."""
    parts = [f"Tarea completada exitosamente: {requirement[:100]}"]
    
    # Contar iteraciones desde audit_trail
    programmer_calls = sum(1 for a in audit_trail if "Programador" in str(a.get("nodo", "")))
    parts.append(f"Requirió {programmer_calls} iteraciones de programación.")
    
    # Archivos generados
    if source_code:
        files = list(source_code.keys())
        parts.append(f"Archivos generados: {', '.join(files[:5])}")
    
    return " | ".join(parts)


def _extract_failure_pattern(requirement: str, test_report: dict, audit_trail: list, scratchpad: list) -> str:
    """Extrae el patrón de fallo para aprender de él."""
    parts = [f"Tarea fallida: {requirement[:100]}"]
    
    errors = test_report.get("errors", [])
    if errors:
        parts.append(f"Errores: {'; '.join(str(e)[:100] for e in errors[:3])}")
    
    # Técnicas no intentadas (desde fail_diagnosis)
    for entry in scratchpad:
        if "técnica" in entry.lower() or "técnica" in entry.lower():
            parts.append(entry[:150])
    
    return " | ".join(parts)


def _get_key_snippet(source_code: dict) -> str:
    """Obtiene un snippet clave del código generado."""
    if not source_code:
        return ""
    # Tomar el primer archivo, primeras 10 líneas
    first_file = list(source_code.values())[0]
    lines = first_file.split("\n")
    return "\n".join(lines[:8])


# ═══════════════════════════════════════════════════════════════
# 2. ALMACENAMIENTO DE LECCIONES
# ═══════════════════════════════════════════════════════════════

def _load_all_lessons() -> list[dict]:
    """Carga todas las lecciones desde el archivo JSON."""
    _ensure_dirs()
    if LESSONS_FILE.exists():
        try:
            with open(LESSONS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_all_lessons(lessons: list[dict]):
    """Guarda todas las lecciones en el archivo JSON."""
    _ensure_dirs()
    try:
        with open(LESSONS_FILE, "w") as f:
            json.dump(lessons, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[LessonsEngine] ⚠️ Error guardando lecciones: {e}")


def store_lesson(lesson: dict) -> bool:
    """Guarda una lección, fusionando con duplicados existentes.
    
    Si ya existe una lección con el mismo fingerprint:
    - Incrementa occurrences
    - Actualiza last_seen
    - Si es la misma categoría, actualiza description
    
    Returns:
        True si es nueva, False si fusionó con existente.
    """
    lessons = _load_all_lessons()
    now = datetime.now().isoformat()
    
    # Buscar duplicado por fingerprint
    for i, existing in enumerate(lessons):
        if existing.get("id") == lesson["id"]:
            # Fusionar: incrementar ocurrencias
            lessons[i]["occurrences"] = existing.get("occurrences", 1) + 1
            lessons[i]["last_seen"] = now
            lessons[i]["applied_count"] = existing.get("applied_count", 0)
            
            # Si tiene más descripción, actualizar
            if len(lesson.get("description", "")) > len(existing.get("description", "")):
                lessons[i]["description"] = lesson["description"]
            
            _save_all_lessons(lessons)
            print(f"[LessonsEngine] 🔄 Lección actualizada: {lesson['title'][:60]} "
                  f"(oc:{lessons[i]['occurrences']})")
            return False
    
    # Nueva lección
    lessons.append(lesson)
    _save_all_lessons(lessons)
    print(f"[LessonsEngine] ✅ Nueva lección: {lesson['category']} — {lesson['title'][:60]}")
    
    # Intentar guardar también en Supabase
    try:
        from src.supabase_utils import save_to_memory
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # Estamos en un contexto async, crear tarea
                loop.create_task(save_to_memory(
                    task_type=f"leccion_{lesson['category']}",
                    content=f"{lesson['title']}\n{lesson['description']}",
                    metadata={
                        "category": lesson["category"],
                        "domain": lesson["domain"],
                        "origin": lesson["origin_task"][:100],
                    }
                ))
        except RuntimeError:
            # No hay loop corriendo, ejecutar sincrónicamente (no recomendado)
            pass
    except ImportError:
        pass
    
    return True


# ═══════════════════════════════════════════════════════════════
# 3. CARGA DE LECCIONES (para inyección en contexto)
# ═══════════════════════════════════════════════════════════════

def load_lessons(domain: str = None, max_lessons: int = None) -> list[dict]:
    """Carga lecciones activas, opcionalmente filtradas por dominio.
    
    Args:
        domain: Si se especifica, solo lecciones de este dominio
        max_lessons: Máximo de lecciones a retornar
    
    Returns:
        Lista de lecciones ordenadas por: última vista (reciente) → frecuencia
    """
    lessons = _load_all_lessons()
    max_lessons = max_lessons or MAX_LESSONS_IN_CONTEXT
    
    # Filtrar no archivadas
    active = [l for l in lessons if not l.get("archived", False)]
    
    # Filtrar por dominio
    if domain:
        domain_lower = domain.lower()
        active = [l for l in active if domain_lower in l.get("domain", "").lower()]
    
    # Ordenar: más ocurrencias + más recientes primero
    active.sort(key=lambda l: (
        l.get("occurrences", 1),
        l.get("last_seen", ""),
    ), reverse=True)
    
    return active[:max_lessons]


def get_lessons_context(requirement: str = None) -> str:
    """Genera texto de contexto de lecciones para inyectar en prompts de agentes.
    
    Args:
        requirement: Si se especifica, filtra lecciones por dominio relevante
    
    Returns:
        Texto formateado para inyectar en el system prompt del Orquestador/Programador
    """
    domain = _infer_domain(requirement, {}) if requirement else None
    lessons = load_lessons(domain=domain)
    
    if not lessons:
        return ""
    
    lines = [
        "\n",
        "═" * 60,
        "  🧠 LECCIONES APRENDIDAS (inyectadas por Lessons Engine)",
        "═" * 60,
    ]
    
    for i, lesson in enumerate(lessons, 1):
        cat = lesson.get("category", "?")
        emoji = {"pattern": "✅", "anti-pattern": "❌", "pitfall": "⚠️", "optimization": "⚡"}.get(cat, "📌")
        title = lesson.get("title", "Sin título")
        desc = lesson.get("description", "")[:200]
        occ = lesson.get("occurrences", 1)
        
        lines.append(f"\n{emoji} [{cat.upper()}] #{i} (x{occ})")
        lines.append(f"   {title}")
        if desc:
            lines.append(f"   → {desc}")
    
    lines.append("═" * 60)
    lines.append("")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 4. DETECCIÓN DE PATRONES (generación de reglas)
# ═══════════════════════════════════════════════════════════════

def _load_rules() -> list[dict]:
    """Carga las reglas generadas desde patrones."""
    _ensure_dirs()
    if RULES_FILE.exists():
        try:
            with open(RULES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_rules(rules: list[dict]):
    """Guarda las reglas generadas."""
    _ensure_dirs()
    try:
        with open(RULES_FILE, "w") as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[LessonsEngine] ⚠️ Error guardando reglas: {e}")


def detect_patterns() -> list[dict]:
    """Detecta patrones repetidos en las lecciones.
    
    Si una lección (mismo fingerprint) aparece PATTERN_MIN_OCCURRENCES+ veces,
    genera una regla de negocio automática.
    
    Returns:
        Lista de nuevas reglas generadas
    """
    lessons = _load_all_lessons()
    existing_rules = _load_rules()
    existing_rule_texts = {r.get("rule_text", "") for r in existing_rules}
    new_rules = []
    
    for lesson in lessons:
        occ = lesson.get("occurrences", 1)
        if occ >= PATTERN_MIN_OCCURRENCES and not lesson.get("archived", False):
            rule_text = _lesson_to_rule(lesson)
            if rule_text and rule_text not in existing_rule_texts:
                new_rule = {
                    "id": f"rule_{lesson['id']}",
                    "rule_text": rule_text,
                    "category": lesson["category"],
                    "domain": lesson["domain"],
                    "source_lesson": lesson["title"],
                    "occurrences": occ,
                    "created": datetime.now().isoformat(),
                    "applied_count": 0,
                }
                new_rules.append(new_rule)
                existing_rules.append(new_rule)
                existing_rule_texts.add(rule_text)
                print(f"[LessonsEngine] 🆕 Regla generada: {rule_text[:80]}")
    
    if new_rules:
        _save_rules(existing_rules)
    
    return new_rules


def _lesson_to_rule(lesson: dict) -> str:
    """Convierte una lección en una regla de negocio actionable."""
    category = lesson.get("category", "")
    title = lesson.get("title", "")
    description = lesson.get("description", "")[:150]
    domain = lesson.get("domain", "general")
    
    if category == "pattern":
        return f"[PATRÓN APRENDIDO: {domain}] {title}. Al enfrentar tareas similares de {domain}, considera replicar este approach: {description}"
    
    elif category == "anti-pattern":
        return f"[ANTI-PATRÓN: {domain}] {title}. Evita este approach en tareas de {domain}: {description}"
    
    elif category == "pitfall":
        return f"[ERROR CONOCIDO: {domain}] {title}. Si encuentras este error: {description}"
    
    elif category == "optimization":
        return f"[OPTIMIZACIÓN: {domain}] {title}. Para mejorar eficiencia en {domain}: {description}"
    
    return f"[LECCIÓN: {domain}] {title}. {description}"


def generate_business_rules(requirement: str = None) -> list[str]:
    """Genera business_rules dinámicas para inyectar en el pipeline.
    
    Returns:
        Lista de strings de reglas de negocio para inyectar
    """
    rules = _load_rules()
    domain = _infer_domain(requirement, {}) if requirement else None
    
    result = []
    for rule in rules:
        # Si hay dominio, filtrar por relevancia
        if domain and rule.get("domain", "") != domain:
            # Solo incluir reglas del dominio o reglas generales
            if rule.get("domain", "") not in ("general", domain):
                continue
        
        rule_text = rule.get("rule_text", "")
        if rule_text:
            result.append(rule_text)
            # Incrementar applied_count
            rule["applied_count"] = rule.get("applied_count", 0) + 1
    
    if rules and result:
        _save_rules(rules)
        print(f"[LessonsEngine] 📋 {len(result)} reglas inyectadas para dominio '{domain or 'todos'}'")
    
    return result


# ═══════════════════════════════════════════════════════════════
# 5. SEÑAL DE REFUERZO COMPUESTA
# ═══════════════════════════════════════════════════════════════

def compute_reinforcement_signal(state: dict) -> dict:
    """Calcula una señal de refuerzo compuesta (0.0 a 1.0).
    
    Componentes:
    - Éxito (40%): PASS = 1.0, FAIL = 0.0
    - Eficiencia (30%): iteraciones usadas vs máximas
    - Calidad (30%): cantidad de errores, complejidad del código
    
    Returns:
        {
            "success": bool,
            "quality": float (0.0-1.0),
            "iterations": int,
            "errors": int,
            "complexity": str,
            "signal": float (0.0-1.0),
            "components": dict
        }
    """
    test_report = state.get("test_report", {})
    source_code = state.get("source_code", {})
    iteration_count = state.get("iteration_count", 0)
    complexity = state.get("router_stats", {}).get("complexity", "medium")
    
    # 1. Componente de éxito
    is_success = test_report.get("status") == "PASS"
    success_score = 1.0 if is_success else 0.0
    
    # 2. Componente de eficiencia
    max_iter = {"low": 5, "medium": 10, "high": 20}.get(complexity, 10)
    efficiency_score = max(0.0, 1.0 - (iteration_count / max_iter))
    
    # 3. Componente de calidad
    errors = len(test_report.get("errors", []))
    quality_score = max(0.0, 1.0 - (errors * 0.2))
    
    # Bonus: cantidad de archivos generados (si es exitoso, más archivos = mejor)
    if is_success and source_code:
        file_bonus = min(0.1, len(source_code) * 0.02)
        quality_score = min(1.0, quality_score + file_bonus)
    
    # Señal compuesta
    signal = (
        REINFORCEMENT_WEIGHTS["success"] * success_score +
        REINFORCEMENT_WEIGHTS["efficiency"] * efficiency_score +
        REINFORCEMENT_WEIGHTS["quality"] * quality_score
    )
    
    return {
        "success": is_success,
        "quality": round(quality_score, 4),
        "iterations": iteration_count,
        "errors": errors,
        "complexity": complexity,
        "signal": round(signal, 4),
        "components": {
            "success_score": round(success_score, 4),
            "efficiency_score": round(efficiency_score, 4),
            "quality_score": round(quality_score, 4),
        },
    }


# ═══════════════════════════════════════════════════════════════
# 6. SCOREBOARD DE RENDIMIENTO
# ═══════════════════════════════════════════════════════════════

def _load_scoreboard() -> dict:
    """Carga el scoreboard de rendimiento por dominio."""
    _ensure_dirs()
    if SCOREBOARD_FILE.exists():
        try:
            with open(SCOREBOARD_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_scoreboard(scoreboard: dict):
    """Guarda el scoreboard."""
    _ensure_dirs()
    try:
        with open(SCOREBOARD_FILE, "w") as f:
            json.dump(scoreboard, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[LessonsEngine] ⚠️ Error guardando scoreboard: {e}")


def update_scoreboard(state: dict):
    """Actualiza el scoreboard de rendimiento con datos de la ejecución.
    
    Por dominio/tipo de tarea, registra:
    - Total de ejecuciones
    - Tasa de éxito
    - Promedio de iteraciones
    - Última ejecución
    """
    scoreboard = _load_scoreboard()
    test_report = state.get("test_report", {})
    source_code = state.get("source_code", {})
    iteration_count = state.get("iteration_count", 0)
    success = test_report.get("status") == "PASS"
    requirement = state.get("user_requirement", "")
    
    domain = _infer_domain(requirement, state.get("architecture_blueprint", {}))
    
    if domain not in scoreboard:
        scoreboard[domain] = {
            "total_runs": 0,
            "successful_runs": 0,
            "total_iterations": 0,
            "last_run": None,
            "avg_iterations": 0,
            "success_rate": 0.0,
        }
    
    stats = scoreboard[domain]
    stats["total_runs"] += 1
    if success:
        stats["successful_runs"] += 1
    stats["total_iterations"] += iteration_count
    stats["last_run"] = datetime.now().isoformat()
    stats["avg_iterations"] = round(stats["total_iterations"] / stats["total_runs"], 2)
    stats["success_rate"] = round(stats["successful_runs"] / stats["total_runs"], 3)
    
    _save_scoreboard(scoreboard)


def get_scoreboard() -> dict:
    """Obtiene el scoreboard de rendimiento."""
    return _load_scoreboard()


def get_scoreboard_text() -> str:
    """Genera texto legible del scoreboard para debugging/reporte."""
    scoreboard = _load_scoreboard()
    if not scoreboard:
        return "[Scoreboard vacío — sin datos de rendimiento aún]"
    
    lines = [
        "\n" + "=" * 60,
        "  📊 SCOREBOARD DE RENDIMIENTO POR DOMINIO",
        "=" * 60,
    ]
    
    # Ordenar por total de runs descendente
    sorted_domains = sorted(scoreboard.items(), key=lambda x: -x[1].get("total_runs", 0))
    
    for domain, stats in sorted_domains:
        rate = stats.get("success_rate", 0) * 100
        bar_len = 20
        filled = int(rate / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        
        lines.append(f"\n  {domain:25s} {bar} {rate:5.1f}%")
        lines.append(f"  {'':25s} 🏃 {stats.get('total_runs', 0)} runs | "
                     f"✅ {stats.get('successful_runs', 0)} éxito | "
                     f"📐 {stats.get('avg_iterations', 0):.1f} iter promedio")
    
    lines.append("=" * 60)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 7. ARCHIVADO DE LECCIONES ANTIGUAS
# ═══════════════════════════════════════════════════════════════

def archive_old_lessons():
    """Archiva lecciones con más de LESSON_ACTIVE_DAYS días sin uso.
    
    Las lecciones archivadas se mueven a archive/ y se marcan como archived=True.
    """
    lessons = _load_all_lessons()
    now = datetime.now()
    cutoff = now - timedelta(days=LESSON_ACTIVE_DAYS)
    archived_count = 0
    
    for lesson in lessons:
        if lesson.get("archived", False):
            continue
        
        last_seen_str = lesson.get("last_seen", lesson.get("first_seen", ""))
        try:
            last_seen = datetime.fromisoformat(last_seen_str)
            if last_seen < cutoff:
                lesson["archived"] = True
                lesson["archived_date"] = now.isoformat()
                archived_count += 1
        except (ValueError, TypeError):
            pass
    
    if archived_count:
        _save_all_lessons(lessons)
        
        # También guardar copia en archive/
        try:
            archive_file = ARCHIVE_DIR / f"lessons_archive_{now.strftime('%Y%m')}.json"
            archived_lessons = [l for l in lessons if l.get("archived", False)]
            with open(archive_file, "w") as f:
                json.dump(archived_lessons, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
        
        print(f"[LessonsEngine] 🗂️ {archived_count} lecciones archivadas (> {LESSON_ACTIVE_DAYS} días)")


# ═══════════════════════════════════════════════════════════════
# 8. MANTENIMIENTO: REFINAR LECCIONES DUPLICADAS O SOLAPADAS
# ═══════════════════════════════════════════════════════════════

def deduplicate_lessons():
    """Fusiona lecciones muy similares (mismo dominio + mismo error).
    
    1. Detecta lecciones con título/descripción muy similar
    2. Fusiona occurrences y mantiene la más completa
    3. Reduce ruido en el contexto
    """
    lessons = _load_all_lessons()
    if len(lessons) < 2:
        return 0
    
    merged = {}
    for lesson in lessons:
        key = (lesson.get("domain", ""), lesson.get("category", ""))
        # Usar fingerprint del título normalizado
        title_fp = _fingerprint(lesson.get("title", ""))
        merge_key = (key, title_fp)
        
        if merge_key in merged:
            existing = merged[merge_key]
            existing["occurrences"] = existing.get("occurrences", 1) + lesson.get("occurrences", 1)
            existing["applied_count"] = existing.get("applied_count", 0) + lesson.get("applied_count", 0)
            # Mantener la descripción más larga
            if len(lesson.get("description", "")) > len(existing.get("description", "")):
                existing["description"] = lesson["description"]
            # Mantener el last_seen más reciente
            if lesson.get("last_seen", "") > existing.get("last_seen", ""):
                existing["last_seen"] = lesson["last_seen"]
        else:
            merged[merge_key] = dict(lesson)
    
    merged_list = list(merged.values())
    if len(merged_list) < len(lessons):
        _save_all_lessons(merged_list)
        dedup_count = len(lessons) - len(merged_list)
        print(f"[LessonsEngine] 🧹 {dedup_count} lecciones duplicadas fusionadas")
        return dedup_count
    
    return 0


# ═══════════════════════════════════════════════════════════════
# 9. API PRINCIPAL PARA EL NODO DE REFLEXIÓN
# ═══════════════════════════════════════════════════════════════

def process_execution(state: dict) -> dict:
    """Procesa una ejecución completa: extrae, almacena, detecta y actualiza.
    
    Este es el método principal que llama el Reflection Node.
    
    Args:
        state: TeamState completo de la ejecución
    
    Returns:
        dict con:
        - lessons_extracted: int
        - rules_generated: int
        - reinforcement_signal: dict
        - lessons_context: str (para inyectar en próximas ejecuciones)
    """
    requirement = state.get("user_requirement", "")
    source_code = state.get("source_code", {})
    test_report = state.get("test_report", {})
    blueprint = state.get("architecture_blueprint", {})
    audit_trail = state.get("audit_trail", [])
    scratchpad = state.get("scratchpad", [])
    iteration_count = state.get("iteration_count", 0)
    success = test_report.get("status") == "PASS"
    
    # 1. Extraer lecciones
    lessons = extract_lessons(
        requirement=requirement,
        source_code=source_code,
        test_report=test_report,
        blueprint=blueprint,
        audit_trail=audit_trail,
        iteration_count=iteration_count,
        success=success,
        scratchpad=scratchpad,
    )
    
    # 2. Almacenar lecciones
    new_lessons = 0
    for lesson in lessons:
        if store_lesson(lesson):
            new_lessons += 1
    
    # 3. Detectar patrones y generar reglas
    new_rules = detect_patterns()
    
    # 4. Señal de refuerzo
    signal = compute_reinforcement_signal(state)
    
    # 5. Actualizar scoreboard
    update_scoreboard(state)
    
    # 6. Mantenimiento periódico (cada 50 lecciones aprox)
    all_lessons = _load_all_lessons()
    if len(all_lessons) % 50 < len(lessons):
        deduplicate_lessons()
        archive_old_lessons()
    
    # 7. Generar contexto para inyección
    context = get_lessons_context(requirement)
    
    # 8. Generar business_rules para inyectar en próximas ejecuciones
    rules = generate_business_rules(requirement)
    
    print(f"[LessonsEngine] 📊 Señal de refuerzo: {signal['signal']:.3f} "
          f"(éxito={signal['components']['success_score']:.2f}, "
          f"eficiencia={signal['components']['efficiency_score']:.2f}, "
          f"calidad={signal['components']['quality_score']:.2f})")
    
    return {
        "lessons_extracted": len(lessons),
        "new_lessons": new_lessons,
        "rules_generated": len(new_rules),
        "total_rules_active": len(_load_rules()),
        "reinforcement_signal": signal,
        "lessons_context": context,
        "business_rules_from_lessons": rules,
    }


# ═══════════════════════════════════════════════════════════════
# 10. UTILIDADES DE DIAGNÓSTICO
# ═══════════════════════════════════════════════════════════════

def show_status() -> str:
    """Muestra el estado completo del sistema de lecciones."""
    lessons = _load_all_lessons()
    rules = _load_rules()
    scoreboard = _load_scoreboard()
    
    active = [l for l in lessons if not l.get("archived", False)]
    archived = [l for l in lessons if l.get("archived", False)]
    
    by_category = defaultdict(int)
    for l in active:
        by_category[l.get("category", "unknown")] += 1
    
    lines = [
        "=" * 60,
        "  🧠 LESSONS ENGINE — Estado del Sistema",
        "=" * 60,
        f"  Lecciones activas: {len(active)}",
        f"  Lecciones archivadas: {len(archived)}",
        f"  Reglas generadas: {len(rules)}",
        f"  Dominios en scoreboard: {len(scoreboard)}",
        "",
        "  Por categoría (activas):",
    ]
    
    for cat in LESSON_CATEGORIES:
        count = by_category.get(cat, 0)
        emoji = {"pattern": "✅", "anti-pattern": "❌", "pitfall": "⚠️", "optimization": "⚡"}.get(cat, "📌")
        lines.append(f"    {emoji} {cat}: {count}")
    
    lines.append("")
    lines.append(get_scoreboard_text())
    
    return "\n".join(lines)


def reset_lessons():
    """Resetea TODAS las lecciones (peligroso)."""
    import shutil
    _ensure_dirs()
    if LESSONS_FILE.exists():
        LESSONS_FILE.unlink()
    if RULES_FILE.exists():
        RULES_FILE.unlink()
    if SCOREBOARD_FILE.exists():
        SCOREBOARD_FILE.unlink()
    print("[LessonsEngine] 🔄 Todas las lecciones han sido reseteadas")
