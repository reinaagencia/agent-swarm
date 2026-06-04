"""🧠 Model Router Inteligente — Escalado quirúrgico flash↔pro.

FUENTE DE VERDAD UNIFICADA:
  Este archivo y ~/.agents/skills/model-router/SKILL.md son la MISMA source of truth.
  Si modificas uno, actualiza el otro.

Estrategia:
  - Flash (gratis) → 95% del trabajo: generación, análisis, testing rutinario
  - Pro (pago, $) → 5% estratégico: desbloqueo de loops, auditoría crítica,
    debugging cuando flash falla, decisiones arquitectónicas complejas
  
El router decide por nodo + contexto usando:
  1. Nivel de escalado actual (0-4)
  2. Historial de errores del nodo
  3. Presupuesto de calls pro restantes
  4. Complejidad de la tarea
  5. Nodo específico que pide el modelo

Presupuesto dinámico:
  - simple:  max 1 call pro
  - medium: max 2 calls pro
  - high:   max 4 calls pro
  - Si se agota → todo flash (o abortar si es crítica)
"""

import json
from pathlib import Path
from enum import IntEnum

# ── Niveles de escalado ──
class Escalado(IntEnum):
    FLASH_TODO = 0          # Todo con flash (gratis)
    GATES_PRO = 1           # Solo gates auditor usan pro
    DEBUG_PRO = 2           # Programador + Tester escalan a pro si fallan
    PROGRAMADOR_PRO = 3     # Programador siempre pro, tester flash
    TODO_PRO = 4            # Todo pro (máximo)

# ── Perfiles de nodo ──
PERFIL_NODO = {
    "Investigador":       {"critico": False, "beneficio_pro": 0.1,  "tolerancia_fallo": "alta"},
    "SkillResolver":      {"critico": False, "beneficio_pro": 0.2,  "tolerancia_fallo": "alta"},
    "Orquestador":        {"critico": True,  "beneficio_pro": 0.3,  "tolerancia_fallo": "media"},
    "Auditor Gate 1":     {"critico": True,  "beneficio_pro": 0.9,  "tolerancia_fallo": "baja"},
    "Arquitecto":         {"critico": True,  "beneficio_pro": 0.5,  "tolerancia_fallo": "media"},
    "Auditor Gate 2":     {"critico": True,  "beneficio_pro": 0.9,  "tolerancia_fallo": "baja"},
    "Programador":        {"critico": False, "beneficio_pro": 0.7,  "tolerancia_fallo": "alta"},
    "Tester":             {"critico": False, "beneficio_pro": 0.4,  "tolerancia_fallo": "alta"},
    "Auditor Gate 3":     {"critico": True,  "beneficio_pro": 0.95, "tolerancia_fallo": "baja"},
    "Extractor":          {"critico": False, "beneficio_pro": 0.1,  "tolerancia_fallo": "alta"},
}

# ── Presupuesto por complejidad ──
MAX_PRO_CALLS = {
    "low":    1,
    "medium": 2,
    "high":   4,
}

# ── Archivo local para persistencia del router ──
ROUTER_STATE_PATH = Path.home() / ".agents" / "router_state.json"


# ── Singleton del router (compartido entre nodos en la misma ejecución) ──
_router_instance = None


# ── Almacenar complejidad entre reset y get ──
_router_complexity = "medium"


def get_router() -> "ModelRouter":
    """Devuelve el router singleton para la ejecución actual."""
    global _router_instance, _router_complexity
    if _router_instance is None:
        _router_instance = ModelRouter(complexity=_router_complexity)
    return _router_instance


def reset_router(complexity: str = "medium"):
    """Reinicia el router para una nueva ejecución.
    
    Args:
        complexity: Nivel de complejidad detectado ("low", "medium", "high")
    """
    global _router_instance, _router_complexity
    _router_complexity = complexity
    _router_instance = None


class ModelRouter:
    """Router central de modelos con escalado quirúrgico.
    
    Uso:
        router = ModelRouter(complexity="medium")
        model = router.decide("Programador", iteration=2, errors=3)
        # → "pro" si se agotaron iteraciones y hay presupuesto
    """
    
    def __init__(self, complexity: str = "medium"):
        self.complexity = complexity
        self.escalado = Escalado.FLASH_TODO
        self.pro_calls_used = 0
        self.max_pro = MAX_PRO_CALLS.get(complexity, 2)
        self.history = []          # Registro de decisiones tomadas
        self.pro_active_override = 0  # Nivel de escalado pro-activo (0=desactivado, 1-4)
        self._load_state()
    
    def _load_state(self):
        """Carga estado persistido del router (aprendizaje entre ejecuciones)."""
        try:
            if ROUTER_STATE_PATH.exists():
                data = json.loads(ROUTER_STATE_PATH.read_text())
                self.history = data.get("history", [])
        except (json.JSONDecodeError, OSError):
            self.history = []
    
    def _save_state(self):
        """Persiste estado del router para aprendizaje futuro."""
        try:
            ROUTER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Solo guardar últimos 100 registros
            data = {"history": self.history[-100:]}
            ROUTER_STATE_PATH.write_text(json.dumps(data, indent=2))
        except (OSError, json.JSONEncodeError):
            pass
    
    def _calcular_escalado(self, iteration: int, errors: int, loop_detected: bool):
        """Determina el nivel de escalado según iteración, errores y CONFIG PRO-ACTIVA (v3.0).
        
        AHORA: Si el Meta-Planner configuró pro_active_desde_inicio=True,
        el escalado empieza en GATES_PRO (nivel 1) en vez de FLASH_TODO.
        Esto evita las iteraciones perdidas por no tener suficiente poder
        de razonamiento desde el principio.
        """
        # Escalado PRO-ACTIVO: si el Meta-Planner lo recomendó
        if self.pro_active_override:
            self.escalado = Escalado(self.pro_active_override)
            return
            
        # Escalado REACTIVO (original, para tareas simples)    
        if loop_detected or iteration >= 5:
            self.escalado = Escalado.TODO_PRO
        elif iteration >= 4 or errors >= 10:
            self.escalado = Escalado.PROGRAMADOR_PRO
        elif iteration >= 3 or errors >= 5:
            self.escalado = Escalado.DEBUG_PRO
        elif iteration >= 1 or errors >= 2:
            self.escalado = Escalado.GATES_PRO
        else:
            self.escalado = Escalado.FLASH_TODO
    
    def _tiene_presupuesto(self) -> bool:
        """Verifica si quedan calls pro disponibles."""
        return self.pro_calls_used < self.max_pro
    
    def _usar_pro(self, nodo: str) -> bool:
        """Decide si este nodo DEBE usar pro según el nivel de escalado."""
        perfil = PERFIL_NODO.get(nodo, {"critico": False, "beneficio_pro": 0.3})
        
        # Reglas quirúrgicas:
        
        # 1. Gates auditor SIEMPRE usan pro (son el punto de control de calidad)
        if "Auditor Gate" in nodo:
            return True
        
        # 2. Si escalado es máximo, todo pro
        if self.escalado >= Escalado.TODO_PRO:
            return True
        
        # 3. Si escalado es PROGRAMADOR_PRO, Programador usa pro
        if self.escalado >= Escalado.PROGRAMADOR_PRO and nodo == "Programador":
            return True
        
        # 4. Si escalado es DEBUG_PRO y el nodo falló antes, usar pro
        if self.escalado >= Escalado.DEBUG_PRO:
            if perfil["beneficio_pro"] >= 0.6:  # Nodos con alto beneficio de pro
                return True
        
        # 5. Si es crítico y estamos en GATES_PRO
        if self.escalado >= Escalado.GATES_PRO and perfil["critico"]:
            return True
        
        # 6. Default: flash
        return False
    
    def decide(self, nodo: str, iteration: int = 0, errors: int = 0,
               loop_detected: bool = False, force_pro: bool = False) -> str:
        """Decide qué modelo usar para un nodo dado.
        
        Args:
            nodo: Nombre del nodo (ej: "Programador", "Tester")
            iteration: Número de iteración actual
            errors: Cantidad de errores detectados
            loop_detected: True si se detectó bucle sin progreso
            force_pro: True para forzar pro (override)
            
        Returns:
            "flash" o "pro"
        """
        # Actualizar escalado
        self._calcular_escalado(iteration, errors, loop_detected)
        
        # Si hay presupuesto y toca pro, usar pro
        debe_ser_pro = force_pro or self._usar_pro(nodo)
        
        if debe_ser_pro and self._tiene_presupuesto():
            self.pro_calls_used += 1
            decision = "pro"
        elif debe_ser_pro and not self._tiene_presupuesto():
            # Sin presupuesto: forzar flash pero registrar
            decision = "flash"
            print(f"  [Router] ⚠️ {nodo}: quería pro pero sin presupuesto (usados {self.pro_calls_used}/{self.max_pro})")
        else:
            decision = "flash"
        
        # Registrar decisión
        entry = {
            "nodo": nodo,
            "decision": decision,
            "escalado": self.escalado,
            "iteration": iteration,
            "errors": errors,
            "pro_used": self.pro_calls_used,
            "max_pro": self.max_pro,
        }
        self.history.append(entry)
        
        return decision
    
    def get_llm_for_node(self, nodo: str, iteration: int = 0, errors: int = 0,
                          loop_detected: bool = False) -> tuple:
        """Versión completa: devuelve (model_type, temperature, max_tokens) para el nodo.
        
        Returns:
            (model_type, temperature, max_tokens)
            model_type: "flash" | "pro"
        """
        model_type = self.decide(nodo, iteration, errors, loop_detected)
        
        # Temperaturas según nodo y modelo
        temps = {
            "flash": {
                "Programador": 0.4,
                "Tester": 0.2,
                "Arquitecto": 0.3,
                "default": 0.3,
            },
            "pro": {
                "default": 0.15,  # Pro: más determinista
            }
        }
        
        if model_type == "pro":
            temperature = 0.15
            max_tokens = 1024  # Pro se usa para análisis concisos
        else:
            temp_map = temps["flash"]
            temperature = temp_map.get(nodo, temp_map["default"])
            max_tokens = 4096 if nodo == "Programador" else 1024
        
        return (model_type, temperature, max_tokens)
    
    def get_stats(self) -> dict:
        """Devuelve estadísticas del router para logging."""
        return {
            "escalado": int(self.escalado),
            "escalado_label": self.escalado.name,
            "pro_calls_used": self.pro_calls_used,
            "max_pro": self.max_pro,
            "pro_remaining": self.max_pro - self.pro_calls_used,
            "complexity": self.complexity,
            "total_decisions": len(self.history),
        }
    
    def set_pro_active_override(self, nivel: int = 0):
        """Configura escalado pro-activo desde el Meta-Planner (Gate 0).
        
        Args:
            nivel: Nivel de escalado inicial (1=GATES_PRO, 2=DEBUG_PRO, etc.)
                   0 = desactivado (comportamiento reactivo normal)
        """
        self.pro_active_override = nivel
        if nivel > 0:
            self.escalado = Escalado(nivel)
            print(f"  [Router] 🚀 Escalado PRO-ACTIVO: nivel {nivel} ({Escalado(nivel).name})")
    
    def reset(self):
        """Reinicia el router para una nueva ejecución."""
        self.escalado = Escalado.FLASH_TODO
        self.pro_calls_used = 0
        self.pro_active_override = 0
        self.history = []
    
    def aprender(self, ejecucion_exitosa: bool, calidad: float,
                  iteraciones: int = 0, errores: int = 0,
                  complexity: str = "medium"):
        """Actualiza el aprendizaje del router tras una ejecución.
        
        Sistema de aprendizaje por refuerzo:
        1. Registra cada ejecución en el historial
        2. Ajusta max_pro dinámicamente según tasa de éxito
        3. Aprende qué nodos necesitan más calls pro
        4. Persiste el estado para futuras ejecuciones
        
        Args:
            ejecucion_exitosa: True si la tarea terminó en PASS
            calidad: Señal de refuerzo compuesta (0.0-1.0)
            iteraciones: Número de iteraciones usadas
            errores: Cantidad de errores detectados
            complexity: Nivel de complejidad de la tarea
        """
        # Guardar en historial (persistente entre ejecuciones)
        self.history.append({
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "success": ejecucion_exitosa,
            "quality": calidad,
            "iterations": iteraciones,
            "errors": errores,
            "complexity": complexity,
            "pro_used": self.pro_calls_used,
            "max_pro": self.max_pro,
        })
        
        # Ajustar max_pro dinámicamente según rendimiento histórico
        # Solo considerar ejecuciones recientes (últimas 20)
        recent = [h for h in self.history[-20:] if h.get("complexity") == complexity]
        if len(recent) >= 3:
            success_rate = sum(1 for h in recent if h.get("success")) / len(recent)
            
            # Si alta tasa de fallo → necesitamos más pro
            if success_rate < 0.4:
                # Aumentar max_pro (pero no más de 8)
                base = MAX_PRO_CALLS.get(complexity, 2)
                new_max = min(base * 2, 8)
                if new_max > self.max_pro:
                    print(f"  [Router] 📈 Alta tasa de fallo ({success_rate:.0%}) → "
                          f"max_pro aumentado: {self.max_pro} → {new_max}")
                    self.max_pro = new_max
            
            # Si alta tasa de éxito → podemos reducir pro
            elif success_rate > 0.85:
                base = MAX_PRO_CALLS.get(complexity, 2)
                new_max = max(base, self.max_pro - 1)
                if new_max < self.max_pro:
                    print(f"  [Router] 📉 Alta tasa de éxito ({success_rate:.0%}) → "
                          f"max_pro reducido: {self.max_pro} → {new_max}")
                    self.max_pro = new_max
        
        # Registrar en log
        calidad_str = f"{calidad:.3f}"
        success_str = "✅" if ejecucion_exitosa else "❌"
        print(f"  [Router] 📚 Aprendizaje: {success_str} calidad={calidad_str} "
              f"iter={iteraciones} err={errores} max_pro={self.max_pro}")
        
        # Persistir
        self._save_state()


# ── Función helper para que reflection.py llame sin instanciar router ──
def update_router_learning(success: bool, quality: float, iterations: int,
                            errors: int, complexity: str):
    """Actualiza el aprendizaje del router desde el nodo de reflexión.
    
    Esta función obtiene el router singleton y llama a aprender().
    """
    try:
        router = get_router()
        router.aprender(
            ejecucion_exitosa=success,
            calidad=quality,
            iteraciones=iterations,
            errores=errors,
            complexity=complexity,
        )
    except Exception as e:
        print(f"  [Router] ⚠️ Error en update_router_learning: {e}")
