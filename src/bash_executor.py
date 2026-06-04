"""⚡ Bash Executor — Ejecución Segura de Comandos para el Programador Bash-Native.

ARQUITECTURA:
  Basado en mini-SWE-agent: usar bash como interfaz principal del agente.
  Cada acción del programador se ejecuta via subprocess.run() con:
  - Timeout para evitar loops infinitos
  - Captura completa de stdout/stderr
  - Sandboxing por directorio de trabajo
  - Validación de output

DIFERENCIA vs ejecución directa en pipeline:
  - El Tester hace pytest 'por fuera' (paralelo)
  - El BashExecutor permite al PROGRAMADOR auto-ejecutarse
  - Ciclo: escribe código → ejecuta → ve output → corrige → repite
"""

import subprocess
import logging
import os
import signal
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constantes de seguridad ──
MAX_OUTPUT_LENGTH = 10000      # Caracteres máximos de output capturado
DEFAULT_TIMEOUT = 30           # Timeout por defecto en segundos
BANNED_COMMANDS = ["rm -rf /", "dd if=", ":(){ :|:& };:", "mkfs", "format"]
MAX_COMMAND_LENGTH = 2000      # Caracteres máximos del comando


class ExecutionResult:
    """Resultado de la ejecución de un comando."""
    
    def __init__(self, success: bool, stdout: str, stderr: str,
                 returncode: int, timed_out: bool = False):
        self.success = success
        self.stdout = stdout[:MAX_OUTPUT_LENGTH]
        self.stderr = stderr[:MAX_OUTPUT_LENGTH]
        self.returncode = returncode
        self.timed_out = timed_out
    
    def __str__(self) -> str:
        status = "✅" if self.success else "❌"
        return f"{status} exit={self.returncode} | out={len(self.stdout)} chars | err={len(self.stderr)} chars"
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "stdout": self.stdout[-2000:],  # Últimos 2000 chars para contexto
            "stderr": self.stderr[-1000:],
            "returncode": self.returncode,
            "timed_out": self.timed_out,
        }


def _is_safe_command(command: str) -> bool:
    """Valida que el comando no sea peligroso."""
    command_lower = command.lower()
    for banned in BANNED_COMMANDS:
        if banned in command_lower:
            return False
    return True


async def execute_command(
    command: str,
    workdir: Optional[Path] = None,
    timeout: int = DEFAULT_TIMEOUT,
    env: Optional[dict] = None,
) -> ExecutionResult:
    """Ejecuta un comando bash y captura su output.
    
    Args:
        command: Comando a ejecutar (string)
        workdir: Directorio de trabajo (opcional)
        timeout: Timeout en segundos
        env: Variables de entorno adicionales
    
    Returns:
        ExecutionResult con stdout/stderr/returncode
    """
    # Validar seguridad
    if not _is_safe_command(command):
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"COMANDO RECHAZADO: '{command[:50]}...' no está permitido por seguridad",
            returncode=-1,
        )
    
    if len(command) > MAX_COMMAND_LENGTH:
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"Comando demasiado largo ({len(command)} chars, max {MAX_COMMAND_LENGTH})",
            returncode=-1,
        )
    
    logger.info(f"[BashExec] Ejecutando: {command[:120]}...")
    
    try:
        # Preparar entorno
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        
        # Ejecutar con timeout
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workdir) if workdir else None,
            env=exec_env,
            executable="/bin/zsh",
        )
        
        success = result.returncode == 0
        
        logger.info(f"[BashExec] {command[:80]} → {'✅' if success else '❌'} (exit={result.returncode})")
        
        return ExecutionResult(
            success=success,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            returncode=result.returncode,
        )
        
    except subprocess.TimeoutExpired:
        logger.warning(f"[BashExec] ⏱️ TIMEOUT ({timeout}s): {command[:80]}")
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"Comando timeout después de {timeout} segundos",
            returncode=-1,
            timed_out=True,
        )
    except FileNotFoundError as e:
        logger.error(f"[BashExec] ❌ Comando no encontrado: {e}")
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"Error: comando no encontrado - {e}",
            returncode=-1,
        )
    except Exception as e:
        logger.error(f"[BashExec] ❌ Error: {e}")
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"Error inesperado: {e}",
            returncode=-1,
        )


async def execute_python_code(
    code_path: Path,
    args: str = "",
    workdir: Optional[Path] = None,
    timeout: int = DEFAULT_TIMEOUT,
    venv_path: Optional[Path] = None,
) -> ExecutionResult:
    """Ejecuta un archivo Python y captura su output.
    
    Args:
        code_path: Ruta al archivo .py
        args: Argumentos de línea de comandos
        workdir: Directorio de trabajo
        timeout: Timeout en segundos
        venv_path: Ruta al virtualenv (opcional)
    
    Returns:
        ExecutionResult con stdout/stderr/returncode
    """
    python_cmd = "python3"
    if venv_path:
        python_cmd = str(venv_path / "bin" / "python3")
    
    command = f"{python_cmd} \"{code_path}\" {args}"
    return await execute_command(command, workdir=workdir, timeout=timeout)


async def run_pytest(
    test_path: Path,
    workdir: Optional[Path] = None,
    timeout: int = 60,
    verbose: bool = False,
    venv_path: Optional[Path] = None,
) -> ExecutionResult:
    """Ejecuta pytest en un archivo/directorio de tests.
    
    Args:
        test_path: Ruta al archivo/directorio de tests
        workdir: Directorio de trabajo
        timeout: Timeout en segundos
        verbose: Verbosidad
        venv_path: Ruta al virtualenv (opcional)
    
    Returns:
        ExecutionResult
    """
    python_cmd = "python3"
    if venv_path:
        python_cmd = str(venv_path / "bin" / "python3")
    
    verbose_flag = "-v" if verbose else ""
    command = f"{python_cmd} -m pytest {verbose_flag} \"{test_path}\" 2>&1"
    return await execute_command(command, workdir=workdir, timeout=timeout)


def format_output_for_llm(result: ExecutionResult, max_lines: int = 30) -> str:
    """Formatea el output de ejecución para consumo del LLM.
    
    Args:
        result: ExecutionResult
        max_lines: Máximo de líneas a incluir
    
    Returns:
        Texto formateado para inyectar en prompt del LLM
    """
    lines = []
    lines.append(f"🔧 Exit code: {result.returncode}")
    lines.append(f"⏱️ Timed out: {result.timed_out}")
    lines.append("")
    
    if result.stdout:
        stdout_lines = result.stdout.split("\n")
        if len(stdout_lines) > max_lines:
            stdout_lines = stdout_lines[:max_lines]
            stdout_lines.append(f"... ({len(result.stdout.split(chr(10)))} líneas totales)")
        lines.append("📤 STDOUT:")
        lines.extend(f"  {l}" for l in stdout_lines)
        lines.append("")
    
    if result.stderr:
        stderr_lines = result.stderr.split("\n")
        if len(stderr_lines) > max_lines:
            stderr_lines = stderr_lines[:max_lines]
            stderr_lines.append(f"... ({len(result.stderr.split(chr(10)))} líneas totales)")
        lines.append("📥 STDERR:")
        lines.extend(f"  {l}" for l in stderr_lines)
    
    return "\n".join(lines)
