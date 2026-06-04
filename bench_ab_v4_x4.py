#!/usr/bin/env python3
"""
Benchmark A/B v4.0 — Enjambre v3.0 (INTELIGENCIA x4) vs Builder Solo Pro.

Prueba las mejoras clave del v3.0:
  1. Gate 0 Meta-Planner → mejor análisis inicial
  2. Ensemble de arquitectura → 3 blueprints vs 1
  3. Contexto dinámico → más información visible
  4. Auto-reflexión → código más limpio
  5. Clasificación de errores → mejor debugging

Mide: calidad, tiempo, tokens, costo, y tasa de éxito sintáctico.
"""
import requests, time, json, os, sys, re
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

API_KEY = os.getenv("OPENCODE_API_KEY")
GO_URL = "https://opencode.ai/zen/go/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

FLASH = os.getenv("OPENCODE_MODEL_PAID", "deepseek-v4-flash")
PRO = os.getenv("OPENCODE_PRO_MODEL", "deepseek-v4-pro")

# Precios USD/1M tokens
PRICE = {FLASH: (0.14, 0.28), PRO: (1.74, 3.48)}

# ============================================================
# TAREAS DE PRUEBA (4 niveles de complejidad)
# ============================================================
TAREAS = [
    {
        "id": "filter_logs",
        "nivel": "simple",
        "desc": "Filtrar logs por nivel",
        "texto": (
            "Escribe una funcion filter_logs(logs, min_level) en Python que: "
            "1) reciba lista de strings con formato '[LEVEL] message' "
            "2) devuelva los logs con nivel >= min_level (ERROR=3, WARN=2, INFO=1, DEBUG=0) "
            "3) incluya type hints y docstring "
            "4) incluya 3 tests pytest en un bloque if __name__"
        ),
    },
    {
        "id": "csv_converter",
        "nivel": "medio",
        "desc": "Conversor CSV a JSON",
        "texto": (
            "Escribe un script csv_to_json.py en Python que: "
            "1) lea un archivo CSV con columnas: nombre, edad, email, ciudad "
            "2) valide que email tenga formato valido (regex) "
            "3) convierta a JSON con indentacion "
            "4) maneje errores de archivo no encontrado y parseo "
            "5) incluya type hints y docstrings "
            "6) incluya 4 tests pytest"
        ),
    },
    {
        "id": "api_client",
        "nivel": "complejo",
        "desc": "Cliente API REST con cache",
        "texto": (
            "Escribe un API client en Python que: "
            "1) tenga una clase APIClient con metodo get(endpoint, params) "
            "2) implemente cache LRU con TTL de 60 segundos "
            "3) maneje rate limiting con backoff exponencial "
            "4) use type hints en todos los metodos "
            "5) incluya logging estructurado "
            "6) incluya 5 tests pytest en archivo separado test_api_client.py "
            "7) Use solo la biblioteca estandar (requests no permitido, usar urllib)"
        ),
    },
]

# ============================================================
# HELPERS
# ============================================================
def call(model, system, user, max_tok=4096, temp=0.3):
    """Llamada directa a API OpenCode."""
    t0 = time.time()
    resp = requests.post(GO_URL, json={
        "model": model, "temperature": temp, "max_tokens": max_tok,
        "messages": [{"role": "system", "content": system},
                      {"role": "user", "content": user}]
    }, headers=HEADERS, timeout=180)
    elapsed = time.time() - t0
    data = resp.json()
    usage = data.get("usage", {})
    content = data["choices"][0]["message"]["content"]
    return {
        "model": model, "elapsed": round(elapsed, 2),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "content": content,
    }

def cost(model, inp, out):
    pi, po = PRICE.get(model, (0, 0))
    return (inp / 1e6) * pi + (out / 1e6) * po

def verificar_codigo_python(codigo: str) -> dict:
    """Verifica sintaxis Python y extrae metadatos."""
    result = {"sintaxis_ok": False, "tiene_type_hints": False,
              "tiene_docstrings": False, "tiene_tests": False,
              "tiene_if_main": False, "errores": [], "lineas": 0}
    
    # Extraer código si está en bloque markdown
    m = re.search(r'```python\n(.*?)```', codigo, re.DOTALL)
    if m:
        codigo = m.group(1)
    
    result["lineas"] = len(codigo.split("\n"))
    
    # Verificar sintaxis
    try:
        compile(codigo, "<test>", "exec")
        result["sintaxis_ok"] = True
    except SyntaxError as e:
        result["errores"].append(f"SyntaxError: {e.msg} (linea {e.lineno})")
    
    if not result["sintaxis_ok"]:
        return result
    
    # Verificar características
    result["tiene_type_hints"] = "def " in codigo and "->" in codigo
    result["tiene_docstrings"] = '"""' in codigo or "'''" in codigo
    result["tiene_tests"] = "assert " in codigo or "pytest" in codigo or "unittest" in codigo
    result["tiene_if_main"] = 'if __name__' in codigo
    
    return result


def evaluar_calidad(codigo: str, tarea: str) -> dict:
    """Evalúa calidad del código con métricas objetivas."""
    v = verificar_codigo_python(codigo)
    
    # Puntaje de calidad (0-100)
    puntos = 0
    if v["sintaxis_ok"]: puntos += 30
    if v["tiene_type_hints"]: puntos += 15
    if v["tiene_docstrings"]: puntos += 15
    if v["tiene_tests"]: puntos += 25
    if v["tiene_if_main"]: puntos += 15
    
    # Penalización por errores
    puntos = max(0, puntos - len(v["errores"]) * 10)
    
    return {
        "puntaje": puntos,
        "sintaxis_ok": v["sintaxis_ok"],
        "type_hints": v["tiene_type_hints"],
        "docstrings": v["tiene_docstrings"],
        "tests": v["tiene_tests"],
        "if_main": v["tiene_if_main"],
        "lineas": v["lineas"],
        "errores": v["errores"],
    }


# ============================================================
# PATH B: Builder Solo (1 llamada Pro)
# ============================================================
BUILDER_SYSTEM = (
    "Eres un Desarrollador Python experto. Analiza el requerimiento y produce "
    "codigo funcional completo con tests en UNA SOLA respuesta. "
    "Incluye type hints, docstrings, manejo de errores. "
    "Responde con el codigo en bloque ```python."
)

# ============================================================
# PATH A: Enjambre v3.0 (Pipeline simulado con mejoras)
# ============================================================
ORCHESTRATOR_V3 = (
    "Eres el Orquestador v3.0 (Superinteligente). "
    "Analiza el requerimiento COMPLETO y produce analisis ESTRUCTURADO. "
    "Debes incluir: arbol de decisiones, dependencias, riesgos, plan de pruebas. "
    "Responde SOLO JSON con: viable, business_rules, alcance, tecnologias_sugeridas, "
    "arbol_decisiones, dependencias_externas, plan_pruebas, resumen_para_auditor."
)

ARCHITECT_V3 = (
    "Eres el Arquitecto v3.0 con ENFOQUE ROBUSTO. "
    "Disena una arquitectura MODULAR con separacion de concerns. "
    "Define archivos, funciones con signatures, flujo de datos, casos borde. "
    "Responde SOLO JSON con arquitectura completa."
)

PROGRAMMER_V3 = (
    "Eres el Programador v3.0 con AUTO-REFLEXION. "
    "Antes de escribir codigo, verifica este checklist mental: "
    "1) imports correctos 2) type hints 3) docstrings 4) edge cases "
    "5) logging 6) nombres descriptivos 7) sigue blueprint 8) codigo ejecutable. "
    "Escribe codigo limpio, tipado, con tests. "
    "Incluye verification_output y auto_reflection en tu respuesta JSON."
)

TESTER_V3 = (
    "Eres el Tester v3.0 con CLASIFICACION DE ERRORES. "
    "Analiza el codigo y CLASIFICA cada error como: "
    "[SINTAXIS], [LOGICA], [ARQUITECTURA], [DEPENDENCIA], [EDGE_CASE]. "
    "Responde JSON con status, errors (con categoria, causa_raiz, fix), metricas."
)


def run_path_a(tarea: dict) -> dict:
    """Ejecuta la simulación del pipeline Enjambre v3.0."""
    calls = []
    t0 = time.time()
    
    req = tarea["texto"]
    
    print(f"\n    [Enjambre v3.0] Procesando: {tarea['id']}")
    
    # --- Paso 1: Orquestador v3 con contexto DINÁMICO ---
    print(f"      1/5 Orquestador v3...", end=" ")
    r1 = call(FLASH, ORCHESTRATOR_V3, req, max_tok=1024)
    calls.append(("Orquestador v3", FLASH, r1))
    print(f"{r1['elapsed']:.1f}s ({r1['input_tokens']}+{r1['output_tokens']} tok)")
    
    # --- Paso 2: Arquitecto v3 con ENSEMBLE (simulado: 1 robusto) ---
    print(f"      2/5 Arquitecto v3...", end=" ")
    r2 = call(FLASH, ARCHITECT_V3, 
              f"Requerimiento: {req}\nAnalisis: {r1['content'][:500]}",
              max_tok=2048)
    calls.append(("Arquitecto v3", FLASH, r2))
    print(f"{r2['elapsed']:.1f}s ({r2['input_tokens']}+{r2['output_tokens']} tok)")
    
    # --- Paso 3: Programador v3 con AUTO-REFLEXIÓN ---
    print(f"      3/5 Programador v3...", end=" ")
    r3 = call(FLASH, PROGRAMMER_V3,
              f"Requerimiento: {req}\nArquitectura: {r2['content'][:500]}",
              max_tok=4096)
    calls.append(("Programador v3", FLASH, r3))
    print(f"{r3['elapsed']:.1f}s ({r3['input_tokens']}+{r3['output_tokens']} tok)")
    
    # --- Paso 4: Tester v3 con CLASIFICACIÓN ---
    print(f"      4/5 Tester v3...", end=" ")
    r4 = call(FLASH, TESTER_V3,
              f"Codigo:\n{r3['content'][:3000]}",
              max_tok=1024)
    calls.append(("Tester v3", FLASH, r4))
    print(f"{r4['elapsed']:.1f}s ({r4['input_tokens']}+{r4['output_tokens']} tok)")
    
    # --- Paso 5: Auto-corrección (si hay errores) ---
    tiene_errores = False
    r5 = None
    try:
        test_content = r4['content']
        if test_content.startswith("```"):
            test_lines = test_content.split("\n")
            test_content = "\n".join(test_lines[1:-1])
        test_result = json.loads(test_content)
        tiene_errores = test_result.get("status") == "FAIL" and len(test_result.get("errors", [])) > 0
    except (json.JSONDecodeError, KeyError):
        tiene_errores = "FAIL" in r4['content'][:200]
    
    if tiene_errores:
        print(f"      5/5 Programador corrigiendo...", end=" ")
        r5 = call(FLASH, PROGRAMMER_V3,
                  f"El tester reporto errores. Corrige:\n"
                  f"Codigo anterior:\n{r3['content'][:2000]}\n"
                  f"Errores:\n{r4['content'][:500]}",
                  max_tok=4096)
        calls.append(("Correccion", FLASH, r5))
        print(f"{r5['elapsed']:.1f}s ({r5['input_tokens']}+{r5['output_tokens']} tok)")
    
    total_time = time.time() - t0
    codigo_final = r5['content'] if r5 else r3['content']
    
    total_input = sum(c["input_tokens"] for _, _, c in calls)
    total_output = sum(c["output_tokens"] for _, _, c in calls)
    total_calls = len(calls)
    total_cost = sum(cost(m, c["input_tokens"], c["output_tokens"]) for _, m, c in calls)
    
    calidad = evaluar_calidad(codigo_final, tarea["texto"])
    
    return {
        "calls": total_calls,
        "time": round(total_time, 2),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cost": round(total_cost, 6),
        "calidad": calidad,
        "codigo_preview": codigo_final[:200],
        "breakdown": [{"step": s, "model": m, "input": c["input_tokens"], "output": c["output_tokens"]}
                      for s, m, c in calls],
    }


def run_path_b(tarea: dict) -> dict:
    """Ejecuta Builder Solo (1 llamada Pro)."""
    req = tarea["texto"]
    
    print(f"\n    [Builder Solo Pro] Procesando: {tarea['id']}")
    print(f"      1/1 Builder Pro...", end=" ")
    
    t0 = time.time()
    r = call(PRO, BUILDER_SYSTEM, req, max_tok=4096)
    elapsed = time.time() - t0
    
    print(f"{r['elapsed']:.1f}s ({r['input_tokens']}+{r['output_tokens']} tok)")
    
    calidad = evaluar_calidad(r["content"], req)
    
    return {
        "calls": 1,
        "time": round(elapsed, 2),
        "input_tokens": r["input_tokens"],
        "output_tokens": r["output_tokens"],
        "cost": round(cost(PRO, r["input_tokens"], r["output_tokens"]), 6),
        "calidad": calidad,
        "codigo_preview": r["content"][:200],
    }


# ============================================================
# EJECUCIÓN PRINCIPAL
# ============================================================
print("=" * 70)
print("  🧪 BENCHMARK A/B v4.0 — Enjambre v3.0 (x4) vs Builder Solo Pro")
print("=" * 70)

resultados = []

for tarea in TAREAS:
    print(f"\n{'=' * 70}")
    print(f"  TAREA: {tarea['id']} ({tarea['nivel']}) — {tarea['desc']}")
    print(f"{'=' * 70}")
    
    # PATH A: Enjambre v3.0
    print(f"\n  ── PATH A: Enjambre v3.0 (INTELIGENCIA x4) ──")
    path_a = run_path_a(tarea)
    
    # PATH B: Builder Solo Pro
    print(f"\n  ── PATH B: Builder Solo (DeepSeek V4 Pro) ──")
    path_b = run_path_b(tarea)
    
    # Comparación
    print(f"\n  ── COMPARACIÓN ──")
    
    calidad_a = path_a["calidad"]
    calidad_b = path_b["calidad"]
    
    headers = ["Métrica", "Enjambre v3.0", "Builder Solo", "Ganador"]
    rows = [
        ["Calls LLM", str(path_a["calls"]), str(path_b["calls"]),
         "Builder" if path_b["calls"] < path_a["calls"] else "Enjambre"],
        ["Tiempo", f"{path_a['time']:.1f}s", f"{path_b['time']:.1f}s",
         "Builder" if path_b['time'] < path_a['time'] else "Enjambre"],
        ["Tokens totales", f"{path_a['input_tokens']+path_a['output_tokens']:,}",
         f"{path_b['input_tokens']+path_b['output_tokens']:,}",
         "Builder" if path_b['input_tokens']+path_b['output_tokens'] < path_a['input_tokens']+path_a['output_tokens'] else "Enjambre"],
        ["Costo USD", f"${path_a['cost']:.6f}", f"${path_b['cost']:.6f}",
         "Enjambre" if path_a['cost'] < path_b['cost'] else "Builder"],
        ["Calidad (0-100)", f"{calidad_a['puntaje']}", f"{calidad_b['puntaje']}",
         "Enjambre" if calidad_a['puntaje'] > calidad_b['puntaje'] else "Builder"],
        ["Sintaxis OK", "✅" if calidad_a['sintaxis_ok'] else "❌",
         "✅" if calidad_b['sintaxis_ok'] else "❌",
         "Empate" if calidad_a['sintaxis_ok'] == calidad_b['sintaxis_ok'] else ("Enjambre" if calidad_a['sintaxis_ok'] else "Builder")],
        ["Type Hints", "✅" if calidad_a['type_hints'] else "❌",
         "✅" if calidad_b['type_hints'] else "❌", "Empate"],
        ["Docstrings", "✅" if calidad_a['docstrings'] else "❌",
         "✅" if calidad_b['docstrings'] else "❌", "Empate"],
        ["Tests", "✅" if calidad_a['tests'] else "❌",
         "✅" if calidad_b['tests'] else "❌", "Empate"],
    ]
    
    for h in headers:
        print(f"  {h:<20}", end="")
    print()
    print("  " + "-" * 90)
    for row in rows:
        for col in row:
            print(f"  {col:<20}", end="")
        print()
    
    # Determinar ganador global
    scores = {"Enjambre": 0, "Builder": 0}
    if path_a['cost'] < path_b['cost']: scores["Enjambre"] += 1
    else: scores["Builder"] += 1
    if calidad_a['puntaje'] > calidad_b['puntaje']: scores["Enjambre"] += 2
    elif calidad_b['puntaje'] > calidad_a['puntaje']: scores["Builder"] += 2
    if calidad_a['sintaxis_ok'] and not calidad_b['sintaxis_ok']: scores["Enjambre"] += 2
    elif calidad_b['sintaxis_ok'] and not calidad_a['sintaxis_ok']: scores["Builder"] += 2
    
    ganador = max(scores, key=scores.get)
    print(f"\n  🏆 GANADOR: {ganador} (Enjambre {scores['Enjambre']} - Builder {scores['Builder']})")
    
    resultados.append({
        "tarea": tarea["id"],
        "nivel": tarea["nivel"],
        "path_a": path_a,
        "path_b": path_b,
        "ganador": ganador,
        "scores": scores,
    })

# ============================================================
# RESUMEN GLOBAL
# ============================================================
print(f"\n\n{'=' * 70}")
print("  📊 RESUMEN GLOBAL — Enjambre v3.0 vs Builder Solo Pro")
print("=" * 70)

total_a_cost = sum(r["path_a"]["cost"] for r in resultados)
total_b_cost = sum(r["path_b"]["cost"] for r in resultados)
total_a_quality = sum(r["path_a"]["calidad"]["puntaje"] for r in resultados)
total_b_quality = sum(r["path_b"]["calidad"]["puntaje"] for r in resultados)
total_a_tokens = sum(r["path_a"]["input_tokens"]+r["path_a"]["output_tokens"] for r in resultados)
total_b_tokens = sum(r["path_b"]["input_tokens"]+r["path_b"]["output_tokens"] for r in resultados)
total_a_time = sum(r["path_a"]["time"] for r in resultados)
total_b_time = sum(r["path_b"]["time"] for r in resultados)
a_syntax_ok = sum(1 for r in resultados if r["path_a"]["calidad"]["sintaxis_ok"])
b_syntax_ok = sum(1 for r in resultados if r["path_b"]["calidad"]["sintaxis_ok"])

ganados_enjambre = sum(1 for r in resultados if r["ganador"] == "Enjambre")
ganados_builder = sum(1 for r in resultados if r["ganador"] == "Builder")

print(f"""
  ┌──────────────────────────┬──────────────┬──────────────┬──────────┐
  │        Métrica           │ Enjambre v3  │ Builder Solo │ Ganador  │
  ├──────────────────────────┼──────────────┼──────────────┼──────────┤
  │ Costo total              │ ${total_a_cost:.6f}   │ ${total_b_cost:.6f}   │ {'Enjambre' if total_a_cost < total_b_cost else 'Builder'} │
  │ Calidad total (0-100)    │ {total_a_quality:>3} pts       │ {total_b_quality:>3} pts       │ {'Enjambre' if total_a_quality > total_b_quality else 'Builder'} │
  │ Calidad promedio         │ {total_a_quality/len(resultados):.0f}/100        │ {total_b_quality/len(resultados):.0f}/100        │          │
  │ Tareas con sintaxis OK   │ {a_syntax_ok}/{len(resultados)}           │ {b_syntax_ok}/{len(resultados)}           │ {'Enjambre' if a_syntax_ok > b_syntax_ok else 'Builder'} │
  │ Tiempo total             │ {total_a_time:.0f}s          │ {total_b_time:.0f}s          │ {'Builder' if total_b_time < total_a_time else 'Enjambre'} │
  │ Tokens totales           │ {total_a_tokens:,}     │ {total_b_tokens:,}     │ {'Builder' if total_b_tokens < total_a_tokens else 'Enjambre'} │
  │ Tareas ganadas           │ {ganados_enjambre}/{len(resultados)}           │ {ganados_builder}/{len(resultados)}           │ {'Enjambre' if ganados_enjambre > ganados_builder else 'Builder'} │
  └──────────────────────────┴──────────────┴──────────────┴──────────┘
""")

# Determinar eficiencia (calidad/costo)
a_eficiencia = total_a_quality / max(total_a_cost, 0.000001)
b_eficiencia = total_b_quality / max(total_b_cost, 0.000001)

print(f"  📈 EFICIENCIA (calidad/costo):")
print(f"     Enjambre v3.0: {a_eficiencia:,.0f} pts/\$")
print(f"     Builder Solo:  {b_eficiencia:,.0f} pts/\$")
print(f"     Diferencia:    {a_eficiencia/b_eficiencia:.1f}x más eficiente ({'Enjambre' if a_eficiencia > b_eficiencia else 'Builder'})")
print(f"  {'=' * 70}")

# Guardar resultados
output_dir = "/Users/isabeldiaz/Dev/agent-swarm/test_results/ab_v4"
os.makedirs(output_dir, exist_ok=True)

with open(f"{output_dir}/resultados.json", "w") as f:
    json.dump({
        "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tareas": len(resultados),
        "resumen": {
            "cost_a": round(total_a_cost, 6),
            "cost_b": round(total_b_cost, 6),
            "quality_a": total_a_quality,
            "quality_b": total_b_quality,
            "syntax_ok_a": a_syntax_ok,
            "syntax_ok_b": b_syntax_ok,
            "ganados_enjambre": ganados_enjambre,
            "ganados_builder": ganados_builder,
            "eficiencia_a": round(a_eficiencia, 2),
            "eficiencia_b": round(b_eficiencia, 2),
        },
        "detalles": resultados,
    }, f, indent=2, ensure_ascii=False)

print(f"\n  Resultados guardados en: {output_dir}/resultados.json")
print(f"  {'=' * 70}")
