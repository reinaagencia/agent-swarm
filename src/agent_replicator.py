"""🔬 Agent Replication Engine — Clonación de Capacidades a Nuevos Agentes/Dominios.

ARQUITECTURA:
  Toma un "agente exitoso" (un conjunto de patrones que funcionan en un dominio)
  y lo replica a otro dominio o crea un nuevo subagente con la misma "receta".

  ```
  Agente fuente (ej: Programador de APIs REST)
         ↓
  1. Extraer "receta" (prompts, config, thresholds, patterns)
         ↓
  2. Adaptar al dominio destino (ej: Programador de Web Scraping)
         ↓
  3. Generar archivos del subagente
         ↓
  4. Registrar en catálogo de agentes
         ↓
  5. Validar con tarea de prueba
  ```

COMPONENTES DE UNA RECETA:
  - system_prompt: El prompt del agente
  - node_function: La función del nodo (Python)
  - model_preferences: Flash/Pro thresholds
  - success_patterns: Patrones que funcionaron
  - domain_knowledge: Conocimiento específico del dominio
"""

import json
import uuid
from pathlib import Path
from datetime import datetime

# ── Constantes ──
REPLICAS_DIR = Path.home() / ".agents" / "agent_replicas"
CATALOG_FILE = REPLICAS_DIR / "catalog.json"
TEMPLATES_DIR = REPLICAS_DIR / "templates"


def _ensure_dirs():
    REPLICAS_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def _load_catalog() -> dict:
    _ensure_dirs()
    if CATALOG_FILE.exists():
        try:
            return json.loads(CATALOG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"agents": [], "last_updated": None}


def _save_catalog(catalog: dict):
    _ensure_dirs()
    try:
        CATALOG_FILE.write_text(json.dumps(catalog, indent=2, ensure_ascii=False))
    except OSError as e:
        print(f"[Replicator] ⚠️ Error guardando catálogo: {e}")


# ═══════════════════════════════════════════════════════════════
# 1. EXTRACCIÓN DE RECETA
# ═══════════════════════════════════════════════════════════════

def extract_recipe(state: dict, agent_name: str = "Programador") -> dict:
    """Extrae la "receta" de un agente desde el estado de ejecución.
    
    Args:
        state: TeamState de una ejecución exitosa
        agent_name: Nombre del agente fuente
    
    Returns:
        Dict con la receta completa
    """
    recipe = {
        "agent_name": agent_name,
        "version": "1.0.0",
        "source_domain": _infer_domain(state.get("user_requirement", "")),
        "extracted_at": datetime.now().isoformat(),
        "extraction_id": str(uuid.uuid4())[:8],
        
        # Sistema de prompts (del agente)
        "prompt_style": {
            "format": "JSON",
            "temperature": 0.3,
            "max_tokens": 4096,
            "expects_blueprint": True,
            "uses_debug_history": True,
            "verifies_code": True,  # Bash-Native feature
        },
        
        # Threshholds del Model Router
        "router_preferences": {
            "preferred_model": "flash",
            "pro_threshold_iteration": 3,
            "pro_threshold_errors": 5,
            "max_pro_calls": 2,
        },
        
        # Patrones de éxito (del dominio)
        "success_patterns": state.get("scratchpad", [])[-3:] if state.get("scratchpad") else [],
        
        # Tecnologías usadas
        "technologies": state.get("architecture_blueprint", {}).get("tecnologias_sugeridas", []),
        
        # Metadata del dominio
        "domain_knowledge": {
            "common_pitfalls": _extract_pitfalls(state),
            "key_libraries": state.get("architecture_blueprint", {}).get("dependencias", []),
        },
    }
    
    print(f"[Replicator] 📋 Receta extraída: {agent_name} en {recipe['source_domain']}")
    return recipe


def _infer_domain(requirement: str) -> str:
    req_lower = requirement.lower()
    domains = {
        "api": "api_rest", "flask": "api_flask", "database": "base_de_datos",
        "csv": "procesamiento_datos", "json": "procesamiento_datos",
        "cli": "herramienta_cli", "script": "script", "web": "web",
        "test": "testing", "mcp": "mcp_server",
    }
    for keyword, domain in domains.items():
        if keyword in req_lower:
            return domain
    return "general"


def _extract_pitfalls(state: dict) -> list[str]:
    """Extrae errores comunes del scratchpad y debug_history."""
    pitfalls = []
    debug = state.get("debug_history", [])
    for entry in debug[-5:]:
        if entry.get("error"):
            pitfalls.append(f"Evitar: {entry['error'][:150]}")
    if not pitfalls:
        pitfalls.append("(sin pitfalls documentados)")
    return pitfalls


# ═══════════════════════════════════════════════════════════════
# 2. ADAPTACIÓN A NUEVO DOMINIO
# ═══════════════════════════════════════════════════════════════

def adapt_recipe(recipe: dict, target_domain: str) -> dict:
    """Adapta una receta a un dominio destino.
    
    Args:
        recipe: Receta fuente
        target_domain: Dominio destino
    
    Returns:
        Receta adaptada
    """
    adapted = dict(recipe)
    adapted["target_domain"] = target_domain
    adapted["adapted_at"] = datetime.now().isoformat()
    
    # Adaptar conocimientos específicos
    domain_adapter = {
        "api_rest": {
            "prompt_modifications": [
                "Enfócate en crear endpoints REST completos con GET, POST, PUT, DELETE",
                "Incluye validación de datos con Pydantic",
                "Documenta con OpenAPI/Swagger",
            ],
            "key_libraries": ["flask", "fastapi", "pydantic"],
        },
        "web_scraping": {
            "prompt_modifications": [
                "Usa requests + BeautifulSoup para HTML estático",
                "Usa Playwright/Selenium para JS dinámico",
                "Maneja rate limiting y retries con tenacidad",
            ],
            "key_libraries": ["requests", "beautifulsoup4", "playwright"],
        },
        "base_de_datos": {
            "prompt_modifications": [
                "Diseña schema normalizado (3FN)",
                "Usa SQLAlchemy como ORM",
                "Incluye migraciones y seeds",
            ],
            "key_libraries": ["sqlalchemy", "alembic", "psycopg2"],
        },
        "procesamiento_datos": {
            "prompt_modifications": [
                "Usa pandas para transformación de datos",
                "Incluye validación de datos de entrada",
                "Maneja errores con try/except específicos",
            ],
            "key_libraries": ["pandas", "numpy", "pydantic"],
        },
    }
    
    adapter = domain_adapter.get(target_domain, {})
    if adapter:
        adapted["prompt_style"]["domain_instructions"] = adapter.get("prompt_modifications", [])
        adapted["technologies"] = adapter.get("key_libraries", [])
        print(f"[Replicator] 🔄 Receta adaptada: {recipe['source_domain']} → {target_domain}")
    else:
        print(f"[Replicator] ⚠️ Sin adaptador específico para {target_domain}, usando genérica")
    
    return adapted


# ═══════════════════════════════════════════════════════════════
# 3. GENERAR ARCHIVOS DEL SUBAGENTE
# ═══════════════════════════════════════════════════════════════

def generate_subagent(recipe: dict) -> dict:
    """Genera los archivos de un nuevo subagente desde la receta.
    
    Args:
        recipe: Receta (original o adaptada)
    
    Returns:
        Dict con los archivos generados
    """
    agent_name = recipe.get("agent_name", "generic_agent")
    target_domain = recipe.get("target_domain", recipe.get("source_domain", "general"))
    agent_id = f"{agent_name.lower().replace(' ', '_')}_{target_domain}"
    
    # Plantilla del nodo
    node_template = f'''"""Nodo replicado: {agent_name} para {target_domain}.
Generado por Agent Replication Engine el {datetime.now().isoformat()}
Receta fuente: {recipe.get('extraction_id', 'unknown')}
"""

import json
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import get_llm, get_router_llm, safe_invoke, get_budget
from src.model_router import get_router


SYSTEM_PROMPT = """Eres {agent_name} especializado en {target_domain}.

{chr(10).join(recipe.get('prompt_style', {{}}).get('domain_instructions', [
    "Implementa código siguiendo el blueprint del Arquitecto.",
    "Corrige errores del reporte de tests previo.",
    "Escribe código limpio, tipado y con docstrings."
]))}

Responde ÚNICAMENTE en JSON:
{{"source_code": {{"archivo.py": "código"}}, "notas_scratchpad": []}}
"""


async def {agent_id}_node(state: TeamState) -> dict:
    """Nodo replicado: {agent_name} para {target_domain}."""
    iteration = state.get("iteration_count", 0)
    errors = len(state.get("test_report", {{}}).get("errors", []))
    
    router = get_router()
    llm = get_router_llm(router, "{agent_name}",
                          iteration=iteration,
                          errors=errors)
    
    prompt = _build_prompt(state)
    response = await safe_invoke(llm, [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    
    content = response.content if hasattr(response, 'content') else str(response)
    
    try:
        content_clean = content.strip()
        if content_clean.startswith("```"):
            lines = content_clean.split("\\n")
            content_clean = "\\n".join(lines[1:-1])
        result = json.loads(content_clean)
    except json.JSONDecodeError:
        result = {{"source_code": {{"main.py": content}}, "notas_scratchpad": []}}
    
    return {{
        "source_code": result.get("source_code", {{}}),
        "scratchpad": result.get("notas_scratchpad", []),
        "audit_trail": [{{
            "nodo": "{agent_name} ({target_domain})",
            "accion": "Generación de código",
            "resultado": f"{{len(result.get('source_code', {{}}))}} archivos",
        }}],
    }}


def _build_prompt(state: TeamState) -> str:
    """Construye el prompt con el contexto actual."""
    requirement = state.get("user_requirement", "")
    blueprint = state.get("architecture_blueprint", {{}})
    test_report = state.get("test_report", {{}})
    rules = state.get("business_rules", [])
    
    blueprint_str = json.dumps(blueprint, indent=2, ensure_ascii=False) if blueprint else "(sin blueprint)"
    errors_str = "\\n".join(f"- {{e}}" for e in test_report.get("errors", [])[:5]) if test_report.get("errors") else ""
    
    return f"""Requerimiento:
{{requirement[:300]}}

Reglas:
{{chr(10).join(f'- {{r}}' for r in rules[:5])}}

Blueprint:
{{blueprint_str[:500]}}
{{errors_str}}
Implementa el código completo en formato JSON."""
'''

    # Generar archivos
    files = {
        f"src/nodes/{agent_id}.py": node_template,
        f"replicas/{agent_id}/recipe.json": json.dumps(recipe, indent=2, ensure_ascii=False),
        f"replicas/{agent_id}/README.md": f"# {agent_name} - {target_domain}\n\nGenerado por Agent Replication Engine.\nReceta: {recipe.get('extraction_id', 'unknown')}\nFecha: {datetime.now().isoformat()}\n",
    }
    
    # Guardar archivos
    output_dir = REPLICAS_DIR / agent_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for filename, content in files.items():
        filepath = REPLICAS_DIR / f"{agent_id}/{filename}" if "replicas" not in filename else REPLICAS_DIR / filename
        filepath = REPLICAS_DIR / filename.replace(f"replicas/{agent_id}/", "")
        filepath = REPLICAS_DIR / agent_id / filename.split("/")[-1]
        
        # Mejor: guardar con estructura limpia
        if filename.startswith("src/"):
            filepath = Path("/Users/isabeldiaz/Dev/agent-swarm") / filename
        else:
            filepath = REPLICAS_DIR / agent_id / Path(filename).name
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)
    
    print(f"[Replicator] 📁 Subagente generado en: {REPLICAS_DIR / agent_id}")
    
    return {
        "agent_id": agent_id,
        "files_generated": list(files.keys()),
        "output_dir": str(REPLICAS_DIR / agent_id),
    }


# ═══════════════════════════════════════════════════════════════
# 4. REGISTRAR EN CATÁLOGO
# ═══════════════════════════════════════════════════════════════

def register_agent(agent_id: str, recipe: dict):
    """Registra un nuevo agente en el catálogo.
    
    Args:
        agent_id: ID único del agente
        recipe: Receta del agente
    """
    catalog = _load_catalog()
    
    entry = {
        "agent_id": agent_id,
        "name": recipe.get("agent_name", "unknown"),
        "source_domain": recipe.get("source_domain", "unknown"),
        "target_domain": recipe.get("target_domain", recipe.get("source_domain", "unknown")),
        "version": recipe.get("version", "1.0.0"),
        "created_at": datetime.now().isoformat(),
        "source_extraction": recipe.get("extraction_id", "unknown"),
        "technologies": recipe.get("technologies", []),
        "status": "active",
    }
    
    # Verificar si ya existe
    for existing in catalog["agents"]:
        if existing["agent_id"] == agent_id:
            existing.update(entry)
            existing["updated_at"] = datetime.now().isoformat()
            _save_catalog(catalog)
            print(f"[Replicator] 🔄 Agente actualizado: {agent_id}")
            return
    
    catalog["agents"].append(entry)
    catalog["last_updated"] = datetime.now().isoformat()
    _save_catalog(catalog)
    print(f"[Replicator] 🆕 Agente registrado: {agent_id}")


# ═══════════════════════════════════════════════════════════════
# 5. API PRINCIPAL: REPLICAR AGENTE
# ═══════════════════════════════════════════════════════════════

def replicate_agent(state: dict, target_domain: str = None) -> dict:
    """Replica un agente exitoso a un nuevo dominio.
    
    Args:
        state: TeamState de ejecución exitosa
        target_domain: Dominio destino (opcional, si no se especifica clona tal cual)
    
    Returns:
        Resultado de la replicación
    """
    # Extraer receta
    recipe = extract_recipe(state, agent_name="Programador")
    
    # Adaptar si hay dominio destino
    if target_domain and target_domain != recipe["source_domain"]:
        recipe = adapt_recipe(recipe, target_domain)
    
    # Generar subagente
    result = generate_subagent(recipe)
    
    # Registrar
    register_agent(result["agent_id"], recipe)
    
    print(f"\n[Replicator] 🎉 Agente replicado exitosamente!")
    print(f"  ID: {result['agent_id']}")
    print(f"  Dominio: {recipe.get('source_domain', '?')} → {recipe.get('target_domain', recipe.get('source_domain', '?'))}")
    print(f"  Archivos: {', '.join(result['files_generated'][:3])}...")
    
    return result


# ═══════════════════════════════════════════════════════════════
# 6. DIAGNÓSTICO
# ═══════════════════════════════════════════════════════════════

def get_catalog_text() -> str:
    """Genera texto legible del catálogo de agentes."""
    catalog = _load_catalog()
    agents = catalog.get("agents", [])
    
    if not agents:
        return "[Replicator] Catálogo vacío — sin agentes replicados aún"
    
    lines = [
        "\n" + "=" * 60,
        "  🔬 AGENT REPLICATION ENGINE — Catálogo",
        "=" * 60,
    ]
    
    for agent in agents:
        lines.append(f"\n  • {agent.get('name', '?')} ({agent.get('agent_id', '?')})")
        lines.append(f"    Dominio: {agent.get('source_domain', '?')} → {agent.get('target_domain', '?')}")
        lines.append(f"    Estado: {agent.get('status', '?')}")
        lines.append(f"    Creado: {agent.get('created_at', '?')[:10]}")
    
    lines.append("=" * 60)
    return "\n".join(lines)
