"""Instalador Agent — Bootstrap de entornos y proyectos del Enjambre 4.0.

ROL:
  Configura entornos de desarrollo desde cero. Instala dependencias,
  crea archivos de configuración, inicializa bases de datos.

USO:
  python3 -m src.agents.instalador_agent '{"proyecto": "agent-swarm", "accion": "setup"}'

CAPACIDADES:
  - Crear virtualenv + instalar requirements.txt
  - Configurar .env desde template
  - Inicializar Supabase (schema, migraciones)
  - Bootstrap de proyecto nuevo (scaffolding)
  - Verificar instalación (health check de dependencias)
"""

import asyncio
import json
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import get_llm, get_budget
from langchain_core.messages import HumanMessage, SystemMessage


INSTALLER_SYSTEM_PROMPT = """Eres el Instalador del Enjambre 4.0 — Especialista en configuración de entornos.

## Tu Rol
Configuras entornos de desarrollo y producción desde cero. 
Instalas dependencias, creas configuraciones, inicializas servicios.

## Capacidades
1. Python venv + pip install
2. Node.js npm install
3. Configuración de .env
4. Inicialización de Supabase
5. Bootstrap de proyectos nuevos
6. Verificación de instalación

Responde SIEMPRE en JSON con los pasos ejecutados y su resultado."""


PROYECTOS = {
    "agent-swarm": "/Users/isabeldiaz/Dev/agent-swarm",
    "queenchat": "/Users/isabeldiaz/Dev/queenchat-agent",
    "agentes-opencode": "/Users/isabeldiaz/Dev/agentes-opencode",
}


async def setup_python(path: Path) -> dict:
    """Configura entorno Python: venv + pip install."""
    pasos = []
    errores = []
    
    # 1. Crear venv si no existe
    venv_path = path / ".venv"
    if not venv_path.exists():
        try:
            result = subprocess.run(
                ["python3", "-m", "venv", ".venv"],
                capture_output=True, text=True, cwd=path, timeout=60
            )
            if result.returncode == 0:
                pasos.append("venv: ✅ creado")
            else:
                errores.append(f"venv: {result.stderr[:200]}")
                return {"success": False, "pasos": pasos, "errores": errores}
        except Exception as e:
            return {"success": False, "error": f"python3 no disponible: {e}"}
    else:
        pasos.append("venv: ✅ ya existe")
    
    # 2. Instalar dependencias
    pip = str(venv_path / "bin" / "pip")
    req_file = path / "requirements.txt"
    
    if req_file.exists():
        try:
            result = subprocess.run(
                [pip, "install", "-r", "requirements.txt"],
                capture_output=True, text=True, cwd=path, timeout=300
            )
            if result.returncode == 0:
                pasos.append("pip install: ✅")
            else:
                last_line = result.stderr.strip().split("\n")[-1] if result.stderr else "unknown"
                pasos.append(f"pip install: ⚠️ {last_line[:200]}")
        except Exception as e:
            pasos.append(f"pip install: ❌ {str(e)[:100]}")
    else:
        pasos.append("pip install: ⚠️ no requirements.txt")
    
    # 3. Verificar imports clave
    try:
        result = subprocess.run(
            [str(venv_path / "bin" / "python3"), "-c",
             "from src.config import get_llm; print('Config OK')"],
            capture_output=True, text=True, cwd=path, timeout=15
        )
        pasos.append(f"Import check: {'✅' if result.returncode == 0 else '❌'}")
    except:
        pasos.append("Import check: ⚠️")
    
    return {
        "success": len(errores) == 0,
        "pasos": pasos,
        "errores": errores,
    }


async def setup_node(path: Path) -> dict:
    """Configura entorno Node: npm install."""
    pasos = []
    
    package_json = path / "package.json"
    if not package_json.exists():
        return {"success": True, "pasos": ["npm: ⚠️ no package.json — saltando"]}
    
    try:
        result = subprocess.run(
            ["npm", "install"], capture_output=True, text=True,
            cwd=path, timeout=180
        )
        if result.returncode == 0:
            pasos.append("npm install: ✅")
        else:
            pasos.append(f"npm install: ❌ {result.stderr[:200]}")
            return {"success": False, "pasos": pasos}
    except Exception as e:
        return {"success": False, "error": f"npm no disponible: {e}"}
    
    return {"success": True, "pasos": pasos}


async def setup_env(path: Path) -> dict:
    """Configura archivo .env desde .env.example."""
    pasos = []
    
    env_example = path / ".env.example"
    env_file = path / ".env"
    
    if env_file.exists():
        pasos.append(".env: ✅ ya existe")
        return {"success": True, "pasos": pasos}
    
    if env_example.exists():
        shutil.copy(env_example, env_file)
        pasos.append(".env: ✅ creado desde .env.example")
        pasos.append("⚠️ Revisa y completa las variables en .env manualmente")
    else:
        # Crear .env mínimo
        env_content = """# Configuración generada por Instalador Agent
# Completa los valores según tu entorno

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key

# OpenCode / LLM
OPENCODE_API_KEY=sk-your-key
OPENCODE_BASE_URL=https://opencode.ai/zen/v1
"""
        env_file.write_text(env_content)
        pasos.append(".env: ✅ creado con template mínimo")
        pasos.append("⚠️ Completa SUPABASE_URL, SUPABASE_SERVICE_KEY y OPENCODE_API_KEY")
    
    return {"success": True, "pasos": pasos}


async def setup_supabase(path: Path) -> dict:
    """Verifica conexión a Supabase."""
    pasos = []
    
    try:
        from src.supabase_utils import get_supabase
        client = get_supabase()
        # Verificar conexión con una query simple
        result = client.table("agent_memory").select("id", count="exact").limit(1).execute()
        count = result.count if hasattr(result, 'count') else "?"
        pasos.append(f"Supabase: ✅ conectado ({count} registros en agent_memory)")
    except Exception as e:
        pasos.append(f"Supabase: ⚠️ {str(e)[:150]} — verifica .env")
    
    return {"success": True, "pasos": pasos}


async def bootstrap_proyecto(nombre: str, tipo: str = "python", path_base: str = None) -> dict:
    """Crea un proyecto nuevo desde cero.
    
    Args:
        nombre: Nombre del proyecto
        tipo: "python", "node", "python+node"
        path_base: Ruta base (default: ~/Dev/)
    """
    if path_base is None:
        path_base = str(Path.home() / "Dev")
    
    path = Path(path_base) / nombre
    pasos = []
    
    if path.exists():
        return {"success": False, "error": f"El directorio {path} ya existe"}
    
    # Crear estructura
    path.mkdir(parents=True)
    pasos.append(f"mkdir {nombre}: ✅")
    
    if "python" in tipo:
        # Crear estructura Python mínima
        (path / "src").mkdir(exist_ok=True)
        (path / "src" / "__init__.py").write_text("")
        (path / "requirements.txt").write_text("# Dependencias del proyecto\n")
        (path / "main.py").write_text('"""Punto de entrada del proyecto."""\n\n\ndef main():\n    print("Hello from Enjambre 4.0!")\n\n\nif __name__ == "__main__":\n    main()\n')
        (path / ".env.example").write_text("# Variables de entorno\n")
        (path / ".gitignore").write_text(".venv/\n__pycache__/\n.env\n*.pyc\n")
        pasos.append("Python scaffold: ✅")
    
    if "node" in tipo:
        (path / "package.json").write_text(json.dumps({
            "name": nombre,
            "version": "1.0.0",
            "description": "Proyecto generado por Enjambre 4.0",
            "main": "index.js",
            "scripts": {"start": "node index.js", "build": "echo ok"},
        }, indent=2))
        (path / "index.js").write_text('console.log("Hello from Enjambre 4.0!");\n')
        pasos.append("Node scaffold: ✅")
    
    # Git init
    try:
        subprocess.run(["git", "init"], capture_output=True, cwd=path, timeout=10)
        pasos.append("git init: ✅")
    except:
        pasos.append("git init: ⚠️")
    
    # Crear AGENTS.md
    (path / "AGENTS.md").write_text(f"""# AGENTS.md — {nombre}

Proyecto generado por el Enjambre 4.0 (Smith + Instalador).

## Stack
- Lenguaje: {'Python' if 'python' in tipo else 'Node.js'}
- Agentes: agent-swarm pipeline

## Setup
```bash
{'python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt' if 'python' in tipo else ''}
{'npm install' if 'node' in tipo else ''}
```
""")
    pasos.append("AGENTS.md: ✅")
    
    return {
        "success": True,
        "pasos": pasos,
        "proyecto_path": str(path),
        "siguiente_paso": "Configura .env y ejecuta el instalador para dependencias",
    }


async def instalar(proyecto: str, accion: str = "setup") -> dict:
    """Orquesta la instalación/configuración de un proyecto.
    
    Args:
        proyecto: Nombre del proyecto ("agent-swarm", "queenchat") o ruta
        accion: "setup" (completo), "deps" (solo dependencias), "env" (solo .env),
                "verify" (solo verificar), "bootstrap" (crear nuevo)
        
    Returns:
        {"success": bool, "pasos": [...], "errores": [...]}
    """
    # Resolver proyecto
    proyecto_path = PROYECTOS.get(proyecto.lower(), proyecto)
    
    # Si es bootstrap, es un nombre nuevo
    if accion == "bootstrap":
        result = await bootstrap_proyecto(proyecto)
        result["audit"] = {"action": "bootstrap", "proyecto": proyecto}
        return result
    
    path = Path(proyecto_path).expanduser().resolve()
    
    if not path.exists():
        return {"success": False, "error": f"Proyecto no encontrado: {path}"}
    
    print(f"[Instalador Agent] 🔧 Instalando: {path.name} ({accion})")
    
    pasos_totales = []
    errores = []
    
    if accion in ("setup", "deps"):
        # Python
        py_result = await setup_python(path)
        pasos_totales.extend(py_result.get("pasos", []))
        errores.extend(py_result.get("errores", []))
        
        # Node
        node_result = await setup_node(path)
        pasos_totales.extend(node_result.get("pasos", []))
        if not node_result.get("success"):
            errores.append(node_result.get("error", "npm install falló"))
    
    if accion in ("setup", "env"):
        env_result = await setup_env(path)
        pasos_totales.extend(env_result.get("pasos", []))
    
    if accion in ("setup", "verify"):
        supabase_result = await setup_supabase(path)
        pasos_totales.extend(supabase_result.get("pasos", []))
        
        # Verificar Python imports
        venv_path = path / ".venv"
        if venv_path.exists():
            try:
                result = subprocess.run(
                    [str(venv_path / "bin" / "python3"), "-c",
                     "print('Python OK')"],
                    capture_output=True, text=True, cwd=path, timeout=10
                )
                pasos_totales.append(f"Python runtime: {'✅' if result.returncode == 0 else '❌'}")
            except:
                pasos_totales.append("Python runtime: ⚠️")
    
    return {
        "success": len(errores) == 0,
        "proyecto": path.name,
        "accion": accion,
        "pasos": pasos_totales,
        "errores": errores,
        "audit": {
            "action": "install",
            "proyecto": path.name,
            "accion": accion,
            "status": "ok" if len(errores) == 0 else "warn",
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
        print(json.dumps({"error": "No input. Provide JSON with proyecto and accion."}))
        sys.exit(1)
    
    proyecto = data.get("proyecto", "")
    accion = data.get("accion", "setup")
    
    result = asyncio.run(instalar(proyecto, accion=accion))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
