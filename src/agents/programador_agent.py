"""Programador Agent — CLI wrapper independiente para generación de código.

Uso:
    python3 -m src.agents.programador_agent '{"requirement": "...", "blueprint": {...}, "errors_previos": [...]}'

Output: JSON con {"source_code": {...}, "verification": "...", "notas": [...]}
"""

import asyncio
import json
import sys
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import get_llm, get_budget
from src.token_juice import compress
from langchain_core.messages import HumanMessage, SystemMessage


PROGRAMMER_SYSTEM_PROMPT = """Eres el Programador Experto del Enjambre 4.0 — Agente independiente Bash-Native.

TRABAJO:
1. Recibes un requerimiento + blueprint de arquitectura
2. Generas código ejecutable
3. Verificas que compile/ejecute correctamente
4. Auto-corriges si hay errores

REGLAS:
- Código limpio, tipado, con docstrings
- Sigue el blueprint del Arquitecto
- Si hay errores previos, CORRÍGELOS
- Verifica sintaxis con `python3 -c "compile(open(f).read(), f, 'exec')"`
- Máximo 2 intentos de auto-corrección

RESPONDE ÚNICAMENTE EN JSON:
{
  "source_code": {
    "archivo.py": "código completo aquí",
    ...
  },
  "notas": ["nota de implementación"],
  "auto_reflection": {
    "imports_ok": true,
    "sigue_blueprint": true,
    "edge_cases_cubiertos": true,
    "confianza": 0.9
  }
}"""


async def programar(requirement: str, blueprint: dict = None,
                    errores_previos: list = None, rules: list = None) -> dict:
    """Genera código basado en un blueprint de arquitectura."""
    
    print(f"[Programador Agent] 💻 Generando código: {requirement[:100]}...")
    
    # Comprimir requirement si es muy largo
    if len(requirement) > 3000:
        requirement, _ = compress(requirement, max_tokens=2000)
    
    bp_desc = ""
    bp_files = ""
    if blueprint:
        bp_desc = blueprint.get("descripcion_general", "")[:300]
        archivos = blueprint.get("archivos", {})
        bp_files = "\n".join(
            f"  - {name}: {info.get('proposito', '?')[:150]}"
            for name, info in archivos.items()
        )
    
    errors_str = ""
    if errores_previos:
        errors_str = "\nERRORES A CORREGIR:\n" + "\n".join(f"  - {e}" for e in errores_previos[:10])
    
    rules_str = "\n".join(f"- {r}" for r in (rules or [])[:8])
    
    prompt = f"""REQUERIMIENTO:
{requirement}

BLUEPRINT DE ARQUITECTURA:
Descripción: {bp_desc}
Archivos a crear:
{bp_files or '(no especificados — diseña tú la estructura)'}

REGLAS DE NEGOCIO:
{rules_str or '(sin reglas)'}
{errors_str}

Genera el código completo. Incluye imports, docstrings, type hints.
Si hay tests en el blueprint, escríbelos también.
Responde SOLO el JSON con el código fuente."""

    llm = get_llm(max_tokens=get_budget("programmer"))
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content=PROGRAMMER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content = response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        return {
            "source_code": {"error.py": f"# Error: {str(e)}"},
            "notas": [f"Error LLM: {str(e)[:200]}"],
            "verification": f"LLM Error: {e}",
        }
    
    # Parsear JSON
    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {
            "source_code": {"main.py": content},
            "notas": ["JSON mal formado — usando raw output como código"],
            "auto_reflection": {"confianza": 0.0},
        }
    
    source_code = result.get("source_code", {})
    notas = result.get("notas", [])
    reflection = result.get("auto_reflection", {})
    
    # Verificar sintaxis de cada archivo Python
    verification_results = []
    with tempfile.TemporaryDirectory(prefix="prog_agent_") as tmpdir:
        for filename, code in source_code.items():
            if not filename.endswith(".py"):
                continue
            fpath = Path(tmpdir) / filename
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(code)
            
            # Verificar sintaxis
            try:
                subprocess.run(
                    ["python3", "-c", f"compile(open('{fpath}').read(), '{filename}', 'exec')"],
                    capture_output=True, text=True, timeout=10, check=True,
                    cwd=tmpdir,
                )
                verification_results.append(f"[{filename}] ✅ Sintaxis OK")
            except subprocess.CalledProcessError as e:
                verification_results.append(f"[{filename}] ⚠️ Syntax Error: {e.stderr[:200]}")
                # Intentar auto-corrección simple: ejecutar con python3 y capturar error
                try:
                    result_run = subprocess.run(
                        ["python3", str(fpath)],
                        capture_output=True, text=True, timeout=10,
                        cwd=tmpdir,
                    )
                    if result_run.returncode != 0:
                        verification_results.append(f"[{filename}] Runtime: {result_run.stderr[:200]}")
                except:
                    pass
    
    verification = "\n".join(verification_results) if verification_results else "(sin archivos .py)"
    
    return {
        "source_code": source_code,
        "notas": notas,
        "verification": verification,
        "auto_reflection": reflection,
        "audit": {
            "action": "code_generation",
            "files_generated": len(source_code),
            "syntax_ok": "⚠️" not in verification,
            "status": "ok" if "⚠️" not in verification else "warn",
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
        print(json.dumps({"error": "No input. Provide JSON with requirement, blueprint, etc."}))
        sys.exit(1)
    
    requirement = data.get("requirement", "")
    blueprint = data.get("blueprint", {})
    errores = data.get("errores_previos", [])
    rules = data.get("rules", [])
    
    result = asyncio.run(programar(requirement, blueprint=blueprint,
                                    errores_previos=errores, rules=rules))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
