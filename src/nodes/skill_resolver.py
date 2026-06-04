"""Nodo 1.5 — Skill Resolver.
Se ejecuta DESPUÉS del Investigador (RAG) y ANTES del Orquestador.
Lee las skills de ~/.agents/skills/dev/, matchea contra el user_requirement,
y extrae las secciones relevantes (rules, blueprint, code, checks).

Las skills inyectadas se agregan a:
  - business_rules   ← rules de cada skill matcheada
  - injected_skills  ← todas las secciones para que los nodos las usen
"""

import os
import re
import json
from pathlib import Path
from typing import Any

from src.state import TeamState

SKILLS_DIR = Path.home() / ".agents" / "skills" / "dev"

# ── Secciones que nos interesan de cada SKILL.md ──
TARGET_SECTIONS = ["triggers", "rules", "blueprint", "code", "checks"]


def _read_skill_file(path: Path) -> str | None:
    """Lee un SKILL.md devolviendo su contenido o None si no existe."""
    skill_file = path / "SKILL.md"
    if not skill_file.exists():
        return None
    try:
        return skill_file.read_text(encoding="utf-8")
    except Exception:
        return None


def _extract_yaml_block(text: str, section_name: str) -> str | None:
    """Extrae el contenido de un bloque ```yaml ... ``` que está DENTRO de
    una sección específica (## section_name) del SKILL.md.
    
    Busca el encabezado ## <section_name> y luego el primer bloque yaml.
    """
    # Buscar el encabezado de la sección
    pattern = re.compile(
        rf"^##\s+{re.escape(section_name)}\s*$.*?```yaml\s*\n(.*?)```",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return None


def _parse_yaml_simple(yaml_text: str) -> Any:
    """Parseo YAML mínimo SIN dependencia externa (pyyaml).
    Soporta: strings, listas, diccionarios anidados simples.
    NO soporta números complejos, anchors, etc.
    """
    if yaml_text is None:
        return None
    
    # Caso: es un bloque multilínea (>)
    if ">" in yaml_text.split("\n")[0]:
        # Extraer texto multilínea
        lines = yaml_text.split("\n")
        first_line = lines[0].strip()
        if first_line.endswith(">"):
            rest = [l.strip() for l in lines[1:] if l.strip()]
            return " ".join(rest)
    
    # Intentar como JSON (si es un dict simple es más fácil)
    try:
        return json.loads(yaml_text)
    except json.JSONDecodeError:
        pass
    
    # Parseo manual
    result = {}
    current_key = None
    current_list = None
    in_list = False
    in_multiline = False
    multiline_lines = []
    
    for line in yaml_text.split("\n"):
        stripped = line.rstrip()
        
        # Continuación de multilínea
        if in_multiline:
            if stripped.strip().startswith("-") or ":" in stripped.strip() or stripped.strip() == "":
                in_multiline = False
                if current_key and multiline_lines:
                    result[current_key] = "\n".join(multiline_lines).strip()
                    multiline_lines = []
            else:
                multiline_lines.append(stripped.strip())
                continue
        
        # Lista
        if stripped.strip().startswith("- "):
            raw_item = stripped.strip()[2:]
            item = raw_item.strip().strip('"').strip("'")
            if in_list and current_key:
                result.setdefault(current_key, []).append(item)
            elif current_key and isinstance(result.get(current_key), list):
                result[current_key].append(item)
            elif current_key:
                result[current_key] = [item]
                in_list = True
            continue
        
        in_list = False
        
        # Clave: valor
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            
            # Multilínea (>)
            if value == ">" or value == ">-":
                in_multiline = True
                multiline_lines = []
                current_key = key
                continue
            
            # Lista inline
            if value.startswith("[") and value.endswith("]"):
                try:
                    result[key] = json.loads(value.replace("'", '"'))
                except json.JSONDecodeError:
                    result[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",")]
                continue
            
            # Bool
            if value.lower() == "true":
                result[key] = True
            elif value.lower() == "false":
                result[key] = False
            elif value == "" or value == "null":
                result[key] = None
            elif value.startswith('"') and value.endswith('"'):
                result[key] = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                result[key] = value[1:-1]
            else:
                result[key] = value
            
            current_key = key
    
    # Si multilínea quedó abierta
    if in_multiline and current_key and multiline_lines:
        result[current_key] = "\n".join(multiline_lines).strip()
    
    return result if result else yaml_text


def _match_triggers(triggers: dict | None, requirement: str) -> bool:
    """Determina si una skill debe activarse basado en sus triggers.
    
    Matching por keywords y patterns contra el user_requirement.
    """
    if triggers is None:
        return False
    if not isinstance(triggers, dict):
        return False
    
    req_lower = requirement.lower()
    
    # Keywords simples
    keywords = triggers.get("keywords", [])
    if isinstance(keywords, list):
        for kw in keywords:
            if str(kw).lower() in req_lower:
                return True
    
    # Patterns (frases compuestas)
    patterns = triggers.get("patterns", [])
    if isinstance(patterns, list):
        for pat in patterns:
            if str(pat).lower() in req_lower:
                return True
    
    # Exclude words — si hay exclude, NO activar
    exclude = triggers.get("exclude", [])
    if isinstance(exclude, list):
        for ex in exclude:
            if str(ex).lower() in req_lower:
                return False
    
    return False


def _extract_rules(yaml_raw: str | None) -> list[str]:
    """Extrae lista de reglas de negocio del YAML crudo de rules."""
    if not yaml_raw:
        return []
    
    rules: list[str] = []
    for line in yaml_raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            # Quitar el "- " y las comillas
            rule = stripped[2:].strip().strip('"').strip("'")
            if rule:
                rules.append(rule)
    return rules


def _extract_blueprint_text(yaml_raw: str | None) -> str:
    """Extrae texto legible del YAML crudo de blueprint.
    Trabaja directamente con el texto YAML sin parsear estructuras anidadas."""
    if not yaml_raw:
        return ""
    
    lines = yaml_raw.split("\n")
    parts = []
    current_section = None
    
    for line in lines:
        stripped = line.strip()
        
        # Detectar secciones principales
        if stripped.startswith("description:"):
            val = stripped.split(":", 1)[1].strip().strip('"').strip("'").strip(">")
            if val and val != ">":
                parts.append(f"[Blueprint] {val}")
        elif stripped.startswith("data_flow:"):
            val = stripped.split(":", 1)[1].strip().strip('"').strip("'").strip(">")
            if val:
                parts.append(f"[Flujo de datos] {val}")
        elif stripped.startswith("- path:"):
            current_section = "files"
            path_val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            parts.append(f"  - Archivo: {path_val}")
        elif stripped.startswith("purpose:") and current_section == "files":
            purpose = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            parts[-1] = parts[-1] + f" — {purpose}"
        elif stripped.startswith("- ") and "tech_decisions" in current_section if current_section else False:
            parts.append(f"  {stripped}")
        elif stripped.startswith("tech_decisions"):
            current_section = "tech_decisions"
    # También capturar tech_decisions que vienen como lista
    in_td = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("tech_decisions"):
            in_td = True
            continue
        if in_td and stripped.startswith("- "):
            parts.append(f"  {stripped[2:]}")
        elif in_td and not stripped.startswith("- ") and stripped:
            in_td = False
    
    # Extraer multilínea (>) — description y data_flow pueden ser multilínea
    # Buscar bloques > que continúan en siguientes líneas indentadas
    i = 0
    while i < len(lines):
        line = lines[i]
        if ">" in line.split("#")[0] and ":" in line:
            # Podría ser un bloque multilínea
            key = line.split(":")[0].strip()
            rest = []
            i += 1
            while i < len(lines) and (lines[i].startswith("    ") or lines[i].startswith("  ")):
                rest.append(lines[i].strip())
                i += 1
            if rest:
                text = " ".join(rest)
                if key == "description":
                    parts.append(f"[Blueprint] {text}")
                elif key == "data_flow":
                    parts.append(f"[Flujo de datos] {text}")
            continue
        i += 1
    
    return "\n".join(parts)


def _extract_code_text(yaml_raw: str | None) -> str:
    """Extrae información de templates, librerías y snippets del YAML crudo."""
    if not yaml_raw:
        return ""
    
    lines = yaml_raw.split("\n")
    parts = []
    in_snippets = False
    current_snippet_name = ""
    snippet_code_lines = []
    capturing_code = False
    
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith("templates:"):
            in_snippets = False
            continue
        elif stripped.startswith("- name:"):
            name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if not in_snippets:
                parts.append(f"[Template] {name}")
            else:
                current_snippet_name = name
            continue
        elif stripped.startswith("description:"):
            desc = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if parts and parts[-1].startswith("[Template]") or parts and parts[-1].startswith("[Snippet]"):
                parts[-1] = parts[-1] + f" — {desc}"
            continue
        elif stripped.startswith("preferred:"):
            continue
        elif stripped.startswith("conditional:"):
            continue
        elif stripped.startswith("avoid:"):
            continue
        elif stripped.startswith("- ") and "libraries" in str(lines[:lines.index(line)]):
            # items de librerías
            parts.append(f"  {stripped}")
            continue
        elif stripped.startswith("libraries:"):
            parts.append("[Librerías]")
            continue
        elif stripped.startswith("snippets:"):
            in_snippets = True
            continue
        elif in_snippets and stripped.startswith("code: |"):
            capturing_code = True
            snippet_code_lines = []
            continue
        elif capturing_code:
            if stripped.startswith("- ") or stripped.startswith("name:") or stripped.startswith("description:") or ":" in stripped[:20]:
                # Terminó el bloque de código
                if snippet_code_lines:
                    code_text = "\n".join(snippet_code_lines)
                    parts.append(f"  [Snippet] {current_snippet_name}")
                    parts.append(f"    ```python\n{code_text}\n    ```")
                    snippet_code_lines = []
                capturing_code = False
                if stripped.startswith("- ") or stripped.startswith("name:"):
                    # Procesar esta línea de nuevo
                    if stripped.startswith("- name:"):
                        name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                        current_snippet_name = name
                    continue
            else:
                snippet_code_lines.append(stripped)
    
    # Si quedó código sin finalizar
    if capturing_code and snippet_code_lines:
        code_text = "\n".join(snippet_code_lines)
        parts.append(f"  [Snippet] {current_snippet_name}")
        parts.append(f"    ```python\n{code_text}\n    ```")
    
    return "\n".join(parts)


def _extract_checks_text(yaml_raw: str | None) -> str:
    """Extrae checks de validación del YAML crudo, organizados por categoría."""
    if not yaml_raw:
        return ""
    
    lines = yaml_raw.split("\n")
    parts = []
    current_category = None
    
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith("- category:"):
            cat = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_category = cat
            parts.append(f"[Checks: {cat}]")
        elif stripped.startswith("- ") and "[ ]" in stripped:
            # Es un check item 
            check_text = stripped[2:]  # Remove "- "
            current_category = current_category or "general"
            parts.append(f"  {check_text}")
        elif stripped.startswith("checks:") and current_category:
            continue  # "checks:" sub-key, no hacer nada
        elif stripped.startswith("validation_checks:"):
            continue  # Header principal
    
    return "\n".join(parts)


def _load_and_match_skills(requirement: str) -> list[dict]:
    """Escanea ~/.agents/skills/dev/, carga skills, matchea contra requirement.
    
    Devuelve lista de skills matcheadas con sus secciones extraídas.
    """
    if not SKILLS_DIR.exists():
        print(f"[SkillResolver] Directorio de skills no existe: {SKILLS_DIR}")
        return []
    
    matched = []
    
    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        
        # Leer SKILL.md
        content = _read_skill_file(entry)
        if content is None:
            continue
        
        skill_name = entry.name
        
        # Extraer secciones
        triggers_raw = _extract_yaml_block(content, "triggers")
        triggers = _parse_yaml_simple(triggers_raw) if triggers_raw else None
        
        # Matchear
        if not _match_triggers(triggers, requirement):
            continue
        
        # Extraer secciones relevantes
        rules_raw = _extract_yaml_block(content, "rules")
        blueprint_raw = _extract_yaml_block(content, "blueprint")
        code_raw = _extract_yaml_block(content, "code")
        checks_raw = _extract_yaml_block(content, "checks")
        
        skill_data = {
            "name": skill_name,
            "rules": _extract_rules(rules_raw),
            "blueprint_text": _extract_blueprint_text(blueprint_raw),
            "code_text": _extract_code_text(code_raw),
            "checks_text": _extract_checks_text(checks_raw),
        }
        
        matched.append(skill_data)
        print(f"[SkillResolver] Skill activada: {skill_name}")
    
    return matched


async def skill_resolver_node(state: TeamState) -> dict:
    """Resuelve y inyecta skills en el estado.
    
    Lee el user_requirement, matchea skills, y:
    1. Agrega rules a business_rules
    2. Almacena blueprint, code, checks en injected_skills
    3. Agrega blueprint + code a retrieved_memory como contexto adicional
    """
    requirement = state.get("user_requirement", "")
    existing_rules = state.get("business_rules", [])
    existing_memory = state.get("retrieved_memory", "")
    
    print(f"[SkillResolver] Analizando requerimiento para activar skills: {requirement[:60]}...")
    
    matched_skills = _load_and_match_skills(requirement)
    
    if not matched_skills:
        print("[SkillResolver] Ninguna skill activada")
        return {
            "injected_skills": {"matched": [], "rules": [], "blueprint": "", "code": "", "checks": ""},
            "scratchpad": ["[SkillResolver] Sin skills activadas para este requerimiento"],
        }
    
    # Acumular inyecciones
    all_rules: list[str] = []
    all_blueprint_parts: list[str] = []
    all_code_parts: list[str] = []
    all_checks_parts: list[str] = []
    skill_names: list[str] = []
    
    for sk in matched_skills:
        skill_names.append(sk["name"])
        all_rules.extend(sk["rules"])
        if sk["blueprint_text"]:
            all_blueprint_parts.append(f"=== Skill: {sk['name']} ===\n{sk['blueprint_text']}")
        if sk["code_text"]:
            all_code_parts.append(f"=== Skill: {sk['name']} ===\n{sk['code_text']}")
        if sk["checks_text"]:
            all_checks_parts.append(f"=== Skill: {sk['name']} ===\n{sk['checks_text']}")
    
    # Combinar en strings
    blueprint_combined = "\n\n".join(all_blueprint_parts)
    code_combined = "\n\n".join(all_code_parts)
    checks_combined = "\n\n".join(all_checks_parts)
    
    # Inyectar rules en business_rules (sin duplicar)
    existing_rules_set = set(existing_rules)
    new_rules = [r for r in all_rules if r not in existing_rules_set]
    combined_rules = existing_rules + new_rules
    
    # Inyectar blueprint + code en retrieved_memory como contexto adicional
    skill_context_parts = []
    if blueprint_combined:
        skill_context_parts.append(f"[SKILL BLUEPRINT]\n{blueprint_combined}")
    if code_combined:
        skill_context_parts.append(f"[SKILL CODE]\n{code_combined}")
    
    skill_context = "\n\n".join(skill_context_parts)
    combined_memory = existing_memory
    if skill_context:
        combined_memory = existing_memory + "\n\n---\n\n" + skill_context if existing_memory else skill_context
    
    print(f"[SkillResolver] Skills activadas: {', '.join(skill_names)}")
    print(f"[SkillResolver] {len(new_rules)} nuevas reglas inyectadas, {len(skill_context_parts)} secciones de contexto")
    
    return {
        "business_rules": combined_rules,
        "retrieved_memory": combined_memory,
        "injected_skills": {
            "matched": skill_names,
            "rules": all_rules,
            "blueprint": blueprint_combined,
            "code": code_combined,
            "checks": checks_combined,
        },
        "scratchpad": [
            f"[SkillResolver] Skills activadas: {', '.join(skill_names)}",
            f"[SkillResolver] {len(new_rules)} reglas inyectadas desde skills",
        ],
        "audit_trail": [{
            "nodo": "Skill Resolver",
            "accion": "Inyección de skills en el pipeline",
            "resultado": f"Skills: {', '.join(skill_names)} — {len(new_rules)} reglas, {len(skill_context_parts)} secciones",
        }],
    }
