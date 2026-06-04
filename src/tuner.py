"""Self-Tuning Loop — Fase 5: Mejora Continua Automática.

Analiza el historial de métricas y ajusta automáticamente los presupuestos
del pipeline para optimizar velocidad, tokens y costo.

Reglas de ajuste:
- Si baja complejidad es consistentemente rápida (<2 iter, <100s) → reducir budgets 10%
- Si media complejidad es lenta (>5 iter, >300s) → aumentar budgets 10%
- Si alta complejidad tiene >30% fallo → escalar Pro antes (iter 3 en vez de 5)
- Si consumo de tokens está muy por debajo del presupuesto → reducir 15%
- Si consumo excede presupuesto → aumentar 15%

Los ajustes se guardan en ~/.agents/enjambre_tuning.json y se leen al iniciar.
"""

import json
import os
from pathlib import Path
from datetime import datetime

from src.metrics import get_recent_runs, get_summary

TUNING_FILE = Path.home() / ".agents" / "enjambre_tuning.json"

# Ajustes por defecto (sin modificaciones)
DEFAULT_TUNING = {
    "budget_multiplier_low": 1.0,
    "budget_multiplier_medium": 1.0,
    "budget_multiplier_high": 1.0,
    "escalation_tester_iter": 5,     # Primera iteración donde Tester sube a Pro
    "escalation_programmer_iter": 7, # Primera iteración donde Programador sube a Pro
    "escalation_architect_iter": 9,  # Primera iteración donde Arquitecto rediseña
    "hard_cap_high": 20,
    "hard_cap_medium": 15,
    "hard_cap_low": 5,
    "last_tuned": None,
}


def _load_tuning() -> dict:
    """Carga la configuración de tuning actual."""
    if TUNING_FILE.exists():
        try:
            with open(TUNING_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_TUNING)


def _save_tuning(tuning: dict):
    """Guarda la configuración de tuning."""
    TUNING_FILE.parent.mkdir(parents=True, exist_ok=True)
    tuning["last_tuned"] = datetime.now().isoformat()
    with open(TUNING_FILE, "w") as f:
        json.dump(tuning, f, indent=2)


def get_tuning() -> dict:
    """Obtiene la configuración de tuning (para usar desde config.py)."""
    return _load_tuning()


def auto_tune():
    """Analiza el historial y ajusta los parámetros automáticamente.
    
    Se llama después de cada ejecución del pipeline.
    Retorna dict con los cambios realizados.
    """
    tuning = _load_tuning()
    summary = get_summary()
    recent = get_recent_runs(30)
    
    cambios = {"ajustes_realizados": [], "nuevos_valores": {}}
    
    # ── 1. Analizar por nivel de complejidad ──
    for complexity in ["low", "medium", "high"]:
        runs = [r for r in recent if r.get("complexity") == complexity]
        if len(runs) < 3:
            continue  # Necesitamos al menos 3 ejecuciones para ajustar
        
        avg_iter = sum(r.get("iterations", 1) for r in runs) / len(runs)
        avg_time = sum(r.get("time_seconds", 0) for r in runs) / len(runs)
        pass_count = sum(1 for r in runs if r.get("status") == "PASS")
        fail_rate = 1 - (pass_count / len(runs)) if runs else 0
        
        # ── Low complexity: si consistentemente rápido, reducir budgets ──
        if complexity == "low":
            if avg_iter < 2 and avg_time < 100 and fail_rate < 0.1:
                new_mult = max(0.6, tuning.get("budget_multiplier_low", 1.0) - 0.1)
                if new_mult != tuning.get("budget_multiplier_low"):
                    tuning["budget_multiplier_low"] = new_mult
                    cambios["ajustes_realizados"].append(
                        f"low: promedio {avg_time:.0f}s/{avg_iter:.1f} iter → budget x{new_mult}"
                    )
            elif avg_iter > 4 or avg_time > 200:
                new_mult = min(1.5, tuning.get("budget_multiplier_low", 1.0) + 0.15)
                if new_mult != tuning.get("budget_multiplier_low"):
                    tuning["budget_multiplier_low"] = new_mult
                    cambios["ajustes_realizados"].append(
                        f"low: lento ({avg_time:.0f}s/{avg_iter:.1f} iter) → budget x{new_mult}"
                    )
        
        # ── Medium complexity ──
        elif complexity == "medium":
            if avg_iter > 5 or avg_time > 300:
                new_mult = min(1.5, tuning.get("budget_multiplier_medium", 1.0) + 0.1)
                if new_mult != tuning.get("budget_multiplier_medium"):
                    tuning["budget_multiplier_medium"] = new_mult
                    cambios["ajustes_realizados"].append(
                        f"medium: lento ({avg_time:.0f}s/{avg_iter:.1f} iter) → budget x{new_mult}"
                    )
            elif avg_iter < 2 and avg_time < 150:
                new_mult = max(0.7, tuning.get("budget_multiplier_medium", 1.0) - 0.1)
                if new_mult != tuning.get("budget_multiplier_medium"):
                    tuning["budget_multiplier_medium"] = new_mult
                    cambios["ajustes_realizados"].append(
                        f"medium: rápido ({avg_time:.0f}s/{avg_iter:.1f} iter) → budget x{new_mult}"
                    )
        
        # ── High complexity: si alta tasa de fallo, escalar Pro antes ──
        elif complexity == "high":
            if fail_rate > 0.3:
                # Escalar Pro antes
                if tuning.get("escalation_tester_iter", 5) > 3:
                    tuning["escalation_tester_iter"] = 3
                    cambios["ajustes_realizados"].append(
                        f"high: {fail_rate*100:.0f}% fallo → Tester Pro desde iter 3"
                    )
                if tuning.get("escalation_programmer_iter", 7) > 5:
                    tuning["escalation_programmer_iter"] = 5
                    cambios["ajustes_realizados"].append(
                        f"high: {fail_rate*100:.0f}% fallo → Programador Pro desde iter 5"
                    )
            elif fail_rate < 0.1 and avg_iter < 3:
                # Bajo fallo, podemos relajar
                tuning["hard_cap_high"] = min(25, tuning.get("hard_cap_high", 20) + 2)
                cambios["ajustes_realizados"].append(
                    f"high: {fail_rate*100:.0f}% éxito → hard cap +2"
                )
    
    # ── 2. Guardar cambios si hubo alguno ──
    if cambios["ajustes_realizados"]:
        _save_tuning(tuning)
        cambios["nuevos_valores"] = {
            k: tuning[k] for k in [
                "budget_multiplier_low", "budget_multiplier_medium", "budget_multiplier_high",
                "escalation_tester_iter", "escalation_programmer_iter", "escalation_architect_iter",
                "hard_cap_high", "hard_cap_medium", "hard_cap_low",
            ]
        }
        print(f"[Tuner] ✅ Auto-ajuste completado: {len(cambios['ajustes_realizados'])} cambios")
        for c in cambios["ajustes_realizados"]:
            print(f"[Tuner]   • {c}")
    else:
        print(f"[Tuner] ℹ️  Sin ajustes necesarios (promedios dentro de rango)")
    
    return cambios


def reset_tuning():
    """Resetea el tuning a valores por defecto."""
    _save_tuning(dict(DEFAULT_TUNING))
    print("[Tuner] 🔄 Tuning reseteado a valores por defecto")


def show_tuning() -> str:
    """Muestra la configuración de tuning actual."""
    tuning = _load_tuning()
    lines = [
        "=" * 60,
        "  🎛️  CONFIGURACIÓN DE TUNING",
        "=" * 60,
        f"  Budget multipliers:",
        f"    Low:    x{tuning.get('budget_multiplier_low', 1.0)}",
        f"    Medium: x{tuning.get('budget_multiplier_medium', 1.0)}",
        f"    High:   x{tuning.get('budget_multiplier_high', 1.0)}",
        f"",
        f"  Escalamiento (primera iter Pro):",
        f"    Tester:       iter {tuning.get('escalation_tester_iter', 5)}",
        f"    Programador:  iter {tuning.get('escalation_programmer_iter', 7)}",
        f"    Arquitecto:   iter {tuning.get('escalation_architect_iter', 9)}",
        f"",
        f"  Hard caps:",
        f"    Low:    {tuning.get('hard_cap_low', 5)} iteraciones",
        f"    Medium: {tuning.get('hard_cap_medium', 15)} iteraciones",
        f"    High:   {tuning.get('hard_cap_high', 20)} iteraciones",
        f"",
        f"  Último ajuste: {tuning.get('last_tuned', 'nunca')}",
        "=" * 60,
    ]
    return "\n".join(lines)
