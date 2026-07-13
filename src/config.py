"""Configuración central del enjambre de agentes — LLM clientes + Supabase.

ARQUITECTURA DE FALLBACK (3 NIVELES):
  Nivel 0: reinaagenciacol · Zen (free) · deepseek-v4-flash-free
  Nivel 1: rzuluam        · Zen (free) · deepseek-v4-flash-free ← NUEVO
  Nivel 2: reinaagenciacol · Go (pago)  · deepseek-v4-flash

  Pro (Auditor): siempre reinaagenciacol · Go (pago) · deepseek-v4-pro

ESTRATEGIA:
  Free-first en 2 cuentas antes de pagar. Si 429 en reina free → rzuluam free.
  Si 429 en rzuluam free → reina Go (pago). Si 429 en Go → error.
  Ver skill model-router para documentación completa."""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# ═══════════════════════════════════════════════════════════════
# API Keys — 2 cuentas para maximizar uso gratuito
# ═══════════════════════════════════════════════════════════════

# Cuenta principal: reinaagenciacol@gmail.com (plan Zen + Go)
OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY", "")

# Cuenta secundaria: rzuluam@gmail.com (plan Zen solamente)
RZULUAM_API_KEY = os.getenv("RZULUAM_API_KEY", "sk-sInMXGDr8Niijx291ufvMJLRUgSqQPejnqtvW8NAriKLBa0cgWRoKtvIN2Ze29MZ")

# ═══════════════════════════════════════════════════════════════
# Keys por nivel de fallback
# ═══════════════════════════════════════════════════════════════
FALLBACK_KEYS = [
    {"name": "reinaagenciacol (Zen)", "key": OPENCODE_API_KEY, "url": None},           # Nivel 0
    {"name": "rzuluam (Zen)",        "key": RZULUAM_API_KEY,   "url": None},           # Nivel 1
    {"name": "reinaagenciacol (Go)",  "key": OPENCODE_API_KEY, "url": "go"},           # Nivel 2
]

# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════
OPENCODE_ZEN_BASE_URL = os.getenv("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1")
OPENCODE_GO_BASE_URL = os.getenv("OPENCODE_GO_BASE_URL", "https://opencode.ai/zen/go/v1")
OPENCODE_BASE_URL = os.getenv("OPENCODE_BASE_URL", OPENCODE_ZEN_BASE_URL)

# ═══════════════════════════════════════════════════════════════
# Modelos del pipeline
# ═══════════════════════════════════════════════════════════════

OPENCODE_MODEL_FREE = os.getenv("OPENCODE_MODEL", "deepseek-v4-flash-free")
OPENCODE_MODEL_PAID = os.getenv("OPENCODE_MODEL_PAID", "deepseek-v4-flash")

# Modelo premium para auditoría y micro-gates
# Antes: deepseek-v4-pro ($1.74 in / $3.48 out)
# Ahora:  qwen3.7-plus   ($0.40 in / $1.60 out) — 4.35x más barato
OPENCODE_PRO_MODEL = os.getenv("OPENCODE_PRO_MODEL", "qwen3.7-plus")

# ═══════════════════════════════════════════════════════════════
# Nemotron 3 Ultra Free (temporal, plan Zen)
# ═══════════════════════════════════════════════════════════════
# Mismo API key y endpoint que los demás modelos Zen.
# Según la página oficial de OpenCode Zen (10 jun 2026):
#   Model ID: nemotron-3-ultra-free
#   En OpenCode: opencode/nemotron-3-ultra-free
#   Precio: FREE (disponible por tiempo limitado)
#   Endpoint: https://opencode.ai/zen/v1/chat/completions
NEMOTRON_MODEL = "nemotron-3-ultra-free"


def get_nemotron_llm(temperature: float = 0.3, max_tokens: int = 4096) -> ChatOpenAI:
    """Cliente LLM para Nemotron 3 Ultra Free (plan Zen, gratis).
    
    Periodo promocional por tiempo limitado. Usa el mismo API key
    y endpoint que deepseek-v4-flash-free.
    
    Args:
        temperature: Temperatura (default 0.3)
        max_tokens: Máximo de tokens de salida (default 4096)
    """
    return ChatOpenAI(
        model=NEMOTRON_MODEL,
        api_key=OPENCODE_API_KEY,
        base_url=OPENCODE_ZEN_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ═══════════════════════════════════════════════════════════════
# MoA Multi-Model Helpers — Inteligencia Amplificada
# ═══════════════════════════════════════════════════════════════

def get_kimi_llm(temperature: float = 0.3, max_tokens: int = 2048) -> ChatOpenAI:
    """Cliente LLM para Kimi K2.5 (Go pago).
    
    Excelente para análisis estratégico, creativo y perspectivas
    alternativas en el MoA ensemble.
    """
    return ChatOpenAI(
        model="opencode-go/kimi-k2.5",
        api_key=OPENCODE_API_KEY,
        base_url=OPENCODE_GO_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def get_deepseek_pro_llm(temperature: float = 0.15, max_tokens: int = 2048) -> ChatOpenAI:
    """Cliente LLM para DeepSeek V4 Pro (Go pago).
    
    El modelo más inteligente del stack. Para razonamiento extremo,
    MoA aggregation, y decisiones críticas de arquitectura.
    HLE: 37.7 — SWE-Bench: 74.5
    """
    return ChatOpenAI(
        model="deepseek-v4-pro",
        api_key=OPENCODE_API_KEY,
        base_url=OPENCODE_GO_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def get_model_llm(model_id: str, temperature: float = 0.3, max_tokens: int = 2048,
                  use_go: bool = True) -> ChatOpenAI:
    """Cliente LLM genérico para cualquier modelo del stack.
    
    Args:
        model_id: ID del modelo (ej: "opencode-go/kimi-k2.5", "deepseek-v4-pro")
        temperature: Temperatura
        max_tokens: Máximo de tokens de salida
        use_go: True = Go endpoint (pago), False = Zen endpoint (free)
    
    Returns:
        ChatOpenAI configurado para el modelo solicitado
    """
    base_url = OPENCODE_GO_BASE_URL if use_go else OPENCODE_ZEN_BASE_URL
    return ChatOpenAI(
        model=model_id,
        api_key=OPENCODE_API_KEY,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ═══════════════════════════════════════════════════════════════
# Modelos Locales (Ollama)
# ═══════════════════════════════════════════════════════════════

# URL base de Ollama local (https://ollama.com)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

def get_ollama_llm(model: str = "qwen3:8b", temperature: float = 0.3,
                   max_tokens: int = 4096) -> ChatOpenAI:
    """Cliente LLM para modelos locales vía Ollama.
    
    Args:
        model: Modelo Ollama (ej: "qwen3:8b", "gemma4:12b", "deepseek-r1:7b")
        temperature: Temperatura
        max_tokens: Máximo de tokens de salida
    
    Uso:
        llm = get_ollama_llm("gemma4:12b")
        response = await llm.ainvoke([...])
    
    Requiere:
        - Ollama corriendo (ollama serve)
        - Modelo descargado (ollama pull qwen3:8b)
    """
    return ChatOpenAI(
        model=model,
        api_key="ollama",  # Ollama no requiere API key
        base_url=f"{OLLAMA_BASE_URL}/v1",  # API compatible con OpenAI
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ═══════════════════════════════════════════════════════════════
# Supabase
# ═══════════════════════════════════════════════════════════════
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# ═══════════════════════════════════════════════════════════════
# Constantes del grafo
# ═══════════════════════════════════════════════════════════════
MAX_ITERATIONS = 10
AUDITOR_TRIGGER_ITERATION = 3
TEMPERATURE_DEFAULT = 0.3
TEMPERATURE_CREATIVE = 0.5
AUDITOR_TEMPERATURE = 0.15
AUDITOR_MAX_TOKENS = 1024

# ═══════════════════════════════════════════════════════════════
# Output token budgets por nodo (Fase 1: Quick Wins)
# ═══════════════════════════════════════════════════════════════
TOKEN_BUDGET_ORCHESTRATOR = 512
TOKEN_BUDGET_ARCHITECT = 1024
TOKEN_BUDGET_PROGRAMMER = 4096
TOKEN_BUDGET_TESTER = 512
TOKEN_BUDGET_AUDITOR_G1 = 256
TOKEN_BUDGET_AUDITOR_G2 = 256
TOKEN_BUDGET_AUDITOR_G3 = 256
TOKEN_BUDGET_EXTRACTOR = 1024

# ═══════════════════════════════════════════════════════════════
# Limites de contexto por nodo (para trim) — V3 DINÁMICO
# ═══════════════════════════════════════════════════════════════
# Ya no usamos límites fijos. Cada nodo ve el 50-80% del requirement real
# dependiendo de su criticidad. La función get_dynamic_limit() calcula
# el límite óptimo basado en la longitud real del requirement.
MAX_REQUIREMENT_LENGTH = 300       # Legacy — ahora se usa get_dynamic_limit()
MAX_MEMORY_LENGTH = 500            # Aumentado: más contexto de memoria
MAX_RULES_COUNT = 8                # Más reglas visibles
MAX_SCRATCHPAD_ENTRIES = 8         # Más entradas de scratchpad
MAX_BLUEPRINT_DEPTH = 3            # Más profundidad del blueprint


def get_dynamic_limit(requirement: str, ratio: float = 0.6, min_val: int = 300, max_val: int = 4000) -> int:
    """Calcula el límite de contexto dinámico basado en la longitud del requirement.
    
    Fórmula: max(min_val, min(len(requirement) * ratio, max_val))
    
    Args:
        requirement: El requirement original
        ratio: Fracción del requirement a mostrar (0.0-1.0)
        min_val: Mínimo absoluto de caracteres
        max_val: Máximo absoluto de caracteres
    
    Ejemplos:
        req de 100 chars  → 300 (mínimo)
        req de 800 chars  → 480 (80% * 0.6)
        req de 2000 chars → 1200 (60%)
        req de 10000 chars → 4000 (máximo)
    """
    length = len(requirement) if requirement else 0
    dynamic = int(length * ratio)
    return max(min_val, min(dynamic, max_val))


def get_dynamic_memory_limit(memory: str, ratio: float = 0.5, max_val: int = 2000) -> int:
    """Límite dinámico para retrieved_memory."""
    length = len(memory) if memory else 0
    dynamic = int(length * ratio)
    return min(dynamic, max_val) if dynamic > 0 else 0

# ═══════════════════════════════════════════════════════════════
# Budgets por defecto (compatibilidad con imports existentes)
# ═══════════════════════════════════════════════════════════════
TOKEN_BUDGETS_DEFAULT = {
    "orchestrator": 512,
    "architect": 1024,
    "programmer": 4096,
    "tester": 512,
    "extractor": 1024,
}

TOKEN_BUDGET_ORCHESTRATOR = 512
TOKEN_BUDGET_ARCHITECT = 1024
TOKEN_BUDGET_PROGRAMMER = 4096
TOKEN_BUDGET_TESTER = 512
TOKEN_BUDGET_AUDITOR_G1 = 256
TOKEN_BUDGET_AUDITOR_G2 = 256
TOKEN_BUDGET_AUDITOR_G3 = 256
TOKEN_BUDGET_EXTRACTOR = 1024

# ═══════════════════════════════════════════════════════════════
# Token budgets por nivel de complejidad (Fase 3)
# ═══════════════════════════════════════════════════════════════
COMPLEXITY_BUDGETS = {
    "low": {
        "description": "Tareas simples: 1-2 archivos, funciones basicas",
        "max_total_tokens": 3000,
        "use_pro": False,           # Sin llamadas Pro
        "max_iterations": 2,
        "skip_gate_1": False,       # Gate 1 es barato, siempre
        "skip_gate_2": True,        # Saltar Gate 2
        "skip_gate_3": True,        # Saltar Gate 3 (pro)
        "budgets": {
            "orchestrator": 256,
            "architect": 512,
            "programmer": 2048,
            "tester": 256,
            "extractor": 512,
        },
    },
    "medium": {
        "description": "Tareas normales: 2-4 archivos, logica moderada",
        "max_total_tokens": 8000,
        "use_pro": True,            # Usar Pro para auditor gates
        "max_iterations": 5,
        "skip_gate_1": False,
        "skip_gate_2": False,       # Gate 2 condicional (por blueprint)
        "skip_gate_3": False,
        "budgets": TOKEN_BUDGETS_DEFAULT,  # Hereda budgets de Fase 1
    },
    "high": {
        "description": "Tareas complejas: 5+ archivos, logica avanzada",
        "max_total_tokens": 30000,
        "use_pro": True,
        "max_iterations": 15,       # Más iteraciones para tareas complejas
        "hard_cap_iterations": 20,   # Hard cap ABSOLUTO (nunca pasar de aquí)
        "skip_gate_1": False,
        "skip_gate_2": False,
        "skip_gate_3": False,
        "budgets": {
            "orchestrator": 1024,
            "architect": 2048,
            "programmer": 8192,
            "tester": 1024,
            "extractor": 2048,
        },
    },
}

# Globo de complejidad actual (actualizado por detect_complexity)
_current_complexity = "medium"

# ═══════════════════════════════════════════════════════════════
# Estado de fallback (3 niveles)
# ═══════════════════════════════════════════════════════════════
_fallback_level = 0   # 0=reina free, 1=rzuluam free, 2=reina go, 3=sin opciones
_fallback_model = None

FALLBACK_NAMES = ["reinaagenciacol (Zen)", "rzuluam (Zen)", "reinaagenciacol (Go)", "SIN OPCIONES"]

FALLBACK_REASONS = {
    "rate_limit": "Rate limit del plan Zen agotado.",
    "no_credits": "Sin créditos en el plan. Recargar en https://opencode.ai/workspace/wrk_01KT1ZE6364E329FDASNEGMH22/billing",
    "switch": "Cambiando a cuenta alternativa para mantener operación gratuita...",
    "go": "Ambas cuentas Zen agotadas. Cambiando a plan Go (pago).",
}


def _make_llm(model: str, temperature: float, max_tokens: int, 
              base_url: str = None, api_key: str = None) -> ChatOpenAI:
    """Factory interna de clientes LLM.
    
    Args:
        model: Nombre del modelo
        temperature: Temperatura
        max_tokens: Máximo de tokens de salida
        base_url: URL base (None = Zen endpoint)
        api_key: API key (None = usa la key del nivel actual)
    """
    url = base_url or OPENCODE_ZEN_BASE_URL
    key = api_key or _get_current_key()
    return ChatOpenAI(
        model=model,
        api_key=key,
        base_url=url,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _get_current_key() -> str:
    """Devuelve la API key del nivel de fallback actual."""
    if _fallback_level < len(FALLBACK_KEYS):
        return FALLBACK_KEYS[_fallback_level]["key"]
    return OPENCODE_API_KEY  # fallback seguro


def _get_current_url() -> str:
    """Devuelve la URL base del nivel de fallback actual.
    
    Nivel 0 y 1: Zen endpoint (free)
    Nivel 2: Go endpoint (pago)
    """
    if _fallback_level >= 2:
        return OPENCODE_GO_BASE_URL
    return OPENCODE_ZEN_BASE_URL


def get_current_flash_model() -> str:
    """Devuelve el modelo flash activo según nivel de fallback."""
    if _fallback_level >= 2:
        return OPENCODE_MODEL_PAID  # deepseek-v4-flash (Go)
    return OPENCODE_MODEL_FREE      # deepseek-v4-flash-free (Zen)


def is_fallback_active() -> bool:
    """True si estamos en algún nivel de fallback."""
    return _fallback_level > 0


def get_fallback_level() -> int:
    """Devuelve el nivel actual de fallback (0-3)."""
    return _fallback_level


def get_fallback_name() -> str:
    """Devuelve el nombre del nivel actual."""
    return FALLBACK_NAMES[_fallback_level] if _fallback_level < len(FALLBACK_NAMES) else "DESCONOCIDO"


def activate_fallback(current_status: int = 429):
    """Avanza al siguiente nivel de fallback.
    
    Flujo:
      0 (reina free)  → 1 (rzuluam free) si 429
      1 (rzuluam free) → 2 (reina go) si 429
      2 (reina go)    → 3 (sin opciones) si 429
    
    Args:
        current_status: Código de error HTTP (429, 401, 402)
    """
    global _fallback_level
    
    if current_status == 429:
        if _fallback_level == 0:
            _fallback_level = 1
            print(f"\n⚠️  {FALLBACK_REASONS['rate_limit']} {FALLBACK_REASONS['switch']}")
            print(f"   → Nueva cuenta: rzuluam (Zen, free)")
            print(f"   Modelo: {OPENCODE_MODEL_FREE}\n")
        elif _fallback_level == 1:
            _fallback_level = 2
            print(f"\n⚠️  {FALLBACK_REASONS['rate_limit']} {FALLBACK_REASONS['go']}")
            print(f"   → Cuenta: reinaagenciacol (Go, pago)")
            print(f"   Modelo: {OPENCODE_MODEL_PAID}\n")
        elif _fallback_level == 2:
            _fallback_level = 3
            print(f"\n❌ Todas las cuentas agotadas (reina Zen, rzuluam Zen, reina Go).")
            print(f"   {FALLBACK_REASONS['no_credits']}\n")
    
    elif current_status in (401, 402):
        if _fallback_level < 2:
            _fallback_level = min(_fallback_level + 1, 3)
            print(f"\n⚠️  Sin créditos en {FALLBACK_NAMES[_fallback_level-1]}. {FALLBACK_REASONS['switch']}")
        else:
            _fallback_level = 3
            print(f"\n❌ {FALLBACK_REASONS['no_credits']}\n")


def reset_fallback():
    """Reinicia al nivel 0 (reina Zen free). Se llama al inicio de cada pipeline."""
    global _fallback_level
    _fallback_level = 0


async def precheck_free_model() -> bool:
    """Prueba el modelo free en TODAS las cuentas disponibles.
    
    Estrategia:
      1. Prueba reinaagenciacol (Zen) — si ok, listo
      2. Si 429, prueba rzuluam (Zen) — si ok, listo
      3. Si 429, activa Go (pago)
      4. Si 429 en Go, error fatal
    
    Returns: True si hay algún modelo disponible, False si todos fallaron.
    """
    global _fallback_level
    
    if _fallback_level >= 3:
        return False
    
    # Probar cada nivel hasta encontrar uno que funcione
    while _fallback_level < 3:
        level_name = FALLBACK_NAMES[_fallback_level]
        model = get_current_flash_model()
        base_url = _get_current_url()
        api_key = _get_current_key()
        
        print(f"[Precheck] Probando {level_name}... ", end="")
        try:
            test_llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=0.3,
                max_tokens=10,
            )
            await test_llm.ainvoke([
                {"role": "system", "content": "Responde SOLO: ok"},
                {"role": "user", "content": "test"},
            ])
            print(f"✅ Disponible")
            print(f"[Precheck] Usando: {level_name} | {model} | {base_url}")
            return True
            
        except Exception as e:
            status_code = getattr(e, 'status_code', None) or getattr(e, 'status', None)
            
            if status_code == 429:
                print(f"❌ Rate limited")
                activate_fallback(429)
                # Continuar al siguiente nivel
            elif status_code in (401, 402):
                print(f"❌ Sin créditos")
                activate_fallback(status_code)
            else:
                print(f"⚠️  Error: {str(e)[:60]}")
                # Error no relacionado con rate limit, intentar siguiente nivel
                if _fallback_level < 2:
                    _fallback_level += 1
                else:
                    return False
    
    return False  # Todos los niveles fallaron


# ═══════════════════════════════════════════════════════════════
# Detección de complejidad y presupuesto dinámico (Fase 3)
# ═══════════════════════════════════════════════════════════════

def detect_complexity(requirement: str) -> str:
    """Detecta el nivel de complejidad de un requerimiento.
    
    Retorna: "low", "medium", o "high"
    """
    req_lower = requirement.lower()
    words = req_lower.split()
    word_count = len(words)
    
    # Indicadores de complejidad alta
    high_indicators = [
        "api", "rest", "database", "flask", "django", "multi", "pipeline",
        "servidor", "async", "concurrent", "thread", "socket", "websocket",
        "autenticación", "login", "oauth", "jwt", "criptografía",
        "5 archivos", "6 archivos", "7 archivos", "10",
        "complejo", "compleja", "microservicios", "distribuido",
    ]
    
    # Indicadores de complejidad baja
    low_indicators = [
        "una función que sume", "funcion simple", "1 solo archivo",
        "una unica funcion", "filter_valid", "suma y resta",
        "escribe hola mundo", "imprimir hola",
    ]

    # Indicadores de complejidad media
    medium_indicators = [
        "script", "cli", "csv", "json", "archivo", "procese",
        "validar", "filtrar", "convertir", "parser",
    ]

    high_score = sum(1 for ind in high_indicators if ind in req_lower)
    low_score = sum(1 for ind in low_indicators if ind in req_lower)
    medium_score = sum(1 for ind in medium_indicators if ind in req_lower)

    # Regla de decisión
    if high_score >= 2 or (high_score >= 1 and word_count > 50):
        return "high"
    elif low_score >= 1:
        return "low"
    elif medium_score >= 1 or word_count >= 10:
        return "medium"
    else:
        return "low"


def get_current_complexity() -> str:
    """Devuelve el nivel de complejidad actual."""
    return _current_complexity


def set_complexity(level: str):
    """Establece el nivel de complejidad para esta ejecución."""
    global _current_complexity
    if level in COMPLEXITY_BUDGETS:
        _current_complexity = level
        print(f"[Complejidad] Nivel: {level} — {COMPLEXITY_BUDGETS[level]['description']}")


def get_budget(key: str) -> int:
    """Obtiene el presupuesto de tokens para un nodo según complejidad.
    
    Fase 5: Aplica el multiplicador de tuning (auto-ajuste).
    """
    budgets = COMPLEXITY_BUDGETS.get(_current_complexity, COMPLEXITY_BUDGETS["medium"])
    node_budgets = budgets.get("budgets", TOKEN_BUDGETS_DEFAULT)
    base = node_budgets.get(key, TOKEN_BUDGETS_DEFAULT.get(key, 512))

    # Aplicar multiplicador de tuning si existe
    try:
        tuning_file = Path.home() / ".agents" / "enjambre_tuning.json"
        if tuning_file.exists():
            with open(tuning_file) as f:
                tuning = json.load(f)
            mult_key = f"budget_multiplier_{_current_complexity}"
            mult = tuning.get(mult_key, 1.0)
            if mult != 1.0:
                base = int(base * mult)
    except (json.JSONDecodeError, OSError, ImportError):
        pass

    return base


def get_max_total_tokens() -> int:
    """Obtiene el límite total de tokens según complejidad."""
    return COMPLEXITY_BUDGETS.get(_current_complexity, COMPLEXITY_BUDGETS["medium"]).get("max_total_tokens", 8000)


def should_skip_gate(gate_number: int) -> bool:
    """Determina si un gate debe saltarse según la complejidad."""
    budgets = COMPLEXITY_BUDGETS.get(_current_complexity, COMPLEXITY_BUDGETS["medium"])
    key = f"skip_gate_{gate_number}"
    return budgets.get(key, False)


def get_max_iterations() -> int:
    """Obtiene el máximo de iteraciones según complejidad."""
    return COMPLEXITY_BUDGETS.get(_current_complexity, COMPLEXITY_BUDGETS["medium"]).get("max_iterations", 5)


def get_hard_cap_iterations() -> int:
    """Obtiene el hard cap ABSOLUTO de iteraciones.
    
    A diferencia de max_iterations (que puede variar por escalamiento),
    este es un límite duro que nunca se excede.
    """
    return COMPLEXITY_BUDGETS.get(_current_complexity, COMPLEXITY_BUDGETS["medium"]).get("hard_cap_iterations", 25)


def get_llm(temperature: float = TEMPERATURE_DEFAULT, max_tokens: int = None) -> ChatOpenAI:
    """Cliente LLM para los 6 nodos flash del pipeline.
    
    Usa el modelo y API key según el nivel de fallback actual:
      Nivel 0: deepseek-v4-flash-free · reinaagenciacol (Zen)
      Nivel 1: deepseek-v4-flash-free · rzuluam (Zen)
      Nivel 2: deepseek-v4-flash · reinaagenciacol (Go)
    
    Args:
        temperature: Temperatura del modelo
        max_tokens: Máximo de tokens de salida
    """
    model = get_current_flash_model()
    base_url = _get_current_url()
    api_key = _get_current_key()
    mt = max_tokens or 16384
    
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=mt,
    )


def get_pro_llm(max_tokens: int = None) -> ChatOpenAI:
    """Cliente LLM para auditoría y micro-gates (Qwen3.7 Plus, Go pago).
    
    OPTIMIZACIÓN DE COSTOS (10 Jun 2026):
      Antes: deepseek-v4-pro ($1.74 in / $3.48 out)
      Ahora: qwen3.7-plus   ($0.40 in / $1.60 out) — 4.35x más barato
    
    Rendimiento comparable para tareas de validación/auditoría.
    Si se requiere la máxima precisión de deepseek-v4-pro, cambiar
    OPENCODE_PRO_MODEL en .env.
    
    Optimizado para:
    - Máximo cache hit: temperature=0.15, system prompt estático
    - Mínimo output: max_tokens configurable, solo JSON conciso
    """
    mt = max_tokens or AUDITOR_MAX_TOKENS
    return ChatOpenAI(
        model=OPENCODE_PRO_MODEL,
        api_key=OPENCODE_API_KEY,  # Siempre reinaagenciacol (Go)
        base_url=OPENCODE_GO_BASE_URL,
        temperature=AUDITOR_TEMPERATURE,
        max_tokens=mt,
    )


def get_router_llm(router, nodo: str, iteration: int = 0, errors: int = 0,
                   loop_detected: bool = False) -> ChatOpenAI:
    """Obtiene un LLM según la decisión del Model Router.
    
    El router decide si usar flash (gratis) o pro (pago).
    Si es flash, usa el nivel de fallback actual (0, 1, o 2).
    Si es pro, siempre usa reinaagenciacol Go.
    """
    model_type, temperature, max_tokens = router.get_llm_for_node(
        nodo, iteration, errors, loop_detected
    )
    
    if model_type == "pro":
        return get_pro_llm(max_tokens=max_tokens)
    else:
        return get_llm(temperature=temperature, max_tokens=max_tokens)


def handle_llm_error(status_code: int) -> bool:
    """Procesa un error de la API y avanza al siguiente nivel de fallback.
    
    Args:
        status_code: Código de error HTTP
    
    Returns:
        True si hay un nivel de fallback disponible, False si se agotaron.
    """
    global _fallback_level
    
    if status_code == 429:
        if _fallback_level < 2:
            activate_fallback(429)
            return True
        else:
            print(f"❌ Todas las cuentas agotadas (reina Zen, rzuluam Zen, reina Go).")
            return False
    elif status_code in (401, 402):
        if _fallback_level < 2:
            activate_fallback(status_code)
            return True
        else:
            print(f"❌ {FALLBACK_REASONS['no_credits']}")
            return False
    return False


async def safe_invoke(llm, messages, node_name: str = ""):
    """Invoca el LLM con retry automático en caso de rate limit (429).
    
    Flujo de retry:
      1. Si 429 en reina Zen → retry con rzuluam Zen
      2. Si 429 en rzuluam Zen → retry con reina Go
      3. Si 429 en reina Go → error fatal
      4. Si 401/402 en cualquier nivel → avanza al siguiente
    """
    prefix = f"[{node_name}] " if node_name else ""

    try:
        return await llm.ainvoke(messages)
    except Exception as e:
        status_code = getattr(e, 'status_code', None) or getattr(e, 'status', None)

        if status_code in (429, 401, 402):
            level_before = _fallback_level
            has_fallback = handle_llm_error(status_code)
            
            if has_fallback:
                level_name = FALLBACK_NAMES[_fallback_level]
                model = get_current_flash_model()
                print(f"{prefix}⚠️  Fallback → {level_name} ({model})")
                new_llm = get_llm()
                return await new_llm.ainvoke(messages)
            else:
                print(f"{prefix}❌ Sin opciones de fallback disponibles.")
        
        raise
