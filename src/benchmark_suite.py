"""📊 Benchmark Suite — Evaluación Automática y Tracking Temporal.

ARQUITECTURA:
  Cada ejecución del enjambre produce un reporte de benchmark.
  Los reportes se acumulan para análisis de tendencias temporales.

MÉTRICAS POR EJECUCIÓN:
  - success: PASS/FAIL
  - iterations: número de iteraciones
  - errors: cantidad de errores
  - tokens_used: estimación de tokens
  - time_elapsed: tiempo total
  - model_used: flash/pro/mixto
  - files_generated: cantidad de archivos
  - complexity: low/medium/high
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# ── Constantes ──
BENCHMARK_DIR = Path.home() / ".agents" / "benchmarks"
BENCHMARK_FILE = BENCHMARK_DIR / "benchmark_history.json"
SUMMARY_FILE = BENCHMARK_DIR / "benchmark_summary.json"
MAX_HISTORY = 500  # Máximo de ejecuciones en historial


def _ensure_dirs():
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)


def _load_history() -> list[dict]:
    _ensure_dirs()
    if BENCHMARK_FILE.exists():
        try:
            with open(BENCHMARK_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_history(history: list[dict]):
    _ensure_dirs()
    history = history[-MAX_HISTORY:]
    try:
        with open(BENCHMARK_FILE, "w") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[Benchmark] ⚠️ Error guardando: {e}")


def _load_summary() -> dict:
    _ensure_dirs()
    if SUMMARY_FILE.exists():
        try:
            return json.loads(SUMMARY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_summary(summary: dict):
    _ensure_dirs()
    try:
        SUMMARY_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    except OSError:
        pass


# ═══════════════════════════════════════════════════════════════
# 1. REGISTRAR EJECUCIÓN
# ═══════════════════════════════════════════════════════════════

def record_run(state: dict, start_time: float) -> dict:
    """Registra una ejecución completa en el benchmark.
    
    Args:
        state: TeamState de la ejecución
        start_time: time.time() del inicio
    
    Returns:
        Record almacenado
    """
    test_report = state.get("test_report", {})
    source_code = state.get("source_code", {})
    iteration_count = state.get("iteration_count", 0)
    router_stats = state.get("router_stats", {})
    
    time_elapsed = time.time() - start_time
    
    record = {
        "timestamp": datetime.now().isoformat(),
        "success": test_report.get("status") == "PASS",
        "iterations": iteration_count,
        "errors": len(test_report.get("errors", [])),
        "time_elapsed_seconds": round(time_elapsed, 2),
        "files_generated": len(source_code) if source_code else 0,
        "complexity": router_stats.get("complexity", "medium"),
        "model_pro_used": router_stats.get("pro_calls_used", 0),
        "model_max_pro": router_stats.get("max_pro", 0),
        "escalado": router_stats.get("escalado_label", "FLASH_TODO"),
        "requirement_preview": state.get("user_requirement", "")[:100],
    }
    
    # Guardar en historial
    history = _load_history()
    history.append(record)
    _save_history(history)
    
    print(f"[Benchmark] 📊 Run #{len(history)}: {'✅' if record['success'] else '❌'} "
          f"{record['iterations']} iter, {record['time_elapsed_seconds']:.1f}s, "
          f"{record['model_pro_used']}/{record['model_max_pro']} pro calls")
    
    return record


# ═══════════════════════════════════════════════════════════════
# 2. GENERAR REPORTE
# ═══════════════════════════════════════════════════════════════

def generate_report() -> dict:
    """Genera reporte completo del benchmark.
    
    Returns:
        Dict con métricas agregadas
    """
    history = _load_history()
    
    if not history:
        return {"message": "Sin datos de benchmark aún", "runs": 0}
    
    total = len(history)
    successes = sum(1 for r in history if r.get("success"))
    failures = total - successes
    success_rate = successes / total if total else 0
    
    # Últimas 20 ejecuciones
    recent = history[-20:] if len(history) >= 20 else history
    recent_successes = sum(1 for r in recent if r.get("success"))
    recent_rate = recent_successes / len(recent) if recent else 0
    
    # Tendencias
    avg_iterations = sum(r.get("iterations", 0) for r in history) / total
    avg_time = sum(r.get("time_elapsed_seconds", 0) for r in history) / total
    avg_errors = sum(r.get("errors", 0) for r in history) / total
    avg_files = sum(r.get("files_generated", 0) for r in history) / total
    
    # Por complejidad
    by_complexity = defaultdict(lambda: {"total": 0, "success": 0})
    for r in history:
        c = r.get("complexity", "medium")
        by_complexity[c]["total"] += 1
        if r.get("success"):
            by_complexity[c]["success"] += 1
    
    # Por modelo
    by_model = defaultdict(lambda: {"total": 0, "success": 0})
    for r in history:
        m = r.get("escalado", "unknown")
        by_model[m]["total"] += 1
        if r.get("success"):
            by_model[m]["success"] += 1
    
    # Tendencia temporal (últimos 50 runs en ventanas de 10)
    trend_data = []
    if len(history) >= 10:
        for i in range(0, len(history), 10):
            window = history[i:i+10]
            if len(window) >= 5:
                win_success = sum(1 for r in window if r.get("success"))
                trend_data.append({
                    "window_start": window[0].get("timestamp", ""),
                    "window_end": window[-1].get("timestamp", ""),
                    "rate": win_success / len(window),
                })
    
    # Mejora desde el inicio
    improvement = None
    if len(history) >= 20:
        first_10 = history[:10]
        last_10 = history[-10:]
        first_rate = sum(1 for r in first_10 if r.get("success")) / 10
        last_rate = sum(1 for r in last_10 if r.get("success")) / 10
        improvement = round(last_rate - first_rate, 3)
    
    report = {
        "total_runs": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(success_rate, 3),
        "recent_rate": round(recent_rate, 3),
        "trend": "mejorando" if improvement and improvement > 0.05 else "empeorando" if improvement and improvement < -0.05 else "estable",
        "improvement_from_baseline": improvement,
        "averages": {
            "iterations": round(avg_iterations, 1),
            "time_seconds": round(avg_time, 1),
            "errors": round(avg_errors, 1),
            "files_generated": round(avg_files, 1),
        },
        "by_complexity": dict(by_complexity),
        "by_model": dict(by_model),
        "trend_data": trend_data,
        "last_updated": datetime.now().isoformat(),
    }
    
    # Guardar resumen
    _save_summary(report)
    
    return report


# ═══════════════════════════════════════════════════════════════
# 3. VISUALIZAR REPORTE
# ═══════════════════════════════════════════════════════════════

def get_report_text() -> str:
    """Genera texto legible del reporte de benchmark."""
    report = generate_report()
    
    if "message" in report:
        return f"[Benchmark] {report['message']}"
    
    lines = [
        "\n" + "=" * 60,
        "  📊 BENCHMARK SUITE — Reporte de Rendimiento",
        "=" * 60,
        f"  Total runs: {report['total_runs']}",
        f"  ✅ Éxitos: {report['successes']} ({report['success_rate']*100:.1f}%)",
        f"  ❌ Fallos: {report['failures']}",
        f"  📈 Última tasa: {report['recent_rate']*100:.1f}%",
        f"  🎯 Tendencia: {report['trend'].upper()}",
        "",
        "  Promedios:",
        f"    Iteraciones: {report['averages']['iterations']}",
        f"    Tiempo: {report['averages']['time_seconds']}s",
        f"    Errores: {report['averages']['errors']}",
        f"    Archivos: {report['averages']['files_generated']}",
        "",
        "  Por complejidad:",
    ]
    
    for comp, stats in sorted(report.get("by_complexity", {}).items()):
        rate = (stats["success"] / stats["total"] * 100) if stats["total"] else 0
        bar = "█" * int(rate / 5) + "░" * (20 - int(rate / 5))
        lines.append(f"    {comp:10s} {bar} {rate:.0f}% ({stats['success']}/{stats['total']})")
    
    lines.append("")
    lines.append("  Por escalado de modelo:")
    for model, stats in sorted(report.get("by_model", {}).items()):
        rate = (stats["success"] / stats["total"] * 100) if stats["total"] else 0
        lines.append(f"    {model:20s} {rate:.0f}% ({stats['success']}/{stats['total']})")
    
    if report.get("improvement_from_baseline") is not None:
        imp = report["improvement_from_baseline"]
        emoji = "📈" if imp > 0 else "📉" if imp < 0 else "➡️"
        lines.append(f"\n  {emoji} Mejora desde baseline: {imp*100:+.1f}%")
    
    lines.append("=" * 60)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 4. COMPARAR CON ESTÁNDARES (SWE-bench style)
# ═══════════════════════════════════════════════════════════════

def compare_to_standards() -> str:
    """Compara rendimiento del enjambre con estándares de la industria."""
    
    # Estándares conocidos (junio 2026)
    standards = {
        "mini-SWE-agent (SWE-bench Verified)": 0.74,
        "SWE-agent 1.0 (SWE-bench Verified)": 0.65,
        "GPT-4o + SWE-agent (SWE-bench Lite)": 0.33,
        "Claude Sonnet 4 (SWE-bench Verified)": 0.58,
        "GPT-5 + mini-SWE-agent (SWE-bench Verified)": 0.74,
    }
    
    history = _load_history()
    if not history:
        return "[Benchmark] Sin datos para comparar"
    
    our_rate = sum(1 for r in history if r.get("success")) / len(history)
    
    lines = [
        "\n" + "=" * 60,
        "  📊 COMPARATIVA vs ESTÁNDARES DE LA INDUSTRIA",
        "=" * 60,
        f"  Enjambre-dev:  {'▰' * int(our_rate * 20)}{'▱' * (20 - int(our_rate * 20))} {our_rate*100:.1f}%",
        "",
        "  Referencias (SWE-bench Verified):",
    ]
    
    for name, rate in standards.items():
        bar = "▰" * int(rate * 20) + "▱" * (20 - int(rate * 20))
        indicator = " ← NOSOTROS" if abs(rate - our_rate) < 0.02 else ""
        lines.append(f"    {name:40s} {bar} {rate*100:.0f}%{indicator}")
    
    lines.append("=" * 60)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 5. RESET
# ═══════════════════════════════════════════════════════════════

def reset_benchmarks():
    """Resetea todos los datos de benchmark."""
    _ensure_dirs()
    if BENCHMARK_FILE.exists():
        BENCHMARK_FILE.unlink()
    if SUMMARY_FILE.exists():
        SUMMARY_FILE.unlink()
    print("[Benchmark] 🔄 Datos de benchmark reseteados")
