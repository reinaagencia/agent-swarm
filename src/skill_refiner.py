"""Skill Refiner — Herramienta de autorrefinamiento de skills.

Analiza todas las skills (manuales y auto-generadas) y:
1. Detecta skills con triggers demasiado amplios (falsos positivos)
2. Detecta skills con triggers que nunca matchean (skills muertas)
3. Detecta keywords obsoletos o mal formateados
4. Sugiere/agrega exclude words para evitar solapamientos
5. Verifica que el formato YAML sea correcto
6. Reporta un resumen de salud del catálogo de skills
7. Detecta referencias a métodos de autenticación obsoletos (auth_manager.py, etc.)
8. Detecta referencias a herramientas/scripts que ya no existen

Uso:
    python3 -c "from src.skill_refiner import refiner_report; print(refiner_report())"
    
Mejoras v2:
  - Escanea TODOS los directorios de skills (~/.agents/skills/*/), no solo dev/
  - Detecta referencias obsoletas a auth_manager.py, update_source.py, etc.
  - Detecta referencias a rutas de archivo que ya no existen
  - Detecta patrones de interacción incompletos en Playwright
  - Incluye categorías notebooklm, conversación, skills de sistema
"""

import re
import yaml
from pathlib import Path

SKILLS_DIR = Path.home() / ".agents" / "skills"

# Requerimientos de prueba para detectar falsos positivos
TEST_REQUIREMENTS = [
    # Funciones Python genéricas
    "Crea una funcion que sume dos numeros",
    "Crea una funcion filter_valid(dicts, keys)",
    "Escribe una funcion en Python que calcule el factorial",
    # CLI tools
    "Crea un script CLI que procese un archivo CSV",
    "Crea una herramienta de linea de comandos para renombrar archivos",
    # APIs
    "Crea una API REST con Flask para gestionar tareas",
    "Crea una API con autenticacion JWT",
    # Pipelines
    "Haz un pipeline de datos que lea JSON y exporte CSV",
    "Crea un procesador ETL con Pandas",
    # Frontend/Web
    "Crea un dashboard con Streamlit",
    "Crea una pagina web con HTML y CSS",
    # Testing
    "Escribe tests pytest para el modulo de procesos",
    # Otros
    "Crea un servidor MCP con herramientas personalizadas",
    "Haz un deployment a Railway",
    "Crea un agente de WhatsApp con Express",
    # NotebookLM / Conversación
    "Guarda el resumen de la sesion en NotebookLM",
    "Agrega una fuente al cuaderno de agentes",
    "Guarda la conversacion en el diario de desarrollo",
    "Actualiza el notebook con los ultimos cambios",
    "Haz un resumen de esta conversacion y guardalo",
    # Playwright / Navegador
    "Navega a la pagina de NotebookLM y agrega una fuente",
    "Abre el navegador y haz clic en el boton de agregar fuente",
    "Automatiza la pestana de NotebookLM para pegar texto",
    # Skills / Refinamiento
    "Ejecuta el refiner de skills para verificar la salud del catalogo",
    "Refina las skills auto-generadas para reducir falsos positivos",
    "Genera una nueva skill a partir de patrones repetidos",
    # Auth / Conexiones
    "Configura las credenciales de Google OAuth",
    "Verifica que la autenticacion de Playwright MCP esta activa",
    # Code Review / QA
    "Revisa el codigo antes de la entrega final",
    "Haz code review del modulo de procesos",
    "Audita la calidad del codigo y sugiere mejoras",
    # Knowledge / Memoria
    "Guarda el conocimiento aprendido en la base de memoria",
    "Extrae lecciones de esta tarea para futuras ejecuciones",
    "Etiqueta la memoria por dominio y tipo de tarea",
]

# Categorías de skills esperadas
SKILL_CATEGORIES = {
    "api": ["api", "rest", "flask", "endpoint", "http", "jwt", "oauth"],
    "cli": ["cli", "script", "línea de comandos", "consola", "argparse"],
    "pipeline": ["pipeline", "etl", "datos", "data", "csv", "json", "pandas"],
    "python": ["función", "funcion", "python", "módulo", "modulo"],
    "testing": ["test", "pytest", "qa", "cobertura"],
    "deployment": ["deploy", "railway", "docker", "producción"],
    "mcp": ["mcp", "server", "tools.py", "alpaca"],
    "web": ["web", "frontend", "dashboard", "html", "css", "streamlit"],
    "whatsapp": ["whatsapp", "bot", "mensaje", "selma"],
    "notebooklm": ["notebooklm", "cuaderno", "notebook", "fuente", "source", 
                   "resumen", "diario", "conversación", "sesión"],
    "playwright": ["playwright", "browser", "navegador", "mcp browser", 
                   "cdk-overlay", "angular", "click"],
    "skill_refiner": ["skill", "refiner", "refinamiento", "auto-mejora",
                      "catalogo", "catálogo", "health", "salud"],
    "auth": ["auth", "oauth", "credentials", "token", "api key", "cookies"],
}


def _read_skill(skill_path: Path) -> dict | None:
    """Lee una skill y retorna sus secciones."""
    try:
        content = skill_path.read_text(encoding="utf-8")

        # Extraer bloques YAML
        sections = {}
        yaml_blocks = re.findall(
            r"^##\s+(\w+)\s*\n+```yaml\s*\n(.*?)```",
            content, re.MULTILINE | re.DOTALL
        )

        for section_name, yaml_content in yaml_blocks:
            try:
                parsed = yaml.safe_load(yaml_content) or {}
                sections[section_name] = parsed
            except yaml.YAMLError as e:
                sections[section_name] = {"_parse_error": str(e)}

        return {
            "path": skill_path,
            "name": skill_path.parent.name,
            "content": content,
            "sections": sections,
        }
    except Exception as e:
        return {"path": skill_path, "name": skill_path.parent.name, "error": str(e)}


def _test_triggers(skill: dict) -> dict:
    """Prueba los triggers de una skill contra requirements de prueba."""
    triggers = skill.get("sections", {}).get("triggers", {})
    keywords = triggers.get("keywords", [])
    patterns = triggers.get("patterns", [])
    exclude = triggers.get("exclude", [])

    # Normalizar a listas
    if isinstance(keywords, str):
        keywords = [keywords]
    if isinstance(patterns, str):
        patterns = [patterns]
    if isinstance(exclude, str):
        exclude = [exclude]
    if not isinstance(keywords, list):
        keywords = []
    if not isinstance(patterns, list):
        patterns = []
    if not isinstance(exclude, list):
        exclude = []

    # Asegurar que todo sea string
    keywords = [str(k) for k in keywords]
    patterns = [str(p) for p in patterns]
    exclude = [str(e) for e in exclude]

    matches = []
    false_positives = []

    for req in TEST_REQUIREMENTS:
        req_lower = req.lower()

        # Verificar exclude primero
        if any(e.lower() in req_lower for e in exclude):
            continue

        # Verificar keywords
        kw_match = any(k.lower() in req_lower for k in keywords)
        pat_match = any(p.lower() in req_lower for p in patterns)

        if kw_match or pat_match:
            matches.append(req)

            # Determinar si es falso positivo
            skill_name = skill.get("name", "")
            category = _guess_category(req)
            skill_category = _guess_skill_category(skill_name, keywords)

            if category and skill_category and category != skill_category:
                false_positives.append({
                    "requirement": req,
                    "detected_as": skill_category,
                    "actual_category": category,
                })

    return {
        "matches": len(matches),
        "matched_requirements": matches,
        "false_positives": false_positives,
        "false_positive_rate": round(len(false_positives) / max(len(matches), 1) * 100, 1),
    }


def _guess_category(requirement: str) -> str | None:
    """Adivina la categoría de un requerimiento."""
    req_lower = requirement.lower()
    for category, indicators in SKILL_CATEGORIES.items():
        for ind in indicators:
            if ind in req_lower:
                return category
    return None


def _guess_skill_category(skill_name: str, keywords: list[str]) -> str | None:
    """Adivina la categoría de una skill por su nombre y keywords."""
    name_lower = skill_name.lower()
    kw_text = " ".join(k.lower() for k in keywords)

    for category, indicators in SKILL_CATEGORIES.items():
        for ind in indicators:
            if ind in name_lower or ind in kw_text:
                return category
    return None


# Referencias obsoletas a detectar en los contenidos de las skills
OBSOLETE_REFERENCES = [
    # auth_manager.py fue reemplazado por notebooklm-fast-auth (Playwright MCP)
    ("auth_manager.py", "Método de autenticación obsoleto — usar notebooklm-fast-auth (Playwright MCP)"),
    ("update_source.py", "Script de actualización obsoleto — usar flujo de diálogo + Texto copiado"),
    ("patchright", "Herramienta obsoleta — Playwright MCP es el reemplazo"),
    # Rutas que ya no existen
    ("scripts/run.py", "Ruta obsoleta — los scripts se ejecutan via Playwright MCP"),
]

# Referencias a directorios de skills no-dev que deben ser escaneados
NON_DEV_SKILL_DIRS = [
    "canva", "conversation-saver", "deepseek-web", "deploy-queenchat",
    "notebooklm", "notebooklm-fast-auth", "remotion", "visor-multimodal",
    "whatsapp-agent",
]


def _check_obsolete_references(content: str) -> list[str]:
    """Detecta referencias a herramientas/rutas obsoletas en el contenido.
    
    Excluye menciones en contexto de advertencia ("no usar", "obsoleto", "Never use").
    """
    issues = []
    for ref_pattern, message in OBSOLETE_REFERENCES:
        if ref_pattern not in content:
            continue
        
        # Buscar si la referencia está en contexto de advertencia (no es un uso real)
        lines = content.split('\n')
        ref_in_warning = False
        for i, line in enumerate(lines):
            if ref_pattern in line:
                # Revisar líneas circundantes por palabras de advertencia
                context_start = max(0, i - 1)
                context_end = min(len(lines), i + 3)
                context = '\n'.join(lines[context_start:context_end]).lower()
                warning_words = ['never use', 'obsoleto', 'deprecated', 'no usar', 
                                'no utilices', 'en vez de', 'reemplazado', 'legacy',
                                'old', 'antiguo', 'not the old', 'not use']
                if any(w in context for w in warning_words):
                    ref_in_warning = True
                    break
        
        if not ref_in_warning:
            issues.append(f"Referencia obsoleta: '{ref_pattern}' — {message}")
    return issues


def _check_playwright_interactions(content: str) -> list[str]:
    """Detecta patrones de interacción con Playwright incompletos o frágiles."""
    issues = []

    # Si usa playwright_browser_click sin waitFor previo
    if "playwright_browser_click" in content and "waitFor" not in content:
        # Verificar si hay algún mecanismo de espera
        has_wait = any(w in content for w in ["waitFor", "wait_for", "setTimeout", "timeout"])
        if not has_wait:
            issues.append("Usa playwright_browser_click sin waitFor previo — frágil contra overlays Angular")

    # Si usa ref= selectors (frágiles)
    if "[ref=" in content or "jslog" in content:
        issues.append("Usa selectores [ref=...] frágiles — preferir selectores semánticos (:has-text, button. class)")

    # Si usa run_code_unsafe pero no maneja errores
    if "run_code_unsafe" in content and "try" not in content and "catch" not in content:
        issues.append("Usa run_code_unsafe sin try/catch — puede fallar silenciosamente")

    return issues


def _check_yaml_health(skill: dict) -> list[str]:
    """Verifica la salud del YAML de una skill."""
    issues = []

    if "error" in skill:
        return [f"Error de lectura: {skill['error']}"]

    sections = skill.get("sections", {})
    content = skill.get("content", "")

    # Verificar secciones requeridas (skills dev requieren triggers/rules/blueprint)
    is_dev_skill = "/dev/" in str(skill.get("path", ""))
    if is_dev_skill:
        required = ["triggers", "rules", "blueprint"]
        for sec in required:
            if sec not in sections:
                issues.append(f"Falta sección requerida: ## {sec}")
    else:
        # Skills no-dev: al menos tener name y description
        if not content.strip():
            issues.append("Skill vacía — sin contenido")
        elif len(content) < 100:
            issues.append("Skill demasiado corta — menos de 100 caracteres")

    # Verificar triggers
    triggers = sections.get("triggers", {})
    if isinstance(triggers, dict):
        kw = triggers.get("keywords", [])
        if isinstance(kw, list) and len(kw) == 0:
            issues.append("Triggers sin keywords")
        elif isinstance(kw, list):
            # Verificar keywords muy genéricas
            very_common = {"python", "código", "codigo", "función", "funcion",
                          "archivo", "crear", "hacer", "script"}
            for k in kw:
                if str(k).lower() in very_common:
                    issues.append(f"Keyword demasiado genérica: '{k}'")

    # Detectar exclude fuera de lugar (malformado)
    if "exclude:" in content and "```yaml" in content:
        # Verificar que exclude esté dentro del bloque triggers
        if "triggers" in sections:
            trig_yaml = sections["triggers"]
            if isinstance(trig_yaml, dict) and "exclude" not in trig_yaml:
                issues.append("exclude: está presente pero no dentro del bloque triggers")

    # Verificar que los bloques de código estén bien cerrados
    known_openers = ["```yaml", "```python", "```bash", "```json", 
                     "```javascript", "```js", "```markdown", "```text"]
    total_opens = sum(content.count(o) for o in known_openers)
    total_closes = content.count("```")
    
    # Si hay más closes que opens*2, puede haber bloques sin lenguaje (``` solos)
    # que son tanto opens como closes. Para skills que no son dev, esto es normal.
    if total_opens > 0 and total_closes > total_opens * 2:
        issues.append(f"Posibles bloques mal cerrados (opens: {total_opens}, closes: {total_closes})")
    elif total_opens > 0 and total_opens != (total_closes - total_opens):
        # Los ``` que no tienen lenguaje después también cuentan como opens
        actual_opens = total_closes - total_opens  # asume que todos los closes que no son openers son opens
        if total_opens != actual_opens:
            issues.append(f"Bloques desbalanceados (opens con lenguaje: {total_opens}, closes total: {total_closes})")

    # Verificar referencias obsoletas
    obsolete_issues = _check_obsolete_references(content)
    issues.extend(obsolete_issues)

    # Verificar patrones de Playwright
    pw_issues = _check_playwright_interactions(content)
    issues.extend(pw_issues)

    return issues


def _find_all_skills() -> list[Path]:
    """Encuentra skills en TODOS los directorios, no solo dev/."""
    skill_files = []

    # Skills en dev/
    dev_dir = SKILLS_DIR / "dev"
    if dev_dir.exists():
        skill_files.extend(sorted(dev_dir.glob("*/SKILL.md")))

    # Skills no-dev (conversation-saver, notebooks, etc.)
    for subdir in NON_DEV_SKILL_DIRS:
        skill_path = SKILLS_DIR / subdir / "SKILL.md"
        if skill_path.exists():
            skill_files.append(skill_path)

    # Skills auto-generadas en dev/ (ya cubiertas por el primer glob)
    # Skills con otros nombres que puedan existir
    for subdir in sorted(SKILLS_DIR.iterdir()):
        if subdir.is_dir() and subdir.name not in ["dev"] + NON_DEV_SKILL_DIRS:
            skill_path = subdir / "SKILL.md"
            if skill_path.exists() and skill_path not in skill_files:
                skill_files.append(skill_path)

    return sorted(set(skill_files))


def refiner_report() -> str:
    """Genera un reporte completo de salud del catálogo de skills."""
    if not SKILLS_DIR.exists():
        return "❌ Directorio de skills no encontrado"

    skill_files = _find_all_skills()
    if not skill_files:
        return "ℹ️  No hay skills en el catálogo"

    total = len(skill_files)
    healthy = 0
    warnings = []
    improvements = []

    for sf in skill_files:
        skill = _read_skill(sf)
        name = skill.get("name", sf.parent.name)

        # Salud YAML + referencias obsoletas + patrones Playwright
        yaml_issues = _check_yaml_health(skill)
        if yaml_issues:
            for issue in yaml_issues:
                warnings.append(f"  [{name}] {issue}")

        # Prueba de triggers (solo para skills dev que tengan triggers)
        test_result = _test_triggers(skill)
        fp = test_result.get("false_positives", [])

        if fp:
            for fp_item in fp:
                warnings.append(
                    f"  [{name}] Falso positivo: '{fp_item['requirement'][:40]}' "
                    f"(detectó: {fp_item['detected_as']}, real: {fp_item['actual_category']})"
                )

        if test_result.get("matches", 0) == 0:
            # Solo advertir si tiene triggers definidos
            triggers = skill.get("sections", {}).get("triggers", {})
            if triggers:
                warnings.append(f"  [{name}] No matchea NINGÚN requirement de prueba (skill muerta?)")

        if not yaml_issues and not fp:
            healthy += 1

    # Generar sugerencias de mejora
    if not any("No matchea" in w for w in warnings):
        improvements.append("Todas las skills con triggers matchean al menos un requirement de prueba ✅")
    if not any("Falso positivo" in w for w in warnings):
        improvements.append("Sin falsos positivos detectados ✅")
    if not any("malformado" in w for w in warnings or "mal cerrados" in w):
        improvements.append("Formato YAML correcto en todas las skills ✅")
    if not any("obsoleta" in w for w in warnings):
        improvements.append("Sin referencias obsoletas ✅")
    if not any("Playwright" in w for w in warnings):
        improvements.append("Patrones de Playwright correctos ✅")

    # Listar skills (con directorio de origen)
    skill_list = []
    for sf in skill_files:
        name = sf.parent.name
        skill = _read_skill(sf)
        test_result = _test_triggers(skill)
        matches = test_result.get("matches", 0)
        fp_rate = test_result.get("false_positive_rate", 0)

        # Determinar origen
        parent_dir = sf.parent.parent.name  # dev/ u otro
        if parent_dir == "dev":
            is_auto = name.startswith("auto_")
            tag = "🤖" if is_auto else "📚"
        else:
            tag = "📁"

        marker = "⚠️" if (fp_rate > 0 and matches > 0) or any(name in w for w in warnings) else "✅"
        # Mejor marker
        has_warning = any(name in w for w in warnings)
        marker = "⚠️" if has_warning else ("✅" if matches > 0 else "⬜")
        skill_list.append(f"  {tag} {marker} {name:30s} {parent_dir:20s} {matches:2d} matches")

    lines = [
        "=" * 70,
        "  📋 REPORTE DE SALUD DEL CATÁLOGO DE SKILLS (v2)",
        "=" * 70,
        f"  Skills analizadas: {total}",
        f"  Saludables: {healthy}/{total}",
        f"  Con advertencias: {len(warnings)}",
        "",
        "  Skills:",
        f"  {'':3s} {'':1s} {'Nombre':30s} {'Origen':20s} {'Tests':8s}",
        f"  {'':3s} {'':1s} {'-'*30} {'-'*20} {'-'*8}",
    ] + skill_list

    if warnings:
        lines += ["", "  ⚠️ Advertencias:"] + warnings

    if improvements:
        lines += ["", "  ✅ Mejoras:"] + [f"    {i}" for i in improvements]

    lines += [
        "",
        f"  📅 Último análisis: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 70,
    ]

    return "\n".join(lines)


def auto_fix_skills() -> list[str]:
    """Intenta corregir automáticamente problemas detectados."""
    if not SKILLS_DIR.exists():
        return []

    fixes = []

    for sf in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        skill = _read_skill(sf)
        name = skill.get("name", sf.parent.name)
        content = skill.get("content", "")

        if not content:
            continue

        original = content
        changed = False

        # Fix 1: Asegurar que exclude esté dentro del bloque triggers
        if "exclude:" in content and "triggers" in skill.get("sections", {}):
            triggers = skill["sections"]["triggers"]
            if isinstance(triggers, dict) and "exclude" not in triggers:
                # El exclude está fuera del bloque YAML
                # Moverlo dentro
                lines = content.split("\n")
                new_lines = []
                in_triggers = False
                trigger_lines = []

                for line in lines:
                    if line.strip().startswith("## triggers"):
                        in_triggers = True
                        new_lines.append(line)
                    elif line.strip().startswith("## ") and in_triggers:
                        in_triggers = False
                        # Cerrar bloque yaml y agregar exclude
                        if "exclude:" not in "\n".join(trigger_lines):
                            trigger_lines.append("exclude: []")
                        new_lines.append("```yaml")
                        new_lines.extend(trigger_lines)
                        new_lines.append("```")
                        new_lines.append("")
                        new_lines.append(line)
                        trigger_lines = []
                    elif in_triggers:
                        if line.strip().startswith("```yaml"):
                            continue  # Saltar apertura
                        elif line.strip() == "```":
                            continue  # Saltar cierre
                        elif "exclude:" in line:
                            # Capturar exclude
                            continue
                        else:
                            trigger_lines.append(line)
                    else:
                        new_lines.append(line)

                content = "\n".join(new_lines)
                changed = True
                fixes.append(f"{name}: exclude movido dentro de triggers")

        # Fix 2: Agregar exclude a skills sin exclude si son auto_
        if name.startswith("auto_") and "exclude:" not in content:
            overlap_map = {
                "auto_cli": "api, flask, web, dashboard",
                "auto_api": "script, cli, consola",
                "auto_ecosystem": "api, flask, web, database",
            }
            for key, excludes in overlap_map.items():
                if key in name:
                    # Insertar exclude en los triggers
                    lines = content.split("\n")
                    new_lines = []
                    in_triggers = False

                    for line in lines:
                        if line.strip() == "```" and in_triggers:
                            new_lines.append(f"exclude: [{', '.join(f'\"{e.strip()}\"' for e in excludes.split(','))}]")
                            new_lines.append(line)
                            in_triggers = False
                        elif line.strip().startswith("## ") and in_triggers:
                            new_lines.append(f"exclude: [{', '.join(f'\"{e.strip()}\"' for e in excludes.split(','))}]")
                            new_lines.append("```")
                            new_lines.append("")
                            new_lines.append(line)
                            in_triggers = False
                        else:
                            new_lines.append(line)
                            if line.strip().startswith("keywords:"):
                                in_triggers = True

                    content = "\n".join(new_lines)
                    changed = True
                    fixes.append(f"{name}: exclude añadido: {excludes}")
                    break

        if changed:
            with open(sf, "w") as f:
                f.write(content)

    return fixes


# Wrapper para uso desde el pipeline
def refine_and_report():
    """Ejecuta el refinamiento y muestra el reporte."""
    fixes = auto_fix_skills()
    if fixes:
        print("[SkillRefiner] 🔧 Correcciones aplicadas:")
        for f in fixes:
            print(f"  • {f}")

    print()
    print(refiner_report())
    return fixes
