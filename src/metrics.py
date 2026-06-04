"""Sistema de métricas del enjambre — Fase 4: Aprendizaje Autónomo.

Registra cada ejecución del pipeline para:
- Detectar tendencias de rendimiento (tiempo, tokens, costo)
- Identificar tipos de tarea con mayor/menor éxito
- Auto-ajustar presupuestos basado en datos históricos
- Generar reportes semanales

Almacenamiento: archivos JSON en ~/.agents/enjambre_metrics/
"""

import json
import os
import time
from datetime import datetime, date
from pathlib import Path

METRICS_DIR = Path.home() / ".agents" / "enjambre_metrics"
RUNS_DIR = METRICS_DIR / "runs"
SUMMARY_FILE = METRICS_DIR / "summary.json"


def _ensure_dirs():
    """Crea directorios de métricas si no existen."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _today_file() -> Path:
    """Devuelve la ruta del archivo de hoy."""
    return RUNS_DIR / f"{date.today().isoformat()}.json"


def record_run(metrics: dict):
    """Registra una ejecución del pipeline.
    
    Args:
        metrics: dict con campos: timestamp, task_type, complexity, status,
                iterations, time_seconds, num_files, num_llm_calls,
                total_input_tokens, total_output_tokens, estimated_cost,
                skills_activated, error_summary
    """
    _ensure_dirs()

    # Asegurar campos mínimos
    record = {
        "timestamp": datetime.now().isoformat(),
        "task_type": metrics.get("task_type", "unknown"),
        "complexity": metrics.get("complexity", "unknown"),
        "status": metrics.get("status", "UNKNOWN"),
        "iterations": metrics.get("iterations", 0),
        "time_seconds": round(metrics.get("time_seconds", 0), 2),
        "num_files": metrics.get("num_files", 0),
        "num_llm_calls": metrics.get("num_llm_calls", 0),
        "total_input_tokens": metrics.get("total_input_tokens", 0),
        "total_output_tokens": metrics.get("total_output_tokens", 0),
        "estimated_cost": round(metrics.get("estimated_cost", 0), 8),
        "skills_activated": metrics.get("skills_activated", []),
        "error_summary": metrics.get("error_summary", ""),
        "requirement_summary": metrics.get("requirement_summary", "")[:100],
    }

    # Cargar registros de hoy
    today_file = _today_file()
    today_runs = []
    if today_file.exists():
        try:
            with open(today_file) as f:
                today_runs = json.load(f)
        except (json.JSONDecodeError, OSError):
            today_runs = []

    # Agregar nuevo registro
    today_runs.append(record)

    # Guardar
    with open(today_file, "w") as f:
        json.dump(today_runs, f, indent=2, ensure_ascii=False)

    # Actualizar summary
    _update_summary(record)


def _update_summary(new_record: dict):
    """Actualiza el resumen agregado."""
    _ensure_dirs()
    
    summary = {"total_runs": 0, "pass_count": 0, "fail_count": 0,
               "total_time": 0, "total_cost": 0, "total_tokens": 0,
               "by_complexity": {}, "by_task_type": {},
               "last_updated": datetime.now().isoformat()}
    
    if SUMMARY_FILE.exists():
        try:
            with open(SUMMARY_FILE) as f:
                summary = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Actualizar contadores
    summary["total_runs"] = summary.get("total_runs", 0) + 1
    if new_record["status"] == "PASS":
        summary["pass_count"] = summary.get("pass_count", 0) + 1
    elif new_record["status"] == "FAIL":
        summary["fail_count"] = summary.get("fail_count", 0) + 1
    
    summary["total_time"] = summary.get("total_time", 0) + new_record["time_seconds"]
    summary["total_cost"] = summary.get("total_cost", 0) + new_record["estimated_cost"]
    summary["total_tokens"] = summary.get("total_tokens", 0) + new_record["total_input_tokens"] + new_record["total_output_tokens"]
    summary["last_updated"] = datetime.now().isoformat()

    # Por complejidad
    comp = new_record["complexity"]
    comp_stats = summary.setdefault("by_complexity", {}).setdefault(comp, {"runs": 0, "pass": 0})
    comp_stats["runs"] = comp_stats.get("runs", 0) + 1
    if new_record["status"] == "PASS":
        comp_stats["pass"] = comp_stats.get("pass", 0) + 1

    # Por tipo de tarea
    tt = new_record["task_type"]
    tt_stats = summary.setdefault("by_task_type", {}).setdefault(tt, {"runs": 0, "pass": 0})
    tt_stats["runs"] = tt_stats.get("runs", 0) + 1
    if new_record["status"] == "PASS":
        tt_stats["pass"] = tt_stats.get("pass", 0) + 1

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


def get_recent_runs(days: int = 7) -> list[dict]:
    """Obtiene ejecuciones de los últimos N días."""
    _ensure_dirs()
    all_runs = []
    today = date.today()
    
    for i in range(days):
        d = date.fromordinal(today.toordinal() - i)
        f = RUNS_DIR / f"{d.isoformat()}.json"
        if f.exists():
            try:
                with open(f) as fh:
                    all_runs.extend(json.load(fh))
            except (json.JSONDecodeError, OSError):
                pass
    
    return all_runs


def get_summary() -> dict:
    """Obtiene el resumen agregado."""
    if SUMMARY_FILE.exists():
        try:
            with open(SUMMARY_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"total_runs": 0}


def generate_report() -> str:
    """Genera un reporte de rendimiento en texto plano."""
    summary = get_summary()
    recent = get_recent_runs(7)
    
    lines = [
        "=" * 60,
        "  📊 REPORTE DE RENDIMIENTO DEL ENJAMBRE",
        "=" * 60,
        f"  Ejecuciones totales: {summary.get('total_runs', 0)}",
        f"  Tasa de éxito: {_pct(summary.get('pass_count', 0), summary.get('total_runs', 0))}%",
        f"  Tiempo total: {summary.get('total_time', 0):.1f}s",
        f"  Costo total estimado: ${summary.get('total_cost', 0):.6f}",
        f"  Tokens totales: {summary.get('total_tokens', 0):,}",
        "",
        "  Últimas ejecuciones:",
    ]
    
    for run in recent[-5:]:
        lines.append(
            f"    [{run.get('timestamp','')[:16]}] "
            f"{run.get('complexity','?'):>6} "
            f"{'✅' if run.get('status')=='PASS' else '❌'} "
            f"{run.get('task_type','?'):20s} "
            f"{run.get('time_seconds',0):>6.1f}s "
            f"iter={run.get('iterations',0)}"
        )
    
    lines.append("")
    lines.append("  Por nivel de complejidad:")
    for comp, stats in summary.get("by_complexity", {}).items():
        lines.append(
            f"    {comp:>8}: {stats.get('runs',0)} ejecuciones, "
            f"{_pct(stats.get('pass',0), stats.get('runs',0))}% éxito"
        )
    
    lines.append("")
    lines.append(f"  Última actualización: {summary.get('last_updated', 'N/A')}")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def _pct(part: int, total: int) -> float:
    """Calcula porcentaje."""
    if total == 0:
        return 0.0
    return round(part / total * 100, 1)
