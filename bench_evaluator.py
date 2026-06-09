#!/usr/bin/env python3
"""
Benchmark Evaluator — Motor de evaluación multi-dimensional para el A/B Test.
Mide calidad de código mediante análisis estático, compilación, pytest real,
y conteo de features implementadas.
"""
import re
import sys
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# FEATURE EXTRACTION
# ═══════════════════════════════════════════════════════════════════

# Keywords de features que buscamos en el código
FEATURE_SIGNATURES = {
    # Python Core
    "type_hints": [r":\s*(str|int|float|bool|list|dict|set|tuple|Optional|Union|Any)", r"->\s*\w+"],
    "docstrings": [r'"""', r"'''"],
    "error_handling": [r"try\s*:", r"except\s", r"raise\s"],
    "logging": [r"logging\.", r"logger\s*=", r"getLogger", r"import logging"],
    "if_main": [r'if\s+__name__\s*==\s*["\']__main__["\']'],
    "async": [r"async\s+def", r"await\s", r"asyncio\."],
    "argparse": [r"argparse", r"ArgumentParser"],
    "type_decorators": [r"@dataclass", r"@property", r"@staticmethod", r"@classmethod"],
    
    # Web/API
    "fastapi": [r"FastAPI", r"@app\.", r"APIRouter"],
    "flask": [r"Flask", r"@app\.route"],
    "jwt": [r"jwt", r"JWT", r"access_token", r"Bearer"],
    "sqlalchemy": [r"SQLAlchemy", r"Column\(", r"declarative_base"],
    "sqlite3": [r"sqlite3", r"\.db\b"],
    "pydantic": [r"BaseModel", r"Field\(", r"pydantic"],
    
    # Data
    "pandas": [r"pandas", r"pd\.", r"DataFrame"],
    "numpy": [r"numpy", r"np\.", r"array\("],
    "openpyxl": [r"openpyxl", r"Workbook", r"load_workbook"],
    
    # Testing
    "pytest": [r"pytest", r"def test_", r"@pytest\.", r"unittest"],
    "pytest_asyncio": [r"pytest\.mark\.asyncio", r"pytest_asyncio"],
    "httpx_test": [r"httpx", r"TestClient", r"AsyncClient"],
    
    # Infrastructure
    "docker": [r"Dockerfile", r"docker-compose", r"FROM\s"],
    "env_vars": [r"os\.getenv", r"os\.environ", r"dotenv", r"load_dotenv"],
    "click": [r"click\.", r"@click\.", r"import click"],
    
    # Enterprise/Accounting
    "puc": [r"PUC", r"cuenta\w*_contable", r"plan_unic[ao]", r"catalogo_cuentas"],
    "iva": [r"IVA", r"iva\b", r"calcular_iva", r"retefuente", r"reteICA"],
    "dian": [r"DIAN", r"formato_?\d{4}", r"informe_dian"],
    "balance": [r"BalanceGeneral", r"balance_general", r"EstadoResultados", r"flujo_caja"],
}


def extract_features_from_requirement(requirement: str) -> list:
    """Extrae lista de features esperadas del texto del requerimiento."""
    features = []
    requirement_lower = requirement.lower()
    
    feature_keywords = {
        "type_hints": ["type hints", "typehints", "tipado"],
        "docstrings": ["docstring", "documentación"],
        "error_handling": ["manejo de errores", "error handling", "try", "except"],
        "logging": ["logging", "logger", "log"],
        "tests": ["pytest", "test", "pruebas"],
        "async": ["async", "asincrono", "asyncio", "await"],
        "argparse": ["argparse", "cli", "command line", "argumentos"],
        "cli": ["cli", "comando", "argparse", "click"],
        "fastapi": ["fastapi"],
        "flask": ["flask"],
        "jwt": ["jwt", "autenticación", "auth", "token", "login", "register"],
        "sqlalchemy": ["sqlalchemy", "orm"],
        "sqlite": ["sqlite", "base de datos"],
        "pydantic": ["pydantic", "base model", "schemas"],
        "pandas": ["pandas"],
        "openpyxl": ["openpyxl", "excel", ".xlsx"],
        "docker": ["docker", "docker-compose"],
        "diagram": ["diagrama", "esquema", "erd", "entidad-relación"],
        "jwt_auth": ["jwt", "autenticación", "token"],
        "rate_limiting": ["rate limit", "rate limiting", "100 requests"],
        "watchdog": ["watchdog", "nuevos archivos", "directorio"],
        "geolocation": ["geolocalización", "geo", "ip"],
        "docker_compose": ["docker-compose", "docker compose"],
        "contabilidad": ["contabilidad", "contable", "puc", "pólizas"],
        "iva": ["iva", "retefuente", "reteica", "impuestos"],
        "dian": ["dian", "formato 1001"],
        "reportes_financieros": ["balance general", "estado de resultados", "flujo de caja"],
    }
    
    for feature, keywords in feature_keywords.items():
        if any(kw in requirement_lower for kw in keywords):
            features.append(feature)
    
    return features


# ═══════════════════════════════════════════════════════════════════
# VALIDADORES DE CÓDIGO
# ═══════════════════════════════════════════════════════════════════

def check_syntax(files: dict) -> dict:
    """Verifica sintaxis de todos los archivos .py con compile()."""
    syntax_ok = True
    errors = []
    valid_count = 0
    total_py = 0
    
    for fname, code in files.items():
        if fname.endswith('.py'):
            total_py += 1
            try:
                compile(code, fname, 'exec')
                valid_count += 1
            except SyntaxError as e:
                syntax_ok = False
                errors.append({
                    "file": fname,
                    "line": e.lineno or 0,
                    "msg": e.msg,
                    "text": e.text.strip() if e.text else ""
                })
    
    return {
        "syntax_ok": syntax_ok,
        "valid_files": valid_count,
        "total_files": total_py,
        "syntax_ok_pct": valid_count / max(total_py, 1),
        "syntax_score": valid_count / max(total_py, 1),
        "errors": errors[:10],
    }


def check_code_quality(all_code: str) -> dict:
    """Analiza calidad del código mediante firmas."""
    scores = {}
    
    for feature, patterns in FEATURE_SIGNATURES.items():
        found = 0
        for pattern in patterns:
            if re.search(pattern, all_code):
                found += 1
        scores[feature] = found / max(len(patterns), 1)
    
    return scores


def check_features_implemented(features_required: list, all_code: str) -> dict:
    """Verifica qué features del requerimiento fueron implementados."""
    results = {}
    implemented = 0
    
    for feature in features_required:
        if feature in FEATURE_SIGNATURES:
            patterns = FEATURE_SIGNATURES[feature]
            found = any(re.search(p, all_code) for p in patterns)
            results[feature] = found
            if found:
                implemented += 1
    
    return {
        "features_required": features_required,
        "features_found": results,
        "implemented_count": implemented,
        "total_count": len(features_required),
        "completitud": implemented / max(len(features_required), 1),
    }


# ═══════════════════════════════════════════════════════════════════
# TEST RUNNER (pytest real)
# ═══════════════════════════════════════════════════════════════════

def run_pytest_on_files(files: dict, timeout: int = 60) -> dict:
    """Ejecuta pytest real sobre los archivos generados."""
    has_tests = any('def test_' in code or 'import pytest' in code for code in files.values())
    if not has_tests:
        return {
            "has_tests": False,
            "tests_pass": None,
            "test_count": 0,
            "output": "No tests found in generated code",
            "passed": False,
        }
    
    with tempfile.TemporaryDirectory(prefix="bench_ab_") as tmpdir:
        # Escribir archivos
        for fname, code in files.items():
            fpath = Path(tmpdir) / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(code)
        
        # Ejecutar pytest
        try:
            r = subprocess.run(
                [sys.executable, '-m', 'pytest', tmpdir, '-x', '--tb=short', '-q', '--timeout=30'],
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            )
            passed = r.returncode == 0
            output = (r.stdout[-500:] if r.stdout else "") + (r.stderr[-500:] if r.stderr else "")
            
            # Contar tests
            test_count = 0
            for code in files.values():
                test_count += len(re.findall(r'def test_\w+', code))
            
            return {
                "has_tests": test_count > 0,
                "tests_pass": passed,
                "test_count": test_count,
                "output": output[:1000],
                "passed": passed,
                "returncode": r.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "has_tests": True,
                "tests_pass": False,
                "test_count": 0,
                "output": "TIMEOUT: pytest exceeded timeout",
                "passed": False,
                "timeout": True,
            }
        except FileNotFoundError as e:
            return {
                "has_tests": True,
                "tests_pass": False,
                "test_count": 0,
                "output": f"Error: {str(e)[:200]}",
                "passed": False,
            }


# ═══════════════════════════════════════════════════════════════════
# EVALUADOR PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

def evaluate_result(result: dict, requirement: str) -> dict:
    """
    Evaluación multi-dimensional completa de un resultado.
    
    Args:
        result: Dict con {"files": {"file.py": "code"...}, "system": str, ...}
        requirement: Texto original del requerimiento
    
    Returns:
        Dict con scores, métricas, y análisis detallado
    """
    files = result.get("files", {})
    all_code = '\n'.join(files.values()) if files else ''
    
    t0 = time.time()
    
    # 1. Análisis sintáctico
    syntax = check_syntax(files)
    
    # 2. Calidad del código
    quality = check_code_quality(all_code)
    
    # 3. Features implementadas
    features_required = extract_features_from_requirement(requirement)
    features = check_features_implemented(features_required, all_code)
    
    # 4. Tests
    tests = run_pytest_on_files(files, timeout=60)
    
    # 5. Métricas generales
    total_lines = len(all_code.split('\n')) if all_code else 0
    total_chars = len(all_code)
    
    # 6. Cómputo de score compuesto
    # Sintaxis (15%)
    score_syntax = syntax["syntax_score"]
    
    # Tests (20%)
    if tests["has_tests"]:
        if tests["tests_pass"]:
            score_tests = 1.0
        else:
            # Penalizado: algunos tests, pero no pasan
            score_tests = max(0.3, tests.get("test_count", 0) / 10)
    else:
        score_tests = 0.0
    
    # Type Hints (5%)
    score_type_hints = quality.get("type_hints", 0.0)
    
    # Docstrings (5%)
    score_docstrings = quality.get("docstrings", 0.0)
    
    # Error Handling (5%)
    score_error = quality.get("error_handling", 0.0)
    
    # Logging (5%)
    score_logging = quality.get("logging", 0.0)
    
    # Estructura (5%) — cantidad de archivos
    expected_files = max(1, requirement.count(".py") + 
                          requirement.count("docker-compose") +
                          requirement.count("requirements") +
                          requirement.count("schema.sql"))
    actual_files = len(files)
    score_estructura = min(1.0, actual_files / max(expected_files, 1))
    
    # Completitud funcional (20%)
    score_completitud = features["completitud"]
    
    # Bonus: si tiene async (solo si el req lo pide)
    bonus = 0.0
    if "async" in features_required and quality.get("async", 0) > 0:
        bonus += 0.05
    if "docker" in features_required and quality.get("docker", 0) > 0:
        bonus += 0.05
    
    # Score final
    weights = {
        "syntax": 0.15,
        "tests": 0.20,
        "type_hints": 0.05,
        "docstrings": 0.05,
        "error_handling": 0.05,
        "logging": 0.05,
        "estructura": 0.05,
        "completitud": 0.20,
    }
    
    raw_score = sum([
        score_syntax * weights["syntax"],
        score_tests * weights["tests"],
        score_type_hints * weights["type_hints"],
        score_docstrings * weights["docstrings"],
        score_error * weights["error_handling"],
        score_logging * weights["logging"],
        score_estructura * weights["estructura"],
        score_completitud * weights["completitud"],
    ])
    
    # Bonus (máximo 0.1)
    final_score = min(1.0, raw_score + bonus)
    
    elapsed = time.time() - t0
    
    return {
        "score": round(final_score, 4),
        "raw_score": round(raw_score, 4),
        "bonus": round(bonus, 4),
        "dimensions": {
            "syntax": {"score": score_syntax, "weight": weights["syntax"], "detail": f"{syntax['valid_files']}/{syntax['total_files']} archivos OK"},
            "tests": {"score": score_tests, "weight": weights["tests"], "detail": f"{'PASS' if tests.get('tests_pass') else 'FAIL'} ({tests.get('test_count', 0)} tests)" if tests.get('has_tests') else "No tests"},
            "type_hints": {"score": score_type_hints, "weight": weights["type_hints"], "detail": "OK" if score_type_hints > 0 else "Missing"},
            "docstrings": {"score": score_docstrings, "weight": weights["docstrings"], "detail": "OK" if score_docstrings > 0 else "Missing"},
            "error_handling": {"score": score_error, "weight": weights["error_handling"], "detail": "OK" if score_error > 0 else "Missing"},
            "logging": {"score": score_logging, "weight": weights["logging"], "detail": "OK" if score_logging > 0 else "Missing"},
            "estructura": {"score": score_estructura, "weight": weights["estructura"], "detail": f"{actual_files}/{expected_files} archivos"},
            "completitud": {"score": score_completitud, "weight": weights["completitud"], "detail": f"{features['implemented_count']}/{features['total_count']} features"},
        },
        "syntax": syntax,
        "quality": quality,
        "features": features,
        "tests": tests,
        "metrics": {
            "files": len(files),
            "expected_files": expected_files,
            "lines": total_lines,
            "chars": total_chars,
        },
        "eval_time_ms": round(elapsed * 1000),
    }


def estimate_cost(result: dict) -> dict:
    """
    Estima costo de una ejecución.
    
    Path A (Enjambre): flash (Zen) es GRATIS, solo gates Pro cuestan
    Path B (Builder):  Pro cuesta $1.74/1M input, $3.48/1M output
    """
    system = result.get("system", "")
    
    if system == "enjambre_4.0":
        # Enjambre: flash es gratis (Zen), solo Pro cuesta
        pro_calls = result.get("pro_calls", 0)
        # Estimación: ~$0.002 por call Pro (average)
        cost_pro = pro_calls * 0.002
        flash_calls = result.get("llm_calls", 0) - pro_calls
        return {
            "total_usd": round(cost_pro, 6),
            "pro_calls": pro_calls,
            "flash_calls": max(flash_calls, 0),
            "is_free": cost_pro < 0.001,
            "detail": f"{max(flash_calls, 0)} flash (gratis) + {pro_calls} pro = ${cost_pro:.6f}",
        }
    else:
        # Builder: Pro puro
        # Estimación conservadora basada en chars
        total_chars = result.get("total_chars", 0)
        # Ratio chars->tokens ~4:1
        est_tokens = total_chars // 4
        # Costo Pro: $1.74 input + $3.48 output, avg ~$2.61/1M
        cost_pro = est_tokens * 2.61 / 1_000_000
        pro_calls = result.get("pro_calls", 1)
        flash_calls = result.get("flash_calls", 0)
        return {
            "total_usd": round(cost_pro, 6),
            "pro_calls": pro_calls,
            "flash_calls": flash_calls,
            "is_free": False,
            "detail": f"{flash_calls} flash + {pro_calls} pro = ${cost_pro:.6f}",
        }
