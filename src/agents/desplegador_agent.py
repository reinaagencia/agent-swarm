"""Desplegador Agent — Automatización de despliegues del Enjambre 4.0.

ROL:
  Automatiza el despliegue de proyectos a producción.
  Soporta Railway (git push), Docker, y chequeos de salud.

USO:
  python3 -m src.agents.desplegador_agent '{"proyecto": "queenchat-agent", "entorno": "railway"}'

ESTRATEGIAS DE DEPLOY:
  - Railway: git add + commit + push → build automático
  - Docker: docker build + docker run (local)
  - Verify: solo health check, sin deploy
"""

import asyncio
import json
import sys
import subprocess
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import get_llm, get_budget
from langchain_core.messages import HumanMessage, SystemMessage


DEPLOYER_SYSTEM_PROMPT = """Eres el Desplegador del Enjambre 4.0 — Especialista en DevOps y despliegues.

## Tu Rol
Automatizas el despliegue de proyectos a producción. Diagnosticas el estado actual,
detectas el método de deploy correcto, y ejecutas los pasos necesarios.

## Estrategias de Deploy

### Railway (git push)
1. Verificar git status limpio
2. Build local (npm build / python check)
3. git add + commit + push origin main
4. Verificar railway status
5. Health check al endpoint

### Docker
1. Verificar Dockerfile existe
2. docker build -t <nombre> .
3. docker run -d -p <puerto>:<puerto> <nombre>
4. Health check

### Verify (sin deploy)
1. Chequear que el proyecto compila
2. Verificar tests pasan
3. Reportar estado

Responde SIEMPRE en JSON con el plan de deploy y los comandos a ejecutar."""


async def _check_health(url: str, max_retries: int = 5, delay: float = 3.0) -> dict:
    """Verifica que un endpoint responda después del deploy."""
    import urllib.request
    import urllib.error
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Smith-Deployer/1.0"})
            response = urllib.request.urlopen(req, timeout=10)
            return {
                "status": "healthy",
                "code": response.getcode(),
                "url": url,
                "attempt": attempt + 1,
            }
        except urllib.error.HTTPError as e:
            if attempt == max_retries - 1:
                return {"status": "unhealthy", "code": e.code, "url": url, "error": str(e)}
        except Exception as e:
            if attempt == max_retries - 1:
                return {"status": "unreachable", "url": url, "error": str(e)[:200]}
        
        time.sleep(delay)
    
    return {"status": "timeout", "url": url}


async def desplegar_railway(proyecto_path: str, mensaje_commit: str = "",
                            verificar: bool = True) -> dict:
    """Despliega un proyecto a Railway vía git push."""
    path = Path(proyecto_path).expanduser().resolve()
    
    if not path.exists():
        return {"success": False, "error": f"Ruta no encontrada: {path}"}
    
    pasos = []
    errores = []
    
    # 1. Verificar git
    try:
        result = subprocess.run(
            ["git", "status", "--short"], capture_output=True, text=True,
            cwd=path, timeout=10
        )
        cambios = result.stdout.strip()
        pasos.append(f"git status: {len(cambios.split(chr(10))) if cambios else 0} archivos modificados")
    except Exception as e:
        return {"success": False, "error": f"git no disponible en {path}: {e}"}
    
    if not cambios:
        return {
            "success": True,
            "deployed": False,
            "reason": "No hay cambios para desplegar",
            "pasos": pasos,
        }
    
    # 2. Build local si existe
    build_ok = True
    if (path / "package.json").exists():
        try:
            result = subprocess.run(
                ["npm", "run", "build"], capture_output=True, text=True,
                cwd=path, timeout=120
            )
            if result.returncode == 0:
                pasos.append("npm build: ✅")
            else:
                pasos.append(f"npm build: ❌ {result.stderr[:200]}")
                build_ok = False
                errores.append(f"Build falló: {result.stderr[:200]}")
        except Exception as e:
            pasos.append(f"npm build: ⚠️ {str(e)[:100]}")
    
    if not build_ok:
        return {"success": False, "error": "Build local falló", "pasos": pasos, "errores": errores}
    
    # 3. Commit
    mensaje = mensaje_commit or f"deploy: {time.strftime('%Y-%m-%d %H:%M')}"
    try:
        subprocess.run(["git", "add", "."], capture_output=True, cwd=path, timeout=10)
        result = subprocess.run(
            ["git", "commit", "-m", mensaje], capture_output=True, text=True,
            cwd=path, timeout=10
        )
        pasos.append(f"git commit: {result.stdout.strip()[:200]}")
    except Exception as e:
        errores.append(f"Commit falló: {str(e)[:200]}")
        return {"success": False, "error": f"git commit falló: {e}", "pasos": pasos}
    
    # 4. Push
    try:
        result = subprocess.run(
            ["git", "push", "origin", "main"], capture_output=True, text=True,
            cwd=path, timeout=60
        )
        if result.returncode == 0:
            pasos.append("git push: ✅ Deploy disparado")
        else:
            pasos.append(f"git push: ⚠️ {result.stderr[:200]}")
            errores.append(f"Push falló: {result.stderr[:200]}")
    except Exception as e:
        errores.append(f"Push falló: {str(e)[:200]}")
        return {"success": False, "error": f"git push falló: {e}", "pasos": pasos}
    
    # 5. Health check (si hay URL configurada)
    health = None
    if verificar:
        # Buscar URL en railway.json o similar
        railway_config = path / "railway.json"
        url = None
        if railway_config.exists():
            try:
                config = json.loads(railway_config.read_text())
                url = config.get("url") or config.get("healthCheckUrl")
            except:
                pass
        
        if url:
            health = await _check_health(url)
            pasos.append(f"Health check: {health['status']}")
    
    return {
        "success": len(errores) == 0,
        "deployed": True,
        "mensaje_commit": mensaje,
        "pasos": pasos,
        "errores": errores if errores else [],
        "health": health,
    }


async def desplegar(proyecto: str, entorno: str = "railway",
                    mensaje: str = "", verificar: bool = True) -> dict:
    """Orquesta un despliegue completo.
    
    Args:
        proyecto: Ruta al proyecto o alias ("queenchat", "agent-swarm", etc.)
        entorno: "railway", "docker", "verify"
        mensaje: Mensaje de commit personalizado
        verificar: Si hacer health check post-deploy
        
    Returns:
        {"success": bool, "deployed": bool, "pasos": [...], "health": {...}}
    """
    # Resolver alias de proyectos
    PROYECTOS = {
        "queenchat": "/Users/isabeldiaz/Dev/queenchat-agent",
        "agent-swarm": "/Users/isabeldiaz/Dev/agent-swarm",
        "agentes-opencode": "/Users/isabeldiaz/Dev/agentes-opencode",
    }
    
    proyecto_path = PROYECTOS.get(proyecto.lower(), proyecto)
    
    print(f"[Desplegador Agent] 🚀 Deploy: {proyecto} → {entorno}")
    print(f"  Path: {proyecto_path}")
    
    if entorno == "railway":
        result = await desplegar_railway(proyecto_path, mensaje, verificar)
    elif entorno == "docker":
        result = await _desplegar_docker(proyecto_path)
    elif entorno == "verify":
        result = await _verificar_proyecto(proyecto_path)
    else:
        result = {"success": False, "error": f"Entorno no soportado: {entorno}"}
    
    result["audit"] = {
        "action": "deploy",
        "proyecto": proyecto,
        "entorno": entorno,
        "timestamp": time.time(),
        "status": "ok" if result.get("success") else "error",
    }
    
    return result


async def _desplegar_docker(proyecto_path: str) -> dict:
    """Despliega con Docker."""
    path = Path(proyecto_path).expanduser().resolve()
    pasos = []
    
    dockerfile = path / "Dockerfile"
    if not dockerfile.exists():
        return {"success": False, "error": "No se encontró Dockerfile"}
    
    nombre = path.name
    
    # Build
    try:
        result = subprocess.run(
            ["docker", "build", "-t", nombre, "."],
            capture_output=True, text=True, cwd=path, timeout=180
        )
        if result.returncode == 0:
            pasos.append(f"docker build: ✅ {nombre}")
        else:
            return {"success": False, "error": f"Build falló: {result.stderr[:300]}", "pasos": pasos}
    except Exception as e:
        return {"success": False, "error": f"Docker no disponible: {e}"}
    
    # Run
    try:
        # Detener contenedor anterior si existe
        subprocess.run(["docker", "stop", nombre], capture_output=True, timeout=10)
        subprocess.run(["docker", "rm", nombre], capture_output=True, timeout=5)
        
        result = subprocess.run(
            ["docker", "run", "-d", "--name", nombre, "-p", "8080:8080", nombre],
            capture_output=True, text=True, cwd=path, timeout=30
        )
        if result.returncode == 0:
            pasos.append(f"docker run: ✅ {nombre} (puerto 8080)")
        else:
            pasos.append(f"docker run: ⚠️ {result.stderr[:200]}")
    except Exception as e:
        pasos.append(f"docker run: ❌ {str(e)[:100]}")
    
    return {"success": True, "deployed": True, "pasos": pasos}


async def _verificar_proyecto(proyecto_path: str) -> dict:
    """Verifica que un proyecto está listo para deploy sin desplegarlo."""
    path = Path(proyecto_path).expanduser().resolve()
    checks = []
    all_ok = True
    
    # Python project
    if (path / "requirements.txt").exists() or (path / "pyproject.toml").exists():
        try:
            result = subprocess.run(
                ["python3", "-c", "import compileall; compileall.compile_dir('.', quiet=1)"],
                capture_output=True, text=True, cwd=path, timeout=30
            )
            checks.append(f"Python compile: {'✅' if result.returncode == 0 else '❌'}")
            if result.returncode != 0:
                all_ok = False
        except:
            checks.append("Python compile: ⚠️ no disponible")
    
    # Node project
    if (path / "package.json").exists():
        try:
            result = subprocess.run(
                ["npm", "run", "build", "--if-present"],
                capture_output=True, text=True, cwd=path, timeout=120
            )
            checks.append(f"npm build: {'✅' if result.returncode == 0 else '❌'}")
            if result.returncode != 0:
                all_ok = False
        except:
            checks.append("npm build: ⚠️ no disponible")
    
    # Git status
    try:
        result = subprocess.run(
            ["git", "status", "--short"], capture_output=True, text=True,
            cwd=path, timeout=10
        )
        cambios = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        checks.append(f"Git cambios sin commit: {cambios}")
    except:
        checks.append("Git: ⚠️ no disponible")
    
    return {
        "success": all_ok,
        "deployed": False,
        "verificacion": "ok" if all_ok else "issues",
        "checks": checks,
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
        print(json.dumps({"error": "No input. Provide JSON with proyecto and entorno."}))
        sys.exit(1)
    
    proyecto = data.get("proyecto", "")
    entorno = data.get("entorno", "railway")
    mensaje = data.get("mensaje", "")
    verificar = data.get("verificar", True)
    
    result = asyncio.run(desplegar(proyecto, entorno=entorno, mensaje=mensaje, verificar=verificar))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
