"""🧬 Prompt Evolution v3.0 — Evolución Automática + Self-Play.

Mecanismo de mejora continua del enjambre:
1. Tras cada ejecución, se identifica qué nodo falló más
2. Se genera una mejora específica para su prompt (rule/advertencia)
3. La mejora se inyecta en futuras ejecuciones
4. Self-Play: pares (problema → solución) para entrenamiento futuro

MEJORA v3.0:
  - Evolución por NODO específico (no global a todos)
  - Las reglas se inyectan como business_rules en el nodo correspondiente
  - Self-play: dataset de problemas resueltos para fine-tuning
  - Persistencia en ~/.agents/evolved_prompts/
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── Constantes ──
EVOLVED_DIR = Path.home() / ".agents" / "evolved_prompts"
EVOLVED_FILE = EVOLVED_DIR / "evolved_prompts.json"
EVOLUTION_LOG = EVOLVED_DIR / "evolution_log.json"
SELFPLAY_FILE = EVOLVED_DIR / "selfplay_data.jsonl"
TRIGGER_EVERY_N_EXECUTIONS = 3  # Evolucionar cada N ejecuciones
MIN_SIGNAL_THRESHOLD = 0.3

# Prompts base de cada agente (referencia)
AGENT_PROMPTS = {
    "orchestrator": "Prompt del Orquestador",
    "architect": "Prompt del Arquitecto",
    "programmer": "Prompt del Programador",
    "tester": "Prompt del Tester",
}


def _ensure_dirs():
    EVOLVED_DIR.mkdir(parents=True, exist_ok=True)


def _load_evolved() -> dict:
    _ensure_dirs()
    if EVOLVED_FILE.exists():
        try:
            with open(EVOLVED_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "version": 2,
        "last_evolved": None,
        "total_evolutions": 0,
        "total_executions": 0,
        "agents": {},
    }


def _save_evolved(state: dict):
    _ensure_dirs()
    try:
        with open(EVOLVED_FILE, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[PromptEvolution] ⚠️ Error guardando: {e}")


def _load_log() -> list:
    _ensure_dirs()
    if EVOLUTION_LOG.exists():
        try:
            with open(EVOLUTION_LOG) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_log(log: list):
    _ensure_dirs()
    try:
        with open(EVOLUTION_LOG, "w") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[PromptEvolution] ⚠️ Error guardando log: {e}")


def _append_selfplay(entry: dict):
    """Agrega un par (problema → solución) al dataset self-play."""
    _ensure_dirs()
    try:
        with open(SELFPLAY_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[SelfPlay] ⚠️ Error guardando: {e}")


class PromptEvolution:
    """Sistema de evolución de prompts + self-play."""
    
    @classmethod
    def _diagnose_weak_node(cls, test_report: dict, scratchpad: list,
                             iterations: int, success: bool) -> str:
        """Diagnostica qué nodo del pipeline necesita mejora."""
        if success:
            return "general"  # Reforzar buenas prácticas
        
        errors = test_report.get("errors", []) if isinstance(test_report, dict) else []
        
        # Analizar tipo de error para diagnosticar qué nodo falló
        error_text = " ".join([
            e.get("error", "") if isinstance(e, dict) else str(e)
            for e in errors
        ]).lower()
        
        if any(w in error_text for w in ["import", "module", "dependencia", "syntax"]):
            return "programmer"  # Programador no manejó imports/sintaxis
        elif any(w in error_text for w in ["blueprint", "arquitectura", "estructura", "archivo"]):
            return "architect"  # Arquitecto no definió bien la estructura
        elif any(w in error_text for w in ["regla", "business", "requisito", "alcance"]):
            return "orchestrator"  # Orquestador omitió reglas
        elif iterations >= 3:
            return "tester"  # Tester no da suficiente diagnóstico
        else:
            return "programmer"  # Default: el Programador
    
    @classmethod
    def _generate_improvement(cls, nodo: str, success: bool, 
                               error_categories: dict = None) -> str:
        """Genera una mejora específica para el nodo diagnosticado."""
        
        if success:
            return "✅ Continuar con el enfoque actual. Reforzar: código tipado, modular, con tests."
        
        improvements = {
            "orchestrator": (
                "[MEJORA] Al analizar un requerimiento, extrae explícitamente: "
                "1) todas las reglas de negocio como frases completas, "
                "2) el alcance EXPLÍCITO (qué NO incluye), "
                "3) dependencias externas necesarias."
            ),
            "architect": (
                "[MEJORA] Al diseñar arquitectura, incluye SIEMPRE: "
                "1) la estructura COMPLETA de archivos con dependencias, "
                "2) el flujo de datos entre módulos, "
                "3) los casos borde a considerar desde el diseño."
            ),
            "programmer": (
                "[MEJORA] Antes de escribir código, verifica: "
                "1) todos los imports necesarios, "
                "2) type hints en todas las funciones, "
                "3) manejo de errores para casos borde, "
                "4) que el código es ejecutable sin sintaxis errors."
            ),
            "tester": (
                "[MEJORA] Al analizar código, clasifica cada error con: "
                "categoría (SINTAXIS|LOGICA|ARQUITECTURA|DEPENDENCIA), "
                "causa raíz, y fix concreto. No solo reports 'falló'."
            ),
            "general": (
                "[MEJORA GENERAL] El enjambre debe priorizar: "
                "código funcional sobre perfecto, tests sobre documentación, "
                "modularidad sobre monolithic."
            ),
        }
        
        return improvements.get(nodo, improvements["general"])
    
    @classmethod
    def evolve(cls, success: bool, iterations: int, signal: float,
               test_report: dict, scratchpad: list) -> dict:
        """Evalúa y aplica evolución de prompts post-ejecución.
        
        Args:
            success: Si la ejecución fue exitosa
            iterations: Número de iteraciones usadas
            signal: Señal de refuerzo compuesta
            test_report: Reporte del tester
            scratchpad: Notas de la ejecución
        
        Returns:
            Dict con resultado de la evolución
        """
        state = _load_evolved()
        log = _load_log()
        
        # Incrementar contador de ejecuciones
        state["total_executions"] = state.get("total_executions", 0) + 1
        total_execs = state["total_executions"]
        
        # Solo evolucionar cada N ejecuciones o cuando hay señal fuerte
        if total_execs % TRIGGER_EVERY_N_EXECUTIONS != 0 and signal > MIN_SIGNAL_THRESHOLD:
            _save_evolved(state)
            return {
                "cambios_aplicados": 0,
                "razon": f"Próxima evolución en iter {total_execs + (TRIGGER_EVERY_N_EXECUTIONS - total_execs % TRIGGER_EVERY_N_EXECUTIONS)}",
                "detalles": [],
            }
        
        # Diagnosticar nodo débil
        weak_node = cls._diagnose_weak_node(test_report, scratchpad, iterations, success)
        
        # Generar mejora específica
        error_categories = {}
        if isinstance(test_report, dict):
            for e in test_report.get("errors", []):
                if isinstance(e, dict):
                    cat = e.get("categoria", "[?]")
                    error_categories[cat] = error_categories.get(cat, 0) + 1
        
        improvement = cls._generate_improvement(weak_node, success, error_categories)
        
        # Aplicar mejora al nodo diagnosticado
        now = datetime.now().isoformat()
        changes = []
        
        agent_state = state.setdefault("agents", {}).setdefault(weak_node, {
            "version": 0,
            "improvements": [],
            "last_updated": None,
        })
        
        agent_state["version"] += 1
        agent_state["last_updated"] = now
        agent_state["improvements"].append({
            "text": improvement,
            "added_at": now,
            "source_signal": signal,
            "source_success": success,
            "source_iterations": iterations,
        })
        
        changes.append(f"{weak_node}: v{agent_state['version']} (+1 mejora específica)")
        
        # Actualizar estado global
        state["last_evolved"] = now
        state["total_evolutions"] = state.get("total_evolutions", 0) + 1
        _save_evolved(state)
        
        # Registrar en log
        log_entry = {
            "timestamp": now,
            "evolution_number": state["total_evolutions"],
            "signal": signal,
            "success": success,
            "weak_node": weak_node,
            "improvement": improvement,
        }
        log.append(log_entry)
        _save_log(log)
        
        print(f"[PromptEvolution v3] 🧬 Evolución #{state['total_evolutions']}: {weak_node} mejorado "
              f"(signal: {signal:.2f}, {'✅' if success else '❌'})")
        
        return {
            "cambios_aplicados": 1,
            "razon": f"Diagnóstico: {weak_node} necesitaba mejora",
            "detalles": changes,
            "improvement": improvement,
            "weak_node": weak_node,
        }
    
    @classmethod
    def save_selfplay_example(cls, requirement: str, blueprint: dict,
                                source_code: dict, test_report: dict,
                                success: bool, iterations: int):
        """Guarda un par (problema → solución) para self-play.
        
        Cada entrada contiene:
        - El problema original (requirement)
        - La solución (código final, blueprint)
        - El resultado (PASS/FAIL, iteraciones)
        - Metadata (dominio, complejidad, modelos usados)
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "requirement": requirement[:500],
            "blueprint_summary": {
                "archivos": list(blueprint.get("archivos", {}).keys()) if blueprint else [],
                "descripcion": (blueprint.get("descripcion_general", "")[:200] if blueprint else ""),
            },
            "code_summary": {
                "archivos": list(source_code.keys()) if source_code else [],
                "total_lines": sum(len(c.split("\n")) for c in (source_code or {}).values()),
            },
            "result": "PASS" if success else "FAIL",
            "iterations": iterations,
            "test_summary": {
                "status": test_report.get("status", "UNKNOWN") if isinstance(test_report, dict) else "UNKNOWN",
                "num_errors": len(test_report.get("errors", [])) if isinstance(test_report, dict) else 0,
            },
        }
        _append_selfplay(entry)
        return entry
    
    @classmethod
    def get_improvements_for_node(cls, agent_name: str) -> list[str]:
        """Obtiene las mejoras acumuladas para un nodo específico."""
        state = _load_evolved()
        agent = state.get("agents", {}).get(agent_name, {})
        return [imp["text"] for imp in agent.get("improvements", [])]
    
    @classmethod
    def get_evolution_summary(cls) -> str:
        """Genera un resumen legible del estado de evolución."""
        state = _load_evolved()
        log = _load_log()
        agents = state.get("agents", {})
        
        if not agents:
            return "[PromptEvolution v3] Sin evoluciones aún"
        
        lines = [
            "\n" + "=" * 60,
            "  🧬 PROMPT EVOLUTION v3.0 — Estado",
            "=" * 60,
            f"  Versión: {state.get('version', 2)}",
            f"  Ejecuciones totales: {state.get('total_executions', 0)}",
            f"  Evoluciones aplicadas: {state.get('total_evolutions', 0)}",
            f"  Última: {state.get('last_evolved', 'Nunca')}",
            "",
            "  Agentes con mejoras:",
        ]
        
        for agent_name, agent_state in sorted(agents.items()):
            improvements = agent_state.get("improvements", [])
            lines.append(f"    • {agent_name}: v{agent_state.get('version', 0)} "
                        f"({len(improvements)} mejoras)")
            for imp in improvements[-2:]:
                text = imp.get("text", "")[:80]
                lines.append(f"      → {text}...")
        
        # Self-play stats
        if SELFPLAY_FILE.exists():
            try:
                with open(SELFPLAY_FILE) as f:
                    sp_count = sum(1 for _ in f)
                lines.append(f"\n  Self-play dataset: {sp_count} ejemplos")
            except OSError:
                pass
        
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)
    
    @classmethod
    def inject_improvements_into_prompt(cls, agent_name: str, base_prompt: str) -> str:
        """Inyecta mejoras evolutivas en el prompt base de un agente.
        
        Las mejoras se agregan como reglas adicionales al final del prompt.
        """
        improvements = cls.get_improvements_for_node(agent_name)
        if not improvements:
            return base_prompt
        
        # Solo las últimas 3 mejoras para no sobrecargar
        recent = improvements[-3:]
        rules_section = "\n\n📚 LECCIONES APRENDIDAS (inyectadas por PromptEvolution):\n"
        for imp in recent:
            rules_section += f"  • {imp}\n"
        
        return base_prompt + rules_section
    
    @classmethod
    def reset_evolution(cls):
        """Resetea toda la evolución de prompts."""
        _ensure_dirs()
        default_state = {
            "version": 2,
            "last_evolved": None,
            "total_evolutions": 0,
            "total_executions": 0,
            "agents": {},
        }
        _save_evolved(default_state)
        _save_log([])
        print("[PromptEvolution v3] 🔄 Evolución reseteada a estado inicial")
