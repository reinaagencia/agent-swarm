#!/usr/bin/env python3
"""
Benchmark A/B simplificado: Enjambre-Dev vs Builder Solo.
LLamadas directas a la API OpenCode Go. Sin LangChain, sin dependencias.
"""
import requests, time, json, os, sys
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

API_KEY = os.getenv("OPENCODE_API_KEY")
GO_URL = "https://opencode.ai/zen/go/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

FLASH = os.getenv("OPENCODE_MODEL_PAID", "deepseek-v4-flash")
PRO = os.getenv("OPENCODE_PRO_MODEL", "deepseek-v4-pro")

# Tarea unica de benchmark (sencilla para comparacion limpia)
TASK = (
    "Escribe una funcion filter_valid(dicts, required_keys) en Python que: "
    "1) reciba lista de diccionarios y lista de claves requeridas "
    "2) devuelva solo los dicts que tengan TODAS las claves requeridas "
    "3) incluya type hints y docstring "
    "4) incluya 4 tests pytest en un bloque if __name__ == '__main__'"
)

def call(model, system, user, max_tok=4096):
    """Llamada directa a API. Retorna dict con tokens, tiempo, contenido."""
    t0 = time.time()
    resp = requests.post(GO_URL, json={
        "model": model, "temperature": 0.3, "max_tokens": max_tok,
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

# ═════════════════════════════════════════════════════════════
# PRICING (USD por 1M tokens)
# ═════════════════════════════════════════════════════════════
PRICE = {FLASH: (0.14, 0.28), PRO: (1.74, 3.48)}

def cost(model, inp, out):
    pi, po = PRICE.get(model, (0, 0))
    return (inp / 1e6) * pi + (out / 1e6) * po

# ═════════════════════════════════════════════════════════════
# PATH B: Builder Solo DSV4Pro (1 llamada)
# ═════════════════════════════════════════════════════════════
print("=" * 60)
print("  PATH B: Builder Solo (DSV4Pro, 1 llamada)")
print("=" * 60)

BUILDER_SYSTEM = (
    "Eres un Desarrollador Python experto. Analiza el requerimiento y produce "
    "codigo funcional completo con tests en una sola respuesta. Responde con "
    "estructura clara: analisis breve, codigo completo, tests."
)

t0b = time.time()
b = call(PRO, BUILDER_SYSTEM, TASK, max_tok=4096)
total_b = time.time() - t0b
cost_b = cost(PRO, b["input_tokens"], b["output_tokens"])

print(f"  Tiempo: {b['elapsed']:.1f}s")
print(f"  Tokens: input={b['input_tokens']} output={b['output_tokens']} total={b['input_tokens']+b['output_tokens']}")
print(f"  Costo: ${cost_b:.6f}")
print(f"  Llamadas LLM: 1")
print(f"  Codigo: {len(b['content'])} chars")
print(f"  Vista previa:\n{b['content'][:300]}...")

# ═════════════════════════════════════════════════════════════
# PATH A: Enjambre-Dev Pipeline (simulado con llamadas reales)
# ═════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("  PATH A: Simulacion Pipeline Enjambre-Dev")
print("=" * 60)

t0a = time.time()
calls = []

# --- Paso 1: Orquestador (flash) ---
print("\n  [1/7] Orquestador (flash)...")
orch_sys = (
    "Eres el Orquestador. Analiza el requerimiento y define restricciones. "
    "Responde JSON: {\"viable\": bool, \"business_rules\": [...], \"alcance\": \"...\"}"
)
r1 = call(FLASH, orch_sys, TASK, max_tok=1024)
calls.append(("Orquestador", FLASH, r1))
print(f"    {r1['elapsed']:.1f}s | tokens: {r1['input_tokens']}+{r1['output_tokens']}")

# --- Paso 2: Auditor Gate 1 (pro) ---
print("  [2/7] Auditor Gate 1 (pro)...")
audit1_sys = (
    "Eres el Auditor. Valida si el analisis del Orquestador es viable. "
    "Responde JSON: {\"approved\": bool, \"risk\": \"low\"|\"medium\"|\"high\", \"confidence\": float}"
)
r2 = call(PRO, audit1_sys,
    f"Requerimiento: {TASK[:200]}\nReglas: {r1['content'][:300]}", max_tok=512)
calls.append(("Auditor Gate 1", PRO, r2))
print(f"    {r2['elapsed']:.1f}s | tokens: {r2['input_tokens']}+{r2['output_tokens']}")

# --- Paso 3: Arquitecto (flash) ---
print("  [3/7] Arquitecto (flash)...")
arch_sys = (
    "Eres el Arquitecto de Software. Disena la estructura del codigo. "
    "Define archivos, funciones, flujo de datos. Responde JSON."
)
r3 = call(FLASH, arch_sys,
    f"Requerimiento: {TASK}\nReglas: {r1['content'][:300]}", max_tok=2048)
calls.append(("Arquitecto", FLASH, r3))
print(f"    {r3['elapsed']:.1f}s | tokens: {r3['input_tokens']}+{r3['output_tokens']}")

# --- Paso 4: Auditor Gate 2 (pro) ---
print("  [4/7] Auditor Gate 2 (pro)...")
audit2_sys = (
    "Eres el Auditor. Revisa el blueprint de arquitectura. "
    "Responde JSON: {\"approved\": bool, \"critical_flaws\": [...], \"improvements\": [...], \"confidence\": float}"
)
r4 = call(PRO, audit2_sys,
    f"Blueprint: {r3['content'][:500]}", max_tok=512)
calls.append(("Auditor Gate 2", PRO, r4))
print(f"    {r4['elapsed']:.1f}s | tokens: {r4['input_tokens']}+{r4['output_tokens']}")

# --- Paso 5: Programador (flash) ---
print("  [5/7] Programador (flash)...")
prog_sys = (
    "Eres un Programador Python experto. Escribe codigo limpio, tipado, con "
    "docstrings. Incluye tests. Solo responde con el codigo, sin explicaciones extra."
)
r5 = call(FLASH, prog_sys,
    f"Requerimiento: {TASK}\nArquitectura: {r3['content'][:500]}", max_tok=4096)
calls.append(("Programador", FLASH, r5))
print(f"    {r5['elapsed']:.1f}s | tokens: {r5['input_tokens']}+{r5['output_tokens']}")

# --- Paso 6: Tester (flash) ---
print("  [6/7] Tester (flash)...")
test_sys = (
    "Eres un QA. Analiza el codigo y reporta errores. "
    "Responde JSON: {\"status\": \"PASS\"|\"FAIL\", \"errors\": [...]}"
)
r6 = call(FLASH, test_sys,
    f"Codigo a revisar:\n{r5['content'][:3000]}", max_tok=1024)
calls.append(("Tester", FLASH, r6))
print(f"    {r6['elapsed']:.1f}s | tokens: {r6['input_tokens']}+{r6['output_tokens']}")

# --- Paso 7: Knowledge Extractor (flash) ---
print("  [7/7] Knowledge Extractor (flash)...")
ext_sys = (
    "Eres un Extractor de Conocimiento. Genera un resumen conciso de la solucion "
    "implementada para guardar en memoria del sistema. Responde con el resumen."
)
r7 = call(FLASH, ext_sys,
    f"Problema: {TASK[:200]}\nSolucion: {r5['content'][:1000]}\nTests: {r6['content'][:300]}", max_tok=1024)
calls.append(("Extractor", FLASH, r7))
print(f"    {r7['elapsed']:.1f}s | tokens: {r7['input_tokens']}+{r7['output_tokens']}")

total_a = time.time() - t0a

# --- Resumen Path A ---
total_input = sum(c["input_tokens"] for _, _, c in calls)
total_output = sum(c["output_tokens"] for _, _, c in calls)
cost_a = sum(cost(name, c["input_tokens"], c["output_tokens"]) for _, name, c in calls)

print(f"\n  --- RESUMEN PATH A ---")
print(f"  Llamadas LLM: {len(calls)}")
print(f"  Modelos: {sum(1 for _, m, _ in calls if m == FLASH)} flash + {sum(1 for _, m, _ in calls if m == PRO)} pro")
print(f"  Tiempo total: {total_a:.1f}s")
print(f"  Tokens input: {total_input:,}")
print(f"  Tokens output: {total_output:,}")
print(f"  Tokens total: {total_input + total_output:,}")
print(f"  Costo est.: ${cost_a:.6f}")

# ═════════════════════════════════════════════════════════════
# COMPARACION FINAL
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  COMPARACION FINAL: Pipeline Enjambre-Dev vs Builder Solo")
print("=" * 70)

# Definimos metricas
a_tokens = total_input + total_output
b_tokens = b["input_tokens"] + b["output_tokens"]
a_time = sum(c["elapsed"] for _, _, c in calls)
b_time = b["elapsed"]

headers = ["Metrica", "Enjambre-Dev", "Builder Solo", "Diferencia", "Ganador"]
rows = [
    ["Llamadas LLM", str(len(calls)), "1", f"{len(calls)}x mas", "Builder"],
    ["Tiempo total", f"{a_time:.1f}s", f"{b_time:.1f}s",
     f"{'+' if a_time > b_time else '-'}{abs(a_time - b_time):.1f}s", 
     "Builder" if b_time < a_time else "Enjambre"],
    ["Input tokens", f"{total_input:,}", f"{b['input_tokens']:,}",
     f"{total_input/b['input_tokens']:.1f}x",
     "Builder" if b['input_tokens'] < total_input else "Enjambre"],
    ["Output tokens", f"{total_output:,}", f"{b['output_tokens']:,}",
     f"{total_output/b['output_tokens']:.1f}x" if b['output_tokens'] > 0 else "-",
     "Builder" if b['output_tokens'] < total_output else "Enjambre"],
    ["Tokens totales", f"{a_tokens:,}", f"{b_tokens:,}",
     f"{a_tokens/b_tokens:.1f}x" if b_tokens > 0 else "-",
     "Builder" if b_tokens < a_tokens else "Enjambre"],
    ["Costo est. USD", f"${cost_a:.6f}", f"${cost_b:.6f}",
     f"{'+' if cost_a > cost_b else '-'}${abs(cost_a - cost_b):.6f}",
     "Builder" if cost_b < cost_a else "Enjambre"],
]

for h in headers:
    print(f"  {h:<20}", end="")
print()
print("  " + "-" * 90)

for row in rows:
    for col in row:
        print(f"  {col:<20}", end="")
    print()

# Guardar resultados
output = {
    "task": TASK,
    "path_a": {
        "calls": len(calls), "time": round(a_time, 2),
        "input_tokens": total_input, "output_tokens": total_output,
        "cost": round(cost_a, 6),
        "breakdown": [{"step": s, "model": m, "input": c["input_tokens"], "output": c["output_tokens"]} for s, m, c in calls]
    },
    "path_b": {
        "calls": 1, "time": round(b_time, 2),
        "input_tokens": b["input_tokens"], "output_tokens": b["output_tokens"],
        "cost": round(cost_b, 6),
    },
    "winner": "Builder" if cost_b < cost_a and b_tokens < a_tokens else "Enjambre" if cost_a < cost_b and a_tokens < b_tokens else "Mixto"
}

result_file = "/Users/isabeldiaz/Dev/agent-swarm/test_results/ab_test/bench_results.json"
os.makedirs(os.path.dirname(result_file), exist_ok=True)
with open(result_file, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\n  Resultados guardados en: {result_file}")
print(f"  Veredicto: Gana {output['winner']} en eficiencia (tokens+costo)")
print("=" * 70)
