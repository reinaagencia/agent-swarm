"""🎯 Self-Play Data Pipeline — Generación de Datos de Entrenamiento.

ARQUITECTURA:
  Cada ejecución exitosa produce un par (problema → solución).
  Cada ejecución fallida produce un par (problema → error).
  Los pares se acumulan como dataset para fine-tuning futuro.

FLUJO:
  ```
  Ejecución completa
         ↓
  ✅ Éxito → Par (requirement → código final)
  ❌ Fallo → Par (requirement → errores + diagnóstico)
         ↓
  Almacenar en ~/.agents/training_data/
         ↓
  Indexar por dominio y complejidad
         ↓
  Preparar para fine-tuning (formato JSONL)
  ```
"""

import json
from pathlib import Path
from datetime import datetime

# ── Constantes ──
TRAINING_DIR = Path.home() / ".agents" / "training_data"
SUCCESSES_FILE = TRAINING_DIR / "successes.jsonl"
FAILURES_FILE = TRAINING_DIR / "failures.jsonl"
METADATA_FILE = TRAINING_DIR / "metadata.json"


def _ensure_dirs():
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)


def _infer_domain(requirement: str) -> str:
    req_lower = requirement.lower()
    domains = {
        "api": "api_rest", "rest": "api_rest", "flask": "api_flask",
        "database": "base_de_datos", "db": "base_de_datos",
        "csv": "procesamiento_datos", "json": "procesamiento_datos",
        "pipeline": "pipeline_datos", "cli": "herramienta_cli",
        "script": "script", "mcp": "mcp_server", "web": "web",
        "test": "testing", "pytest": "testing",
    }
    for keyword, domain in domains.items():
        if keyword in req_lower:
            return domain
    return "general"


# ═══════════════════════════════════════════════════════════════
# 1. REGISTRAR PAR DE ENTRENAMIENTO
# ═══════════════════════════════════════════════════════════════

def record_training_pair(state: dict, success: bool):
    """Registra un par (problema → solución/error) como dato de entrenamiento.
    
    Args:
        state: TeamState de la ejecución
        success: Si fue exitosa
    """
    _ensure_dirs()
    
    requirement = state.get("user_requirement", "")
    source_code = state.get("source_code", {})
    test_report = state.get("test_report", {})
    iteration_count = state.get("iteration_count", 0)
    blueprint = state.get("architecture_blueprint", {})
    
    domain = _infer_domain(requirement)
    timestamp = datetime.now().isoformat()
    
    if success:
        # Si el código tiene un solo archivo principal, usarlo
        main_code = ""
        for filename in sorted(source_code.keys()):
            if filename.endswith(".py") or filename.endswith(".js"):
                main_code = source_code[filename]
                break
        if not main_code and source_code:
            main_code = list(source_code.values())[0]
        
        pair = {
            "instruction": f"Implementa: {requirement[:500]}",
            "response": main_code[:5000] if main_code else "",
            "domain": domain,
            "complexity": state.get("router_stats", {}).get("complexity", "medium"),
            "iterations": iteration_count,
            "files": list(source_code.keys()),
            "technologies": blueprint.get("tecnologias_sugeridas", []),
            "timestamp": timestamp,
        }
        
        with open(SUCCESSES_FILE, "a") as f:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        
        print(f"[SelfPlay] ✅ Par de éxito registrado: {domain} - {requirement[:60]}...")
    
    else:
        errors = test_report.get("errors", [])
        error_text = "\n".join(str(e)[:300] for e in errors[:3])
        
        pair = {
            "instruction": f"Implementa: {requirement[:500]}",
            "error": error_text,
            "domain": domain,
            "complexity": state.get("router_stats", {}).get("complexity", "medium"),
            "iterations": iteration_count,
            "diagnosis": state.get("scratchpad", [])[-3:],
            "timestamp": timestamp,
        }
        
        with open(FAILURES_FILE, "a") as f:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        
        print(f"[SelfPlay] ❌ Par de fallo registrado: {domain} - {requirement[:60]}...")


# ═══════════════════════════════════════════════════════════════
# 2. ESTADÍSTICAS DEL DATASET
# ═══════════════════════════════════════════════════════════════

def get_stats() -> dict:
    """Obtiene estadísticas del dataset de entrenamiento."""
    _ensure_dirs()
    
    successes = 0
    if SUCCESSES_FILE.exists():
        with open(SUCCESSES_FILE) as f:
            successes = sum(1 for _ in f)
    
    failures = 0
    if FAILURES_FILE.exists():
        with open(FAILURES_FILE) as f:
            failures = sum(1 for _ in f)
    
    # Por dominio
    domains = {}
    for filepath in [SUCCESSES_FILE, FAILURES_FILE]:
        if filepath.exists():
            with open(filepath) as f:
                for line in f:
                    try:
                        pair = json.loads(line)
                        d = pair.get("domain", "unknown")
                        if d not in domains:
                            domains[d] = {"successes": 0, "failures": 0}
                        if filepath == SUCCESSES_FILE:
                            domains[d]["successes"] += 1
                        else:
                            domains[d]["failures"] += 1
                    except json.JSONDecodeError:
                        pass
    
    return {
        "total_pairs": successes + failures,
        "successes": successes,
        "failures": failures,
        "domains": domains,
    }


def get_stats_text() -> str:
    """Genera texto legible de estadísticas."""
    stats = get_stats()
    
    lines = [
        "\n" + "=" * 60,
        "  🎯 SELF-PLAY DATA PIPELINE — Estadísticas",
        "=" * 60,
        f"  Total pares: {stats['total_pairs']}",
        f"  ✅ Éxitos: {stats['successes']}",
        f"  ❌ Fallos: {stats['failures']}",
        "",
        "  Por dominio:",
    ]
    
    for domain, counts in sorted(stats.get("domains", {}).items()):
        total = counts["successes"] + counts["failures"]
        rate = (counts["successes"] / total * 100) if total else 0
        lines.append(f"    • {domain}: {total} pares ({rate:.0f}% éxito)")
    
    lines.append("=" * 60)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 3. EXPORTAR DATASET
# ═══════════════════════════════════════════════════════════════

def export_for_finetuning(output_path: Path = None) -> Path:
    """Exporta el dataset en formato JSONL para fine-tuning.
    
    Formato:
      {"messages": [{"role": "system", "content": "..."}, 
                    {"role": "user", "content": "..."},
                    {"role": "assistant", "content": "..."}]}
    
    Args:
        output_path: Ruta de salida (default: training_data/finetuning.jsonl)
    
    Returns:
        Path al archivo generado
    """
    _ensure_dirs()
    output_path = output_path or TRAINING_DIR / "finetuning.jsonl"
    
    count = 0
    with open(output_path, "w") as out:
        # Éxitos
        if SUCCESSES_FILE.exists():
            with open(SUCCESSES_FILE) as f:
                for line in f:
                    try:
                        pair = json.loads(line)
                        entry = {
                            "messages": [
                                {"role": "system", "content": "Eres un programador experto. Implementa el código solicitado."},
                                {"role": "user", "content": pair.get("instruction", "")},
                                {"role": "assistant", "content": pair.get("response", "")},
                            ]
                        }
                        out.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        count += 1
                    except (json.JSONDecodeError, KeyError):
                        pass
        
        # Fallos (como ejemplos negativos)
        if FAILURES_FILE.exists():
            with open(FAILURES_FILE) as f:
                for line in f:
                    try:
                        pair = json.loads(line)
                        entry = {
                            "messages": [
                                {"role": "system", "content": "Eres un programador experto."},
                                {"role": "user", "content": pair.get("instruction", "")},
                                {"role": "assistant", "content": f"ERROR: {pair.get('error', '')}"},
                            ]
                        }
                        out.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        count += 1
                    except (json.JSONDecodeError, KeyError):
                        pass
    
    print(f"[SelfPlay] 📦 Dataset exportado: {output_path} ({count} pares)")
    return output_path
