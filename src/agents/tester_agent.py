"""Tester Agent — CLI wrapper independiente para QA de código.

Uso:
    python3 -m src.agents.tester_agent '{"source_code": {"main.py": "..."}, "blueprint": {...}, "rules": [...]}'

Output: JSON con {"status": "PASS"|"FAIL", "errors": [...], "sugerencias": [...], "metricas": {...}}
"""

import asyncio
import json
import sys
import tempfile
import subprocess
import re
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import get_llm
from src.token_juice import compress
from langchain_core.messages import HumanMessage, SystemMessage


TESTER_SYSTEM_PROMPT = """Eres el Tester de Código del Enjambre 4.0 — Agente QA independiente.

Analizas código fuente y CLASIFICAS errores:
- [SINTAXIS]: Errores de compilación, imports rotos
- [LOGICA]: Bugs funcionales, condiciones incorrectas
- [ARQUITECTURA]: No sigue el blueprint, mala estructura
- [DEPENDENCIA]: Faltan librerías, imports incorrectos
- [EDGE_CASE]: No maneja vacíos, nulos, límites
- [ESTILO]: Naming, documentación, code style

RESPONDE ÚNICAMENTE EN JSON:
{
  "status": "PASS" o "FAIL",
  "errors": [
    {"categoria": "[SINTAXIS]", "error": "descripción", "causa_raiz": "...", "fix": "..."}
  ],
  "sugerencias": ["fix concreto: ..."],
  "resumen": "breve resumen",
  "metricas": {
    "total_errores": N,
    "criticidad": "baja|media|alta|critica"
  }
}"""


def _run_pytest(source_code: dict) -> dict:
    """Ejecuta pytest real sobre el código."""
    if not source_code:
        return {"status": "SKIP", "errors": [], "output": "Sin código para testear"}
    
    with tempfile.TemporaryDirectory(prefix="tester_agent_") as tmpdir:
        for fname, code in source_code.items():
            fpath = os.path.join(tmpdir, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w") as f:
                f.write(code)
        
        test_files = [f for f in source_code.keys() if "test" in f.lower()]
        
        # Siempre verificar sintaxis aunque no haya tests
        syntax_errors = []
        for fname, code in source_code.items():
            if fname.endswith(".py"):
                fpath = os.path.join(tmpdir, fname)
                try:
                    subprocess.run(
                        ["python3", "-c", f"compile(open('{fpath}').read(), '{fname}', 'exec')"],
                        capture_output=True, text=True, timeout=10, check=True,
                        cwd=tmpdir,
                    )
                except subprocess.CalledProcessError as e:
                    syntax_errors.append(f"[{fname}] SyntaxError: {e.stderr[:200]}")
        
        if syntax_errors:
            return {
                "status": "FAIL",
                "errors": syntax_errors[:5],
                "output": "\n".join(syntax_errors),
            }
        
        if not test_files:
            return {
                "status": "SKIP",
                "errors": [],
                "output": "Sin archivos de test — solo verificación de sintaxis (OK)",
            }
        
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", tmpdir, "-v", "--tb=short", "-q"],
                capture_output=True, text=True, timeout=60,
            )
            output = result.stdout + result.stderr
            
            if result.returncode == 0:
                return {"status": "PASS", "errors": [], "output": output}
            
            # Parsear errores de pytest
            errors = []
            for line in output.split("\n"):
                line = line.strip()
                if "FAILED" in line:
                    errors.append(line[:200])
                elif "ERROR" in line and "error" not in line.lower().split("error")[0]:
                    errors.append(line[:200])
            
            return {
                "status": "FAIL",
                "errors": errors[:10] if errors else [f"Tests fallaron: {output[:300]}"],
                "output": output[-2000:],
            }
        
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "errors": ["Timeout (60s) ejecutando pytest"], "output": ""}
        except FileNotFoundError:
            return {"status": "SKIP", "errors": [], "output": "pytest no disponible"}


async def testear(source_code: dict, blueprint: dict = None,
                  rules: list = None, errores_previos: list = None) -> dict:
    """Analiza código con LLM + pytest en paralelo."""
    
    print(f"[Tester Agent] 🧪 Analizando {len(source_code)} archivos...")
    
    # 1. pytest real (thread)
    pytest_future = asyncio.to_thread(_run_pytest, source_code)
    
    # 2. Análisis LLM
    bp_desc = ""
    if blueprint:
        bp_desc = blueprint.get("descripcion_general", "")[:200]
        bp_files = list(blueprint.get("archivos", {}).keys())
        bp_desc += f"\nArchivos esperados: {', '.join(bp_files) if bp_files else '?'}"
    
    rules_str = "\n".join(f"- {r}" for r in (rules or [])[:5])
    
    code_section = []
    for fname, code in source_code.items():
        truncated = code[:1500] + ("\n# ... [truncado]" if len(code) > 1500 else "")
        code_section.append(f"// {fname}\n{truncated}")
    
    errors_prev_str = ""
    if errores_previos:
        errors_prev_str = "\nERRORES YA REPORTADOS (verificar si persisten):\n" + \
                          "\n".join(f"  - {e}" for e in errores_previos[:5])
    
    prompt = f"""CÓDIGO A ANALIZAR:
{chr(10).join(code_section)}

ARQUITECTURA ESPERADA:
{bp_desc}

REGLAS:
{rules_str or '(sin reglas)'}
{errors_prev_str}

Analiza el código y reporta TODOS los errores con categoría [TIPO], causa raíz y fix concreto.
Responde SOLO el JSON."""

    llm = get_llm()
    llm_future = llm.ainvoke([
        SystemMessage(content=TESTER_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    
    # Esperar ambos
    pytest_result = await pytest_future
    try:
        llm_response = await llm_future
        llm_content = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)
    except Exception as e:
        llm_content = json.dumps({"status": "FAIL", "errors": [{"categoria": "[SINTAXIS]", "error": f"LLM Error: {str(e)[:150]}", "fix": "Reintentar"}], "sugerencias": []})
    
    # Parsear LLM
    try:
        llm_content = llm_content.strip()
        if llm_content.startswith("```"):
            lines = llm_content.split("\n")
            llm_content = "\n".join(lines[1:-1])
        llm_result = json.loads(llm_content)
    except json.JSONDecodeError:
        llm_result = {"status": "FAIL", "errors": [{"categoria": "[SINTAXIS]", "error": "Tester no generó JSON válido"}], "sugerencias": []}
    
    # Fusionar resultados
    if pytest_result["status"] == "PASS":
        final_status = "PASS"
        final_errors = []
        final_sugerencias = llm_result.get("sugerencias", [])
        final_resumen = "pytest PASS ✅"
    elif pytest_result["status"] == "FAIL":
        final_status = "FAIL"
        final_errors = [{"categoria": "[SINTAXIS]", "error": e} for e in pytest_result.get("errors", [])]
        final_sugerencias = llm_result.get("sugerencias", [])
        final_resumen = f"pytest FAIL: {len(final_errors)} errores"
    else:  # SKIP
        llm_errors = llm_result.get("errors", [])
        # Normalizar
        normalized = []
        for e in llm_errors:
            if isinstance(e, str):
                normalized.append({"categoria": "[LOGICA]", "error": e, "fix": ""})
            else:
                normalized.append(e)
        
        critical_kw = ["syntax", "import", "undefined", "typeerror", "attributeerror", "nameerror"]
        critical_errors = [
            e for e in normalized
            if any(kw in str(e.get("error", "")).lower() for kw in critical_kw)
        ]
        
        if not critical_errors:
            final_status = "PASS"
            final_errors = []
            final_sugerencias = llm_result.get("sugerencias", [])
            final_resumen = "Sin errores críticos ✅"
        else:
            final_status = "FAIL"
            final_errors = critical_errors[:5]
            final_sugerencias = llm_result.get("sugerencias", [])
            final_resumen = f"LLM: {len(critical_errors)} errores críticos"
    
    # Clasificación
    cats = {}
    for e in final_errors:
        cat = e.get("categoria", "[?]") if isinstance(e, dict) else "[?]"
        cats[cat] = cats.get(cat, 0) + 1
    
    print(f"[Tester Agent] → {final_status}: {len(final_errors)} errores [{', '.join(f'{k}:{v}' for k,v in cats.items())}]")
    
    return {
        "status": final_status,
        "errors": final_errors,
        "sugerencias": final_sugerencias,
        "resumen": final_resumen,
        "metricas": {
            "total_errores": len(final_errors),
            "por_categoria": cats,
            "criticidad": "alta" if len(final_errors) > 5 else ("media" if len(final_errors) > 2 else "baja"),
        },
        "audit": {
            "action": "qa_testing",
            "pytest_status": pytest_result["status"],
            "llm_status": llm_result.get("status", "?"),
            "status": "ok",
        }
    }


def main():
    """CLI entry point."""
    if len(sys.argv) > 1:
        try:
            data = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON input"}))
            sys.exit(1)
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON from stdin"}))
            sys.exit(1)
    else:
        print(json.dumps({"error": "No input. Provide JSON with source_code, blueprint, etc."}))
        sys.exit(1)
    
    source_code = data.get("source_code", {})
    blueprint = data.get("blueprint", {})
    rules = data.get("rules", [])
    errores = data.get("errores_previos", [])
    
    result = asyncio.run(testear(source_code, blueprint=blueprint, rules=rules, errores_previos=errores))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
