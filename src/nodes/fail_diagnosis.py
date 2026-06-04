"""Nodo de Auto-Fallo con Diagnóstico — Hard Cap inteligente.

Cuando el pipeline excede el hard cap de iteraciones, este nodo:
1. Analiza el historial completo de la ejecución
2. Identifica patrones de error recurrentes
3. Determina qué se intentó y qué NO se intentó
4. Genera un reporte de diagnóstico detallado
5. Sugiere qué cambiar para la próxima ejecución

Se ejecuta UNA SOLA VEZ, cuando el hard cap es alcanzado.
"""

import json
from datetime import datetime
from src.state import TeamState


async def fail_diagnosis_node(state: TeamState) -> dict:
    """Analiza el historial de iteraciones y genera diagnóstico completo."""
    print(f"[FailDiagnosis] 🔍 Analizando causas de fallo...")

    audit = state.get("audit_trail", [])
    scratchpad = state.get("scratchpad", [])
    test_report = state.get("test_report", {})
    source_code = state.get("source_code", {})
    requirement = state.get("user_requirement", "")
    iterations = state.get("iteration_count", 0)

    # ── 1. Extraer errores de cada iteración ──
    errores_por_iter = {}
    errores_recurrentes = {}

    for entry in audit:
        nodo = entry.get("nodo", "?")
        resultado = entry.get("resultado", "")

        # Extraer información de resultados FAIL
        if "FAIL" in resultado or "error" in resultado.lower():
            # Extraer descripción del error
            if nodo not in errores_por_iter:
                errores_por_iter[nodo] = []
            errores_por_iter[nodo].append(resultado)

            # Buscar patrones comunes en las descripciones
            palabras = resultado.lower().split()
            for palabra in palabras:
                if len(palabra) > 5:
                    errores_recurrentes[palabra] = errores_recurrentes.get(palabra, 0) + 1

    # ── 2. Extraer errores específicos del tester ──
    errors_from_tests = []
    for s in scratchpad:
        if "pytest" in s.lower() or "error" in s.lower() or "fail" in s.lower():
            errors_from_tests.append(s)

    # ── 3. Identificar top errores recurrentes ──
    top_errores = sorted(errores_recurrentes.items(), key=lambda x: -x[1])[:10]

    # ── 4. Identificar qué NO se intentó ──
    tecnicas_usadas = set()
    for s in scratchpad:
        s_lower = s.lower()
        if "refactor" in s_lower: tecnicas_usadas.add("refactorización")
        if "test" in s_lower or "pytest" in s_lower: tecnicas_usadas.add("cambios en tests")
        if "import" in s_lower: tecnicas_usadas.add("corrección de imports")
        if "type" in s_lower or "tipado" in s_lower: tecnicas_usadas.add("tipado")
        if "docstring" in s_lower: tecnicas_usadas.add("docstrings")
        if "error" in s_lower: tecnicas_usadas.add("manejo de errores")
        if "instalar" in s_lower or "pip" in s_lower or "dependencia" in s_lower:
            tecnicas_usadas.add("instalación de dependencias")

    tecnicas_no_usadas = []
    if "refactorización" not in tecnicas_usadas:
        tecnicas_no_usadas.append("refactorización completa del módulo problemático")
    if "cambios en tests" not in tecnicas_usadas:
        tecnicas_no_usadas.append("reescritura de tests desde cero")
    if "instalación de dependencias" not in tecnicas_usadas:
        tecnicas_no_usadas.append("verificar/instalar dependencias faltantes")
    if "corrección de imports" not in tecnicas_usadas:
        tecnicas_no_usadas.append("revisar imports y estructura de módulos")

    # ── 5. Generar diagnóstico ──
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    diagnosis = f"""# 🔴 Diagnóstico de Falla - Enjambre de Desarrollo

**Generado:** {ahora}
**Requerimiento:** {requirement[:200]}
**Iteraciones ejecutadas:** {iterations}
**Hard cap:** Alcanzado

---

## 📋 Resumen de la Ejecución

El pipeline ejecutó {iterations} iteraciones sin lograr un resultado PASS.
Se utilizaron {len(audit)} pasos en total a través de los diferentes nodos.

---

## 🔍 Patrones de Error Recurrentes

Los siguientes términos aparecieron con mayor frecuencia en los reportes de error:

| Término | Frecuencia |
|---------|-----------|
"""

    for termino, freq in top_errores[:8]:
        diagnosis += f"| `{termino}` | {freq} veces |\n"

    diagnosis += f"""
---

## 🧪 Errores Detectados por el Sistema de Tests

"""

    if errors_from_tests:
        for e in errors_from_tests[:5]:
            diagnosis += f"- {e[:200]}\n"
    else:
        diagnosis += "(no se capturaron errores específicos de tests)\n"

    diagnosis += f"""
---

## 📝 Historial de Acciones (Scratchpad)

"""

    for s in scratchpad[-8:]:
        diagnosis += f"- {s[:150]}\n"

    diagnosis += f"""
---

## 💡 Técnicas NO Intentadas

Las siguientes estrategias NO fueron probadas durante las iteraciones y podrían
ser relevantes para resolver el problema:

"""

    if tecnicas_no_usadas:
        for t in tecnicas_no_usadas:
            diagnosis += f"- **{t}**\n"
    else:
        diagnosis += "(se intentaron la mayoría de las técnicas disponibles)\n"

    diagnosis += f"""

---

## 📁 Archivos Generados ({len(source_code)})

"""

    for fname in source_code.keys():
        diagnosis += f"- `{fname}`\n"

    diagnosis += f"""

---

## 🎯 Recomendación

1. Revisar los errores recurrentes identificados arriba
2. Considerar las técnicas no intentadas
3. Si el problema persiste, considerar:
   - Dividir el requerimiento en sub-tareas más pequeñas
   - Proporcionar ejemplos concretos de la salida esperada
   - Verificar que las dependencias necesarias estén disponibles

---

*Diagnóstico generado automáticamente por el sistema de Auto-Fallo del Enjambre*
"""

    # Guardar diagnóstico como archivo
    diagnostic_files = dict(source_code)
    diagnostic_files["_FAIL_DIAGNOSIS.md"] = diagnosis

    print(f"[FailDiagnosis] ✅ Diagnóstico generado ({len(diagnosis)} chars)")
    print(f"[FailDiagnosis]    {len(top_errores)} patrones de error detectados")
    print(f"[FailDiagnosis]    {len(errors_from_tests)} errores de tests")
    print(f"[FailDiagnosis]    {len(tecnicas_no_usadas)} técnicas no intentadas")

    return {
        "source_code": diagnostic_files,
        "test_report": {
            "status": "FAIL",
            "errors": [
                f"Hard cap de {iterations} iteraciones alcanzado",
                f"Patrones recurrentes: {', '.join(t for t, _ in top_errores[:3])}",
                f"Técnicas no intentadas: {', '.join(tecnicas_no_usadas) or 'ninguna'}",
            ],
        },
        "scratchpad": [
            f"[FailDiagnosis] Hard cap alcanzado en iteración {iterations}",
            f"[FailDiagnosis] Diagnóstico generado: _FAIL_DIAGNOSIS.md",
            f"[FailDiagnosis] Recomendación: revisar técnicas no intentadas",
        ],
        "audit_trail": [{
            "nodo": "Fail Diagnosis",
            "accion": "Auto-fallo con diagnóstico",
            "resultado": f"Diagnóstico generado — {len(diagnosis)} chars, {len(top_errores)} patrones",
        }],
        "diagnosis_details": {
            "pattern_terms": [t for t, _ in top_errores[:8]],
            "untried_techniques": tecnicas_no_usadas,
            "error_count": len(errors_from_tests),
            "diagnosis_length": len(diagnosis),
        },
    }
