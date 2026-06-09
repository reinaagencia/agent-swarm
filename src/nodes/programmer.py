"""Nodo 4 — Programador Bash-Native V3 con auto-reflexión + TDD ligero.

MEJORA SUPERINTELIGENCIA v3.0 (INTELIGENCIA x4):
  1. Auto-reflexión: se auto-evalúa contra checklist de 10 puntos antes de entregar
  2. TDD ligero: escribe tests ANTES del código cuando aplica
  3. Bash-Native: ejecuta código real y ve el output
  4. Debug Memory con embeddings: errores ya resueltos con búsqueda semántica
  5. Model Router: flash↔pro según contexto

ARQUITECTURA:
```
Recibe blueprint + errores previos
         ↓
  [Auto-reflexión] ¿Entiendo bien el problema?
         ↓
  [TDD] Escribe tests primero (si aplica)
         ↓
  Escribe código a disco
         ↓
  Ejecuta código (bash)
         ↓
  ¿Errores? → Lee output → Corrige → Re-ejecuta
         ↓
  [Auto-reflexión final] Checklist 10 pts → ¿Paso?
         ↓
  Sin errores → Entrega código + output de verificación
```
"""

import json
import asyncio
import re
import subprocess
import sys
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import get_llm, get_router_llm, safe_invoke, get_budget, get_dynamic_limit
from src.model_router import get_router
from src.bash_executor import execute_command, format_output_for_llm


# Directorio temporal para ejecuciones del programador
EXEC_DIR = Path("/tmp") / "enjambre-exec"
OUTPUT_DIR = Path("/Users/isabeldiaz/Dev/agent-swarm") / "output"


PROGRAMMER_PROMPT = """Eres el Programador Experto del Enjambre (Bash-Native) — v3.0.

⚠️ REGLA DE ORO #1: EL CÓDIGO DEBE COMPILAR SIN ERRORES DE SINTAXIS.
Antes de entregar, verifica MENTALMENTE que cada archivo .py compila con:
  python3 -c "compile(open('file').read(), 'file', 'exec')"
Un solo error de sintaxis reinicia el ciclo y desperdicia recursos.
Los errores de sintaxis son INACEPTABLES.

⚠️ REGLA DE ORO #2: NO uses 'import X' si X es un archivo local.
Si generas un archivo llamado config.py, NO escribas 'import config' en otro archivo.
Python confunde módulos locales con paquetes pip. Usa imports relativos: 'from . import config'.

⚠️ REGLA DE ORO #3: Cada archivo debe ser auto-contenido e independiente.
No asumas que otro archivo existe. Verifica que cada .py funciona por sí solo.

TU TRABAJO:
Implementas código y lo VERIFICAS ejecutándolo. No entregas código no probado.
SIGUES EL CICLO: auto-reflexión → TDD → código → bash-verify → auto-reflexión final.

REGLAS:
1. Sigue el blueprint del Arquitecto.
2. CORRIGE errores del test_report previo.
3. REVISA debug_history: errores ya resueltos, NO LOS REPITAS.
4. Código limpio, tipado, con docstrings.
5. Después de escribir, VERIFICA que compila con compile().
6. Si hay errores de ejecución, LEE el output y CORRIGE.
7. Máximo 3 intentos de auto-corrección local.
8. AUTO-REFLEXIÓN: Antes de entregar, evalúa tu código contra estos 10 puntos:
   - ✅ ¿Los imports son correctos y no chocan con archivos locales?
   - ✅ ¿Las funciones tienen type hints?
   - ✅ ¿Hay docstrings en funciones públicas?
   - ✅ ¿Se manejan casos borde (edge cases)?
   - ✅ ¿Hay logging o prints útiles para debug?
   - ✅ ¿Las variables tienen nombres descriptivos?
   - ✅ ¿El código sigue el blueprint?
   - ✅ ¿Se respetan las business_rules?
   - ✅ ¿No hay código duplicado?
   - ✅ ✅✅ ¿CADA ARCHIVO COMPILA CON compile()? (doble check obligatorio)
9. TDD LIGERO: Si el requerimiento incluye lógica de negocio específica,
   escribe los tests PRIMERO, luego el código que los hace pasar.

Responde ÚNICAMENTE en este formato JSON:
{
  "source_code": {
    "archivo.py": "código completo",
    "test_archivo.py": "tests si aplica (TDD)",
    ...
  },
  "notas_scratchpad": ["notas de implementación"],
  "verification_output": "output de la ejecución de verificación",
  "auto_reflection": {
    "checklist_passed": true/false,
    "puntos_fallidos": ["punto 1", ...],
    "confianza": 0.0-1.0
  }
}

IMPORTANTE: Siempre incluye verification_output con el resultado de ejecutar el código."""


def _auto_install_imports(source_code: dict) -> list[str]:
    """Detecta imports en el código generado e instala dependencias faltantes.
    
    OPTIMIZACIÓN: NO instala paquetes cuyos nombres coinciden con archivos locales
    (ej: si hay config.py, no instalar pip package 'config').
    
    Escanea todos los archivos .py en busca de import statements.
    Intenta instalar cualquier paquete que no esté disponible.
    """
    imports_detectados = set()
    
    # Colección de módulos locales (nombres de archivos sin extensión)
    local_modules = set()
    for fname in source_code:
        if fname.endswith('.py'):
            local_modules.add(fname.replace('.py', ''))
        # También carpetas con __init__.py
        if '/' in fname:
            parts = fname.split('/')
            if len(parts) >= 1:
                local_modules.add(parts[0])
    
    for filename, code in source_code.items():
        if not filename.endswith(".py"):
            continue
        
        # Detectar import X / from X import Y
        for match in re.finditer(r'^import\s+(\w+)|^from\s+(\w+)\s+import', code, re.MULTILINE):
            pkg = match.group(1) or match.group(2)
            if pkg and pkg not in ('os', 'sys', 'json', 'time', 'datetime', 're', 'math',
                                     'pathlib', 'collections', 'functools', 'itertools',
                                     'typing', 'abc', 'enum', 'hashlib', 'uuid',
                                     'subprocess', 'tempfile', 'shutil', 'logging',
                                     'argparse', 'csv', 'io', 'textwrap', 'copy',
                                     'inspect', 'pdb', 'traceback', 'warnings',
                                     'dataclasses', 'weakref', 'types', 'string',
                                     'random', 'statistics', 'decimal', 'fractions',
                                     'json', 'base64', 'binascii', 'struct',
                                     'socket', 'http', 'urllib', 'email',
                                     'xml', 'html', 'configparser'):
                # Saltar si es un módulo local (archivo en el proyecto)
                if pkg in local_modules:
                    continue
                imports_detectados.add(pkg)
    
    if not imports_detectados:
        return []
    
    # Mapa de import → pip package (solo paquetes reales PIP, no nombres locales)
    # IMPORTANTE: Solo incluir paquetes PIP verificados, NO módulos locales
    PIP_MAP = {
        'fastapi': 'fastapi', 'pydantic': 'pydantic', 'uvicorn': 'uvicorn',
        'sqlalchemy': 'sqlalchemy', 'flask': 'Flask', 'django': 'django',
        'pandas': 'pandas', 'numpy': 'numpy', 'openpyxl': 'openpyxl',
        'requests': 'requests', 'httpx': 'httpx', 'aiohttp': 'aiohttp',
        'pytest': 'pytest', 'pytest_asyncio': 'pytest-asyncio',
        'dotenv': 'python-dotenv', 'yaml': 'pyyaml', 'bs4': 'beautifulsoup4',
        'selenium': 'selenium', 'playwright': 'playwright',
        'PIL': 'pillow', 'cv2': 'opencv-python',
        'matplotlib': 'matplotlib', 'plotly': 'plotly',
        'scipy': 'scipy', 'sklearn': 'scikit-learn',
        'click': 'click', 'typer': 'typer',
        'tqdm': 'tqdm', 'psutil': 'psutil',
        'watchdog': 'watchdog', 'asyncpg': 'asyncpg',
        'aiosqlite': 'aiosqlite', 'jinja2': 'jinja2',
        'alembic': 'alembic', 'bcrypt': 'bcrypt',
        'python_jose': 'python-jose[cryptography]', 'passlib': 'passlib[bcrypt]',
        'python_multipart': 'python-multipart',
        'aiofiles': 'aiofiles', 'watchfiles': 'watchfiles',
        'redis': 'redis', 'celery': 'celery',
        'asyncio': None,  # built-in
    }
    
    installed = []
    for imp in sorted(imports_detectados):
        pkg = PIP_MAP.get(imp)
        if pkg is None:
            continue  # No está en el mapa conocido → probablemente módulo local
        try:
            __import__(imp)
        except ImportError:
            try:
                print(f"    [AutoInstall] Instalando {pkg}...")
                import subprocess, sys
                r = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', pkg, '-q'],
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode == 0:
                    installed.append(pkg)
                    print(f"    [AutoInstall] ✅ {pkg} instalado")
                else:
                    print(f"    [AutoInstall] ⚠️ Falló {pkg}: {r.stderr[:100]}")
            except Exception as e:
                print(f"    [AutoInstall] ⚠️ Error: {e}")
    
    return installed


def _resumir_blueprint(blueprint: dict) -> str:
    """Extrae solo la info esencial del blueprint."""
    if not blueprint:
        return "(sin blueprint)"
    desc = blueprint.get("descripcion_general", "")[:300]
    archivos = blueprint.get("archivos", {})
    resumen = {}
    for nombre, info in archivos.items():
        resumen[nombre] = {
            "proposito": info.get("proposito", "")[:150],
            "dependencias": info.get("dependencias", []),
        }
    flujo = blueprint.get("flujo_datos", "")[:300]
    return json.dumps({
        "descripcion": desc,
        "archivos": resumen,
        "flujo_datos": flujo,
    }, indent=2, ensure_ascii=False)


def _build_prompt(state: TeamState, verification_feedback: str = "",
                  es_autocorreccion: bool = False) -> str:
    """Construye el prompt con debug history y feedback de ejecución."""
    blueprint = state.get("architecture_blueprint", {})
    test_report = state.get("test_report", {})
    scratchpad = state.get("scratchpad", [])
    requirement = state.get("user_requirement", "")
    rules = state.get("business_rules", [])
    debug_history = state.get("debug_history", [])
    meta_plan = state.get("meta_plan", {})

    blueprint_resumido = _resumir_blueprint(blueprint)
    scratchpad_relevante = scratchpad[-8:] if scratchpad else []

    # Debug Memory
    debug_section = ""
    if debug_history:
        resueltos = [e for e in debug_history if e.get("resuelto")]
        pendientes = [e for e in debug_history if not e.get("resuelto")]
        
        if pendientes:
            items = [f"  - Iter {e.get('it', '?')}: {e.get('error', '?')}" for e in pendientes[-5:]]
            debug_section += f"\nERRORES PENDIENTES:\n" + "\n".join(items)
        
        if resueltos:
            items = [f"  - Iter {e.get('it', '?')}: [{e.get('error', '?')}] → {e.get('fix', '?')}" for e in resueltos[-5:]]
            debug_section += f"\nERRORES RESUELTOS (NO REPETIR):\n" + "\n".join(items)

    # Errores actuales
    errores_previos = ""
    if test_report.get("status") == "FAIL":
        errors = test_report.get("errors", [])
        errores_previos = f"\nERRORES A CORREGIR:\n" + "\n".join(f'- {e}' for e in errors)
        if scratchpad_relevante:
            errores_previos += "\nNotas:\n" + "\n".join(f'- {s}' for s in scratchpad_relevante)

    # Feedback de verificación local
    verif_section = ""
    if verification_feedback:
        verif_section = f"\n\nFEEDBACK DE EJECUCIÓN LOCAL:\n{verification_feedback}\n\n"
        verif_section += "Corrige los errores basado en este feedback."

    # Meta-plan del Gate 0 (si existe)
    meta_section = ""
    if meta_plan:
        meta_section = f"\nPLAN MAESTRO (Gate 0):\n{json.dumps(meta_plan, indent=2)[:500]}\n"

    # Contexto dinámico
    req_limit = get_dynamic_limit(requirement, ratio=0.5, min_val=400, max_val=3000)
    req_trimmed = requirement[:req_limit]

    return f"""Requerimiento ({len(requirement)} chars, mostrando {req_limit}):
{req_trimmed}
{meta_section}
Reglas:
{chr(10).join(f'- {r}' for r in rules[:8])}

Blueprint:
{blueprint_resumido}
{debug_section}
{errores_previos}
{verif_section}
Implementa el código completo en formato JSON. DESPUÉS de escribir, verifica que funciona ejecutándolo.
APLICA AUTO-REFLEXIÓN: revisa el checklist de 10 puntos antes de entregar."""


async def _verify_code(source_code: dict, workdir: Path) -> str:
    """Verifica el código ejecutándolo y capturando output."""
    results = []
    
    for filename, code in source_code.items():
        if not filename.endswith(".py"):
            continue
        
        filepath = workdir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(code)
        
        # Verificar sintaxis
        result = await execute_command(
            f"python3 -c \"compile(open('{filename}').read(), '{filename}', 'exec')\"",
            workdir=workdir,
            timeout=10,
        )
        if not result.success:
            results.append(f"[{filename}] ⚠️ Syntax error: {result.stderr[:200]}")
            continue
        
        results.append(f"[{filename}] ✅ Syntax OK")
        
        if "if __name__" in code or "def " in code:
            result = await execute_command(
                f"python3 -c \"import ast; ast.parse(open('{filename}').read()); print('AST OK')\"",
                workdir=workdir,
                timeout=10,
            )
            if result.success:
                results.append(f"[{filename}] ✅ AST valid")
    
    return "\n".join(results) if results else "(sin archivos Python para verificar)"


async def programmer_node(state: TeamState) -> dict:
    """Programador Bash-Native V3 con auto-reflexión + TDD ligero."""
    iteration = state.get("iteration_count", 0)
    errors = len(state.get("test_report", {}).get("errors", []))
    loop = state.get("loop_detected", False)
    
    # Usar Model Router
    router = get_router()
    llm = get_router_llm(router, "Programador",
                          iteration=iteration,
                          errors=errors,
                          loop_detected=loop)
    
    # Preparar directorio de ejecución
    exec_dir = EXEC_DIR / f"iter-{iteration}"
    exec_dir.mkdir(parents=True, exist_ok=True)
    
    # Fase 1: Generar código
    prompt = _build_prompt(state)
    system_prompt = PROGRAMMER_PROMPT
    
    if router.escalado >= 3:
        system_prompt = PROGRAMMER_PROMPT.replace(
            "Máximo 4096", "Máximo 8192"
        ) + "\n\nUsa todo tu conocimiento como modelo Pro."
    
    response = await safe_invoke(llm, [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ])

    content = response.content if hasattr(response, 'content') else str(response)
    # OPTIMIZACIÓN: detectar modelo real usado (no inferir de escalado)
    modelo_usado = "pro" if "deepseek-v4-pro" in str(getattr(llm, 'model', '')) else "flash"
    print(f"[Programador v3] {modelo_usado.upper()} (iter {iteration}, errs: {errors})")

    # Parsear JSON
    try:
        content_clean = content.strip()
        if content_clean.startswith("```"):
            lines = content_clean.split("\n")
            content_clean = "\n".join(lines[1:-1])
        result = json.loads(content_clean)
    except json.JSONDecodeError:
        result = {
            "source_code": {"main.py": content},
            "notas_scratchpad": ["Error parseando JSON"],
            "auto_reflection": {"checklist_passed": False, "puntos_fallidos": ["JSON mal formado"], "confianza": 0.0}
        }

    source = result.get("source_code", {})
    notas = result.get("notas_scratchpad", [])
    auto_reflection = result.get("auto_reflection", {})
    
    # ── Fase 1.5: Auto-install de dependencias detectadas ──
    if source and any(f.endswith(".py") for f in source.keys()):
        installed = _auto_install_imports(source)
        if installed:
            notas.append(f"[AutoInstall] Dependencias instaladas: {', '.join(installed)}")
    
    # Fase 2: Verificar código localmente (Bash-Native)
    verification_output = ""
    if source and any(f.endswith(".py") for f in source.keys()):
        print(f"[Programador v3] 🔍 Verificando código localmente...")
        verification_output = await _verify_code(source, exec_dir)
        
        # Si hay errores de sintaxis, intentar auto-corrección
        if "⚠️" in verification_output:
            print(f"[Programador v3] ⚠️ Errores de sintaxis detectados, auto-corrigiendo...")
            
            prompt2 = _build_prompt(state, verification_feedback=verification_output, es_autocorreccion=True)
            response2 = await safe_invoke(llm, [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt2),
            ])
            
            content2 = response2.content if hasattr(response2, 'content') else str(response2)
            try:
                content2_clean = content2.strip()
                if content2_clean.startswith("```"):
                    lines = content2_clean.split("\n")
                    content2_clean = "\n".join(lines[1:-1])
                result2 = json.loads(content2_clean)
                
                if result2.get("source_code"):
                    source = result2["source_code"]
                    notas = result2.get("notas_scratchpad", notas)
                    auto_reflection = result2.get("auto_reflection", auto_reflection)
                    print(f"[Programador v3] ✅ Auto-corrección aplicada")
                    
                    # Re-verificar
                    verification_output = await _verify_code(source, exec_dir)
            except (json.JSONDecodeError, KeyError):
                print(f"[Programador v3] ⚠️ Auto-corrección falló, usando código original")

    # Auto-reflexión final: añadir al scratchpad
    if auto_reflection:
        checklist_status = "✅ PASÓ" if auto_reflection.get("checklist_passed") else "❌ FALLÓ"
        notas.append(f"[Auto-reflexión] Checklist: {checklist_status}, "
                     f"Confianza: {auto_reflection.get('confianza', 0.0):.2f}, "
                     f"Puntos fallidos: {auto_reflection.get('puntos_fallidos', [])}")

    return {
        "source_code": source,
        "scratchpad": notas,
        "audit_trail": [{
            "nodo": f"Programador v3 ({modelo_usado})",
            "accion": "Generación + verificación local + auto-reflexión",
            "resultado": f"{len(source)} archivos, verificación: {'OK' if '⚠️' not in verification_output else 'WARN'}, "
                        f"auto-reflexión: {auto_reflection.get('checklist_passed', False)}",
        }],
    }
