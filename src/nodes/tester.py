"""Nodo 5 — Tester con Model Router, pytest real y Debug Memory.

MEJORAS IMPLEMENTADAS:
  1. Model Router: flash↔pro según escalado quirúrgico
  2. pytest real con captura de tracebacks
  3. Debug Memory: construye historial de errores→fixes para el Programador
  4. Loop detection via fingerprint
"""

import json, os, sys, tempfile, subprocess, asyncio, re
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import get_llm, get_pro_llm, get_router_llm, TEMPERATURE_DEFAULT, safe_invoke, get_budget
from src.model_router import get_router


TESTER_PROMPT = """Eres el Tester de Código del Enjambre — QA Profesional v3.0 (Superinteligente).

Tu tarea es analizar el código fuente y CLASIFICAR cada error encontrado:

1. ¿Compila/ejecuta sin errores de sintaxis?
2. ¿Cumple con TODAS las business_rules?
3. ¿Sigue el architecture_blueprint?
4. ¿Tiene errores lógicos, condiciones imposibles, o bugs obvios?
5. ¿Maneja casos borde? (entradas vacías, valores negativos, etc.)
6. ¿Los imports son correctos y las dependencias existen?
7. ¿Hay variables no definidas o funciones llamadas sin definir?
8. ¿Hay problemas de rendimiento obvios? (bucles infinitos, etc.)
9. ¿El código es mantenible? (nombres, estructura, complejidad ciclomática)

CLASIFICACIÓN DE ERRORES — Cada error debe incluir su categoría:
- [SINTAXIS]    → Error de sintaxis, compilación, imports rotos
- [LOGICA]      → Error de lógica, condición incorrecta, bug funcional
- [ARQUITECTURA] → Error estructural, no sigue blueprint, mala organización
- [DEPENDENCIA]  → Falta librería, import incorrecto, versiones
- [PERFORMANCE]  → Problema de rendimiento (bucle infinito, algoritmo ineficiente)
- [EDGE_CASE]    → No maneja casos borde (vacíos, nulos, límites)
- [ESTILO]      → Code style, naming, documentación

SÉ CRÍTICO. Si encuentras CUALQUIER problema, repórtalo.

Responde ÚNICAMENTE en este formato JSON sin texto adicional:

{
  "status": "PASS" o "FAIL",
  "errors": [
    {"categoria": "[SINTAXIS]", "error": "descripción", "causa_raiz": "por qué ocurre", "fix": "cómo corregirlo", "linea": 42},
    ...
  ],
  "sugerencias_scratchpad": ["fix concreto para el Programador: ...", ...],
  "resumen": "breve resumen del análisis",
  "metricas": {
    "total_errores": 2,
    "por_categoria": {"SINTAXIS": 1, "LOGICA": 1},
    "criticidad": "baja|media|alta|critica"
  }
}

IMPORTANTE: Para cada error, incluye categoría, causa raíz y fix concreto.
Máximo 1024 tokens de salida."""


def _build_tester_prompt(state: TeamState, codigo_limit: int = 2000) -> str:
    """Construye el prompt para el tester."""
    source_code = state.get("source_code", {})
    blueprint = state.get("architecture_blueprint", {})
    rules = state.get("business_rules", [])
    scratchpad = state.get("scratchpad", [])
    debug_history = state.get("debug_history", [])

    codigo_formateado = []
    for filename, code in source_code.items():
        code_short = code[:codigo_limit] + ("\n# ... [truncado]" if len(code) > codigo_limit else "")
        codigo_formateado.append(f"// Archivo: {filename}\n{code_short}")

    bp_desc = blueprint.get("descripcion_general", "")[:200]
    bp_files = list(blueprint.get("archivos", {}).keys())
    scratchpad_relevante = scratchpad[-5:] if scratchpad else []
    
    # Debug history como contexto
    debug_ctx = ""
    if debug_history:
        items = [f"  - Iter {e.get('it','?')}: {e.get('error','?')} → Fix: {e.get('fix','?')}"
                 for e in debug_history[-3:]]
        debug_ctx = f"\nERRORES YA CORREGIDOS (verificar que no reaparezcan):\n" + "\n".join(items)

    return f"""CÓDIGO A ANALIZAR:
{chr(10).join(codigo_formateado)}

REGLAS:
{chr(10).join(f'- {r}' for r in rules[:5])}

ARQUITECTURA:
{bp_desc}
Archivos esperados: {', '.join(bp_files) if bp_files else '(no definidos)'}
{debug_ctx}

NOTAS PREVIAS:
{chr(10).join(f'- {s}' for s in scratchpad_relevante) if scratchpad_relevante else '(sin notas previas)'}

Analiza el código y reporta en formato JSON."""


def _parse_pytest_output(output: str) -> list[dict]:
    """Parsea el output de pytest para extraer errores estructurados.
    
    Cada error incluye:
    - type: tipo de error (ImportError, AssertionError, etc.)
    - file: archivo donde ocurre
    - line: línea del error
    - message: mensaje descriptivo
    - fix: sugerencia de fix (cuando es posible inferirla)
    """
    errors = []
    lines = output.split("\n")
    current_error = None
    
    for line in lines:
        stripped = line.strip()
        
        # Detectar FAILED tests
        m = re.match(r'FAILED\s+(\S+)', stripped)
        if m:
            errors.append({
                "type": "FAILED",
                "file": m.group(1),
                "line": 0,
                "message": stripped[:200],
                "fix": f"Revisar el test {m.group(1)}"
            })
            continue
        
        # Detectar ModuleNotFoundError / ImportError
        m = re.search(r'(ModuleNotFoundError|ImportError):\s*(.+)', stripped)
        if m:
            error_type = m.group(1)
            detail = m.group(2).strip()[:150]
            package = detail.replace("No module named ", "").strip("'\"")
            errors.append({
                "type": error_type,
                "file": "",
                "line": 0,
                "message": f"{error_type}: {detail}",
                "fix": f"Agregar 'import {package}' o instalar dependencia faltante" if package else detail
            })
            continue
        
        # Detectar SyntaxError
        m = re.search(r'SyntaxError:\s*(.+)', stripped)
        if m:
            errors.append({
                "type": "SyntaxError",
                "file": "",
                "line": 0,
                "message": f"SyntaxError: {m.group(1)[:150]}",
                "fix": "Revisar sintaxis del archivo"
            })
            continue
        
        # Detectar assert failures
        m = re.search(r'(AssertionError|assert)\s+(.+)', stripped)
        if m:
            errors.append({
                "type": "AssertionError",
                "file": "",
                "line": 0,
                "message": stripped[:200],
                "fix": "Revisar la lógica del test: el valor obtenido no coincide con el esperado"
            })
            continue
        
        # Detectar TypeError / ValueError / AttributeError
        m = re.search(r'(TypeError|ValueError|AttributeError|KeyError|IndexError):\s*(.+)', stripped)
        if m:
            error_type = m.group(1)
            detail = m.group(2).strip()[:150]
            fix_map = {
                "TypeError": "Verificar tipos de datos: puede faltar una conversión o argumento",
                "ValueError": "Verificar que los valores estén en el rango esperado",
                "AttributeError": "Verificar que el objeto tenga el atributo/método usado",
                "KeyError": "Verificar que la clave exista en el diccionario antes de acceder",
                "IndexError": "Verificar que el índice no exceda la longitud de la lista",
            }
            errors.append({
                "type": error_type,
                "file": "",
                "line": 0,
                "message": f"{error_type}: {detail}",
                "fix": fix_map.get(error_type, f"Corregir error de tipo {error_type}")
            })
            continue
    
    # Si no se parseó nada, devolver el output genérico
    if not errors:
        # Extraer líneas con archivos y números de línea
        file_errors = re.findall(r'File\s+\"([^\"]+)\",\s+line\s+(\d+)', output)
        for fpath, lineno in file_errors[:3]:
            errors.append({
                "type": "ERROR",
                "file": fpath,
                "line": int(lineno),
                "message": f"Error en {fpath}:{lineno}",
                "fix": f"Revisar línea {lineno} en {fpath}"
            })
    
    return errors[:5]


def _run_pytest_real(source_code: dict) -> dict:
    """Ejecuta pytest real sobre el código generado.
    
    Escribe archivos a directorio temporal y ejecuta pytest.
    Retorna errores detallados con tracebacks parseados.
    """
    if not source_code:
        return {"status": "FAIL", "errors": ["No hay código para testear"], "output": ""}

    with tempfile.TemporaryDirectory(prefix="enjambre_test_") as tmpdir:
        for fname, code in source_code.items():
            fpath = os.path.join(tmpdir, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w") as f:
                f.write(code)

        test_files = [f for f in source_code.keys() if "test" in f.lower()]
        if not test_files:
            return {"status": "SKIP", "errors": [], "output": "", "info": "Sin archivos de test"}

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", tmpdir, "-v", "--tb=long", "-q"],
                capture_output=True, text=True, timeout=60,
            )
            output = result.stdout + result.stderr

            if result.returncode == 0:
                return {"status": "PASS", "errors": [], "output": output}

            # Parsear errores del output de pytest
            parsed_errors = _parse_pytest_output(output)
            
            # Extraer también el traceback detallado para el Programador
            traceback_lines = []
            capture = False
            for line in output.split("\n"):
                if "ERRORS" in line or "FAILED" in line or "short test summary" in line:
                    capture = True
                if capture:
                    traceback_lines.append(line)
            
            traceback_section = "\n".join(traceback_lines[-30:])[-2000:]
            
            error_messages = []
            for err in parsed_errors:
                fix = err.get("fix", "")
                msg = err.get("message", "")
                if fix:
                    error_messages.append(f"{msg} → {fix}")
                else:
                    error_messages.append(msg)

            return {
                "status": "FAIL",
                "errors": error_messages[:5] if error_messages else [f"Tests fallaron:\n{traceback_section[:300]}"],
                "output": traceback_section,
            }

        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "errors": ["Timeout ejecutando pytest (60s)"], "output": ""}
        except FileNotFoundError:
            return {"status": "SKIP", "errors": [], "output": "", "info": "pytest no disponible"}
        except Exception as e:
            return {"status": "FAIL", "errors": [f"Error en tests: {str(e)[:100]}"], "output": ""}


def _build_debug_history(test_report: dict, previous_history: list, iteration: int,
                         current_code: dict = None) -> list:
    """Construye debug_history con tracking de errores resueltos (v3.0).
    
    - Errores que desaparecen → se marcan como "resueltos" con ✅
    - Errores que persisten → se mantienen sin fix (el Programador no los ha resuelto)
    - Errores nuevos → se agregan al historial
    - CLASIFICACIÓN: cada error guarda su categoría
    
    debug_history se usa para que el Programador aprenda de iteraciones anteriores
    y NO reintroduzca errores ya resueltos.
    """
    current_errors = test_report.get("errors", []) if test_report.get("status") == "FAIL" else []
    history = []
    
    # Normalizar errores actuales: soporta dicts y strings
    def _normalizar(e):
        if isinstance(e, dict):
            return f"{e.get('categoria', '')} {e.get('error', '')}"[:120]
        return str(e).strip()[:120]
    
    current_normalized = [_normalizar(e) for e in current_errors]
    current_set = set(current_normalized)
    
    # Extraer fix from dict
    def _get_fix(e):
        if isinstance(e, dict):
            return e.get("fix", "")
        if "→" in str(e):
            return str(e).split("→", 1)[1].strip()[:200]
        return ""
    
    def _get_cat(e):
        if isinstance(e, dict):
            return e.get("categoria", "[LOGICA]")
        return "[LOGICA]"
    
    # Procesar historial previo
    for entry in previous_history:
        err_text = entry.get("error", "")
        had_fix = entry.get("fix", "")
        already_resolved = entry.get("resuelto", False)
        categoria = entry.get("categoria", "[LOGICA]")
        
        if already_resolved:
            history.append(entry)
            continue
        
        error_still_present = any(err_text[:50] in e for e in current_normalized)
        
        if error_still_present:
            history.append({
                "it": entry.get("it", iteration),
                "error": err_text,
                "fix": "",
                "file": entry.get("file", ""),
                "resuelto": False,
                "categoria": categoria,
            })
            for e in list(current_set):
                if err_text[:50] in e:
                    current_set.discard(e)
                    break
        elif had_fix:
            history.append({
                "it": entry.get("it", iteration),
                "error": err_text,
                "fix": had_fix,
                "file": entry.get("file", ""),
                "resuelto": True,
                "resuelto_en_iter": iteration,
                "categoria": categoria,
            })
    
    # Agregar errores nuevos (no vistos antes)
    for i, error_normalized in enumerate(sorted(current_set)):
        original_error = current_errors[i] if i < len(current_errors) else error_normalized
        fix = _get_fix(original_error)
        cat = _get_cat(original_error)
        
        error_text = error_normalized
        if "→" in error_text and not fix:
            parts = error_text.split("→", 1)
            error_text = parts[0].strip()
            fix = parts[1].strip()
        
        history.append({
            "it": iteration,
            "error": error_text[:200],
            "fix": fix[:200],
            "file": "",
            "resuelto": False,
            "categoria": cat,
        })
    
    return history[-35:]  # Máximo 35 entradas


async def tester_node(state: TeamState) -> dict:
    """Analiza el código generado en busca de errores (solo LLM, versión flash)."""
    router = get_router()
    llm = get_router_llm(router, "Tester",
                          iteration=state.get("iteration_count", 0),
                          errors=len(state.get("test_report", {}).get("errors", [])))
    
    prompt = _build_tester_prompt(state)
    
    response = await safe_invoke(llm, [
        SystemMessage(content=TESTER_PROMPT),
        HumanMessage(content=prompt),
    ])

    content = response.content if hasattr(response, 'content') else str(response)

    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {"status": "FAIL", "errors": [{"categoria": "[SINTAXIS]", "error": "Tester no generó JSON válido", "fix": "Revisar formato de respuesta"}],
                  "sugerencias_scratchpad": [], "resumen": "Error de parseo"}

    # Normalizar: si errors viene como lista de strings, convertir a dict
    errors = result.get("errors", [])
    normalized_errors = []
    for e in errors:
        if isinstance(e, str):
            # Extraer categoría si tiene [CAT] al inicio
            import re
            m = re.match(r'^(\[.*?\])\s*(.*)', e)
            if m:
                normalized_errors.append({"categoria": m.group(1), "error": m.group(2), "fix": ""})
            else:
                normalized_errors.append({"categoria": "[LOGICA]", "error": e, "fix": ""})
        else:
            normalized_errors.append(e)

    return {
        "status": result.get("status", "FAIL"),
        "errors": normalized_errors,
        "sugerencias": result.get("sugerencias_scratchpad", []),
        "resumen": result.get("resumen", ""),
        "metricas": result.get("metricas", {}),
    }


async def _tester_node_pro(state: TeamState) -> dict:
    """Versión Pro del Tester para mejor diagnóstico."""
    router = get_router()
    llm = get_pro_llm(max_tokens=1024)  # Pro siempre para esta variante
    
    prompt = _build_tester_prompt(state, codigo_limit=3000) + """
    
Eres un tester PRO. Identifica errores CONCRETOS con línea y causa raíz.
Si el código es correcto, responde PASS. Si no, detalla CADA error con precisión.
INCLUYE el fix concreto para cada error en sugerencias_scratchpad."""

    response = await safe_invoke(llm, [
        SystemMessage(content=TESTER_PROMPT.replace("Máximo 512", "Máximo 1024")),
        HumanMessage(content=prompt),
    ])

    content = response.content if hasattr(response, 'content') else str(response)

    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {"status": "FAIL", "errors": ["Error de parseo en Tester Pro"],
                  "sugerencias_scratchpad": [], "resumen": ""}

    return {
        "status": result.get("status", "FAIL"),
        "errors": result.get("errors", []),
        "sugerencias": result.get("sugerencias_scratchpad", []),
        "resumen": result.get("resumen", ""),
    }


async def parallel_tester_node(state: TeamState) -> dict:
    """Ejecuta LLM tester + pytest real en paralelo con Model Router.
    
    El router decide si usar flash o pro según el nivel de escalado.
    pytest real gana sobre LLM: si pytest pasa, el código es válido.
    """
    source_code = state.get("source_code", {})
    iteration = state.get("iteration_count", 0) + 1  # 1-indexed
    previous_history = state.get("debug_history", [])
    
    # ── Router decide si usar pro o flash ──
    router = get_router()
    model_type, _, _ = router.get_llm_for_node(
        "Tester", iteration=iteration,
        errors=len(state.get("test_report", {}).get("errors", []))
    )
    
    nivel = "pro" if model_type == "pro" else "flash"
    tester_llm_fn = _tester_node_pro if nivel == "pro" else tester_node
    print(f"[Tester] Router: {nivel} (iter {iteration})")

    # Lanzar LLM + pytest en paralelo
    llm_future = asyncio.create_task(tester_llm_fn(state))
    pytest_future = asyncio.to_thread(_run_pytest_real, source_code)

    llm_result = await llm_future
    pytest_result = await pytest_future

    print(f"[Tester v3] LLM({nivel}): {llm_result['status']} | pytest: {pytest_result['status']}")

    # ── Clasificación de errores (v3.0) ──
    def _clasificar_error(error, default_cat="[LOGICA]"):
        """Asegura que cada error tenga categoría."""
        if isinstance(error, str):
            import re
            m = re.match(r'^(\[.*?\])\s*(.*)', error)
            if m:
                return {"categoria": m.group(1), "error": m.group(2), "fix": ""}
            return {"categoria": default_cat, "error": error, "fix": ""}
        if isinstance(error, dict):
            if "categoria" not in error:
                error["categoria"] = default_cat
            return error
        return {"categoria": default_cat, "error": str(error), "fix": ""}

    def _extraer_error_texto(error) -> str:
        if isinstance(error, str):
            return error
        if isinstance(error, dict):
            return f"{error.get('categoria', '')} {error.get('error', '')}"
        return str(error)

    # ── Decisión final ──
    if pytest_result["status"] == "PASS":
        final_status = "PASS"
        final_errors = []
        final_sugerencias = llm_result.get("sugerencias", [])
        final_resumen = f"pytest PASS (+ LLM: {llm_result.get('resumen', '')})"
        out_detalle = ""

    elif pytest_result["status"] == "FAIL":
        final_status = "FAIL"
        out_detalle = pytest_result.get("output", "")
        pytest_parsed = pytest_result.get("errors", [])
        final_errors = [_clasificar_error(e, "[SINTAXIS]") for e in pytest_parsed]
        final_sugerencias = llm_result.get("sugerencias", [])
        if out_detalle:
            final_sugerencias.append(f"[pytest traceback]\n{out_detalle[:1500]}")
        final_resumen = f"pytest FAIL: {len(final_errors)} errores"

    else:  # pytest SKIP
        llm_errors_raw = llm_result.get("errors", [])
        llm_errors = [_clasificar_error(e) for e in llm_errors_raw]
        
        keywords_criticos = [
            "syntaxerror", "undefined", "importerror", "typeerror",
            "attributeerror", "keyerror", "nameerror", "not defined",
            "no existe", "no definido", "traceback", "exception",
            "missing required", "campo faltante",
        ]
        errores_criticos = [
            e for e in llm_errors
            if any(kw in e.get("error", "").lower() for kw in keywords_criticos)
        ]

        if not errores_criticos:
            final_status = "PASS"
            final_errors = []
            final_sugerencias = llm_result.get("sugerencias", [])
            final_resumen = f"Sin errores críticos"
            out_detalle = ""
        else:
            final_status = "FAIL"
            final_errors = errores_criticos[:5]
            final_sugerencias = llm_result.get("sugerencias", [])
            final_resumen = f"LLM FAIL: {len(errores_criticos)} errores críticos"
            out_detalle = ""

    # Estadísticas de clasificación
    cats = {}
    for e in final_errors:
        cat = e.get("categoria", "[?]") if isinstance(e, dict) else "[?]"
        cats[cat] = cats.get(cat, 0) + 1
    clasificacion = ", ".join(f"{k}:{v}" for k, v in sorted(cats.items()))
    print(f"[Tester v3] → {final_status}: {len(final_errors)} errores [{clasificacion}]")

    # ── Construir debug_history con tracking de resueltos ──
    test_report = {"status": final_status, "errors": final_errors}
    debug_history = _build_debug_history(test_report, previous_history, iteration, source_code)

    return {
        "test_report": test_report,
        "iteration_count": iteration,
        "scratchpad": final_sugerencias,
        "debug_history": debug_history,
        "audit_trail": [{
            "nodo": f"Tester ({nivel})",
            "accion": f"QA — iteración {iteration}",
            "resultado": f"{final_status} — {len(final_errors)} errores (LLM: {llm_result['status']}, pytest: {pytest_result['status']})",
        }],
    }
