"""Auto-generación de skills — Fase 4: Aprendizaje Autónomo.
Refinado: keywords semánticos, patterns reales, exclusión de falsos positivos.

Cuando un mismo tipo de tarea (task_type) se completa exitosamente 3+ veces,
el sistema genera automáticamente un SKILL.md que captura el patrón común.

La skill se guarda en ~/.agents/skills/dev/auto_<task_type>/SKILL.md
y queda disponible para futuras ejecuciones del Skill Resolver.
"""

import json
import os
import re
from pathlib import Path

from src.metrics import get_recent_runs, get_summary

SKILLS_DIR = Path.home() / ".agents" / "skills" / "dev"
MIN_SUCCESSFUL_RUNS = 3

# Palabras demasiado genéricas que no deben ser keywords de skills
STOP_WORDS = {
    # Español
    "crea", "un", "una", "que", "de", "en", "con", "para", "el", "la",
    "los", "las", "del", "por", "como", "más", "pero", "sus", "son",
    "este", "esta", "entre", "todo", "tiene", "ser", "fue", "era",
    "hace", "puede", "han", "sea", "sido", "dice", "sino",
    # Inglés
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "as", "is", "was", "are",
    "were", "been", "be", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "shall",
    "this", "that", "these", "those", "it", "its", "they", "them",
    # Programación genérica
    "función", "funcion", "function", "método", "metodo", "method",
    "clase", "class", "archivo", "file", "código", "codigo", "code",
    "usar", "usa", "usando", "crear", "crea", "hacer", "haz",
    "necesito", "quiero", "debe", "deben", "puede", "pueden",
    "incluye", "incluir", "tiene", "tener",
}


def _skill_exists(task_type: str) -> bool:
    """Verifica si ya existe una skill para este task_type."""
    clean = task_type.replace("_exitoso", "").replace("_benchmark", "")
    skill_name = f"auto_{clean}" if not clean.startswith("auto_") else clean
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    return skill_path.exists()


def _extract_keywords(requirements: list[str]) -> list[str]:
    """Extrae keywords semánticas de los requirements de muestra.
    
    Mejorado: evita nombres de funciones específicos, extrae conceptos
    generales del dominio de la tarea.
    """
    all_words = []
    for req in requirements:
        # Limpiar: quitar nombres de funciones específicos (parentesis)
        req_clean = re.sub(r'\w+\(', '', req)
        # Quitar paréntesis, comas, puntos
        req_clean = re.sub(r'[\(\),\.\']', ' ', req_clean)
        words = req_clean.lower().split()
        all_words.extend(words)

    # Contar frecuencia
    freq = {}
    for w in all_words:
        if w in STOP_WORDS or len(w) < 4:
            continue
        # Saltar números
        if w.isdigit():
            continue
        # Saltar palabras que parecen nombres de funciones (contienen guión bajo)
        if '_' in w and not any(kw in w for kw in ['api', 'rest', 'cli', 'csv', 'json', 'auth']):
            continue
        freq[w] = freq.get(w, 0) + 1

    # Ordenar por frecuencia y tomar las más representativas
    sorted_words = sorted(freq.items(), key=lambda x: -x[1])

    # Tomar palabras que aparecen en AL MENOS 2 requirements
    keywords = [w for w, f in sorted_words if f >= 2][:6]

    # Si no hay palabras con frecuencia >=2, tomar las más frecuentes
    if not keywords and sorted_words:
        keywords = [w for w, f in sorted_words[:6]]

    return keywords


def _extract_patterns(requirements: list[str]) -> list[str]:
    """Extrae patrones de frase completos representativos."""
    patterns = []
    for req in requirements:
        # Limpiar
        clean = req.strip().rstrip('.')
        if clean and len(clean) > 15 and len(clean) < 80:
            patterns.append(f'"{clean}"')
    return patterns[:3]


def _generate_skill_content(pattern: dict) -> str:
    """Genera el contenido de SKILL.md con keywords y patterns mejorados."""
    task_type = pattern["task_type"]
    domain = task_type.replace("_exitoso", "").replace("_benchmark", "").replace("_", " ").title()
    skills_used = pattern.get("skills_used", [])
    samples = pattern.get("sample_requirements", [])

    # Keywords semánticas (sin nombres de funciones específicos)
    keywords = _extract_keywords(samples)

    # Patterns reales (frases completas de los requirements)
    patterns = _extract_patterns(samples)

    # Exclude words (para evitar falsos positivos)
    exclude_words = []
    if "cli" in task_type:
        exclude_words = ["api", "flask", "web", "dashboard", "database"]
    elif "api" in task_type or "rest" in task_type:
        exclude_words = ["script", "cli", ".csv", "consola"]
    elif "pipeline" in task_type or "data" in task_type:
        exclude_words = ["función", "funcion"]
    elif "notebooklm" in task_type or "notebook" in task_type or "conversacion" in task_type:
        exclude_words = ["api", "flask", "script", "cli", "database", "servidor", "deploy"]
    elif "skill" in task_type or "refiner" in task_type:
        exclude_words = ["api", "web", "dashboard", "flask", "deploy"]

    # Rules: referencias a skills base
    rules = []
    seen = set()
    for sk in skills_used:
        if sk not in seen and not sk.startswith("auto_"):
            rules.append(f"Seguir las reglas definidas en la skill {sk}")
            seen.add(sk)

    # Si no hay rules de skills base, agregar reglas genéricas
    if not rules:
        rules.append("Escribir código limpio, tipado y con docstrings")
        rules.append("Incluir tests pytest para todos los módulos")
        rules.append("Manejar errores y casos borde")

    # Construir YAML de triggers
    kw_yaml = ", ".join(f'"{k}"' for k in keywords) if keywords else '"python", "script"'
    pat_yaml = ", ".join(patterns) if patterns else '"tarea genérica"'
    excl_yaml = ", ".join(f'"{w}"' for w in exclude_words) if exclude_words else ""

    rules_yaml = "\n".join(f'  - "{r}"' for r in rules)

    now = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')
    run_count = pattern['count']

    return f"""# Auto-Skill: {domain}

> Generada automáticamente por el Enjambre de Desarrollo
> Basada en {run_count} ejecuciones exitosas del tipo `{task_type}`
> Generada el {now}

## triggers

```yaml
keywords: [{kw_yaml}]
patterns: [{pat_yaml}]
{f'exclude: [{excl_yaml}]' if excl_yaml else '# exclude: []'}
```

## rules

```yaml
{rules_yaml}
```

## blueprint

```yaml
description: >
  Patrón aprendido automáticamente para tareas de tipo {domain}.
  Basado en {run_count} ejecuciones exitosas con las skills:
  {', '.join(skills_used[:5])}.
tech_decisions:
  - Usar la estructura de archivos estándar del ecosistema
  - Priorizar módulos pequeños, testeables y con responsabilidad única
```

## code

```yaml
templates:
  - name: "{domain.lower().replace(' ', '_')}_template"
    description: "Estructura base aprendida para tareas {domain}"
libraries:
  - Usar solo la biblioteca estándar cuando sea posible
  - Para tareas específicas, usar las dependencias recomendadas por las skills base
```

## checks

```yaml
validation_checks:
  - category: "Estructural"
    checks:
      - "[ ] La solución sigue el patrón aprendido para {domain}"
      - "[ ] Todos los archivos tienen tests asociados"
      - "[ ] El código maneja errores correctamente"
      - "[ ] No hay dependencias externas innecesarias"
  - category: "Calidad"
    checks:
      - "[ ] El código es legible y mantenible"
      - "[ ] Los tests cubren casos borde"
```

*Skill auto-generada | {run_count} ejecuciones | {now}*
"""


def _check_and_fix_overlapping(skill_name: str, content: str) -> str:
    """Verifica si una skill nueva solapa con skills existentes y
    agrega exclude words si es necesario."""
    # Skills existentes que podrían solapar
    overlap_map = {
        "auto_cli": "api, flask, web, dashboard",
        "auto_api": "script, cli, consola",
        "auto_ecosystem": "api, flask, web, database",
    }

    for key, excludes in overlap_map.items():
        if key in skill_name:
            # Verificar si ya tiene exclude
            if "exclude:" not in content:
                # Agregar exclude
                content = content.replace(
                    "# exclude: []",
                    f"exclude: [{', '.join(f'\"{e.strip()}\"' for e in excludes.split(','))}]"
                )
    return content


def _find_repeatable_patterns() -> list[dict]:
    """Analiza ejecuciones recientes y encuentra patrones repetidos (3+ veces)."""
    runs = get_recent_runs(days=30)
    
    # Agrupar por task_type
    from collections import defaultdict
    groups = defaultdict(list)
    for run in runs:
        tt = run.get("task_type", "unknown")
        if run.get("status") == "PASS" and tt != "unknown":
            groups[tt].append(run)
    
    patterns = []
    for task_type, task_runs in groups.items():
        if len(task_runs) >= MIN_SUCCESSFUL_RUNS:
            # Extraer skills usadas
            skills_used = set()
            samples = []
            for r in task_runs:
                for sk in r.get("skills_activated", []):
                    skills_used.add(sk)
                req = r.get("requirement_summary", "")
                if req:
                    samples.append(req)
            
            patterns.append({
                "task_type": task_type,
                "count": len(task_runs),
                "skills_used": sorted(skills_used),
                "sample_requirements": samples[:10],
            })
    
    return patterns


def generate_skills():
    """Escanea patrones repetidos y genera skills si es necesario."""
    patterns = _find_repeatable_patterns()
    generated = []

    for pattern in patterns:
        task_type = pattern["task_type"]
        clean_name = task_type.replace("_exitoso", "").replace("_benchmark", "")
        skill_name = f"auto_{clean_name}"
        skill_dir = SKILLS_DIR / skill_name
        skill_path = skill_dir / "SKILL.md"

        skill_dir.mkdir(parents=True, exist_ok=True)

        content = _generate_skill_content(pattern)
        content = _check_and_fix_overlapping(skill_name, content)

        with open(skill_path, "w") as f:
            f.write(content)

        generated.append(skill_name)
        print(f"[SkillGenerator] ✅ Nueva skill: {skill_name}")
        print(f"[SkillGenerator]    Tipo: {task_type}")
        print(f"[SkillGenerator]    Keywords: {_extract_keywords(pattern.get('sample_requirements', []))}")
        print(f"[SkillGenerator]    Basada en: {pattern['count']} ejecuciones")

    return generated


def check_and_generate() -> list[str]:
    """Wrapper para llamar desde el Extractor."""
    try:
        return generate_skills()
    except Exception as e:
        print(f"[SkillGenerator] ⚠️ Error: {e}")
        return []


def auto_refine_all_skills():
    """Refina todas las skills auto-generadas existentes: actualiza triggers,
    agrega exclude words, mejora patterns."""
    refined = []
    for skill_dir in sorted(SKILLS_DIR.glob("auto_*/SKILL.md")):
        skill_name = skill_dir.parent.name
        try:
            with open(skill_dir) as f:
                content = f.read()

            # Verificar si necesita refinamiento
            needs_refine = False
            changes = []

            # 1. Agregar exclude si no tiene
            if "exclude:" not in content:
                overlap_map = {
                    "auto_cli": "api, flask, web, dashboard",
                    "auto_api": "script, cli, consola",
                    "auto_ecosystem": "api, flask, web, database",
                }
                for key, excludes in overlap_map.items():
                    if key in skill_name:
                        content = content.replace(
                            "## triggers",
                            f"## triggers\n\n```yaml\nexclude: [{', '.join(f'\"{e.strip()}\"' for e in excludes.split(','))}]\n```"
                        )
                        changes.append(f"exclude añadido: {excludes}")
                        needs_refine = True
                        break

            # 2. Actualizar timestamp
            old_stamp = "Skill auto-generada |"
            new_stamp = f"Skill auto-generada | Refinada el {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}"
            if old_stamp in content:
                content = content.replace(old_stamp, new_stamp)
                needs_refine = True

            if needs_refine:
                with open(skill_dir, "w") as f:
                    f.write(content)
                refined.append(f"{skill_name}: {', '.join(changes)}")
                print(f"[SkillRefiner] 🔧 {skill_name} refinada: {', '.join(changes)}")

        except Exception as e:
            print(f"[SkillRefiner] ⚠️ Error refinando {skill_name}: {e}")

    return refined
