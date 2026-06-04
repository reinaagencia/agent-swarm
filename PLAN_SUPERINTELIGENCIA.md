# PLAN SUPERINTELIGENCIA CONTINUA — v2.0

> Transformación del enjambre-dev en un sistema agéntico de frontera con capacidad de auto-mejora continua, replicación y evaluación comparativa.

## 📊 Estado Actual vs Objetivo

| Dimensión | Actual | Objetivo |
|-----------|--------|----------|
| **Self-correction** | Básica (scratchpad + debug_history) | Reflexión verbal completa (episodic memory + auto-crítica) |
| **Tool use** | Solo LLM + write files | Bash scripting + MCP + sandbox + code execution |
| **Memory** | Flat JSON lessons | Knowledge graph + vector embeddings + episodic buffer |
| **Evaluation** | Manual (test_report binario) | SWE-bench compatible + reward model |
| **Learning** | Post-hoc reflection | Online RL con self-play |
| **Replication** | No existe | Engine para clonar skills a nuevos dominios |
| **Multi-LLM** | Flash/Pro binario | Orquestación dinámica N-modelos |
| **Benchmarks** | Ninguno | Suite automatizada con tracking temporal |

## 🏗️ Módulos de Transformación

### Módulo 1: Meta-Cognición con Reflexión Verbal (Reflexion-style)
**Duración**: 30 min | **Ejercicios**: 3

#### Ejercicio 1.1: Episodic Memory Buffer
Implementar un buffer de memoria episódica que almacene:
- El requerimiento completo
- El plan original (blueprint)
- El código generado
- Los errores encontrados
- El "reflective text" del agente (auto-crítica)
- La señal de refuerzo

```python
# Estructura del buffer episódico
{
    "episode_id": "uuid",
    "requirement": "...",
    "plan": { ... },
    "code": { ... },
    "errors": [...],
    "self_reflection": "Lo que salió mal y por qué...",
    "reinforcement_signal": 0.75,
    "heuristics_learned": [
        "Para tareas X, siempre verificar imports Y",
        "El patrón Z falla cuando W"
    ]
}
```

#### Ejercicio 1.2: Auto-Crítica Generativa
Antes de cada iteración, el Programador debe:
1. Leer su propia reflexión del episodio anterior
2. Identificar qué salió mal específicamente
3. Proponer un plan de corrección explícito
4. Comparar el código nuevo contra los errores conocidos

#### Ejercicio 1.3: Heurísticas Aprendidas
Del buffer de episodios, extraer heurísticas generalizables:
- Patrones de éxito → reglas reutilizables
- Anti-patrones → checklist de verificación
- Pitfalls → advertencias automáticas

**Criterio de éxito**: El Programador NO repite el mismo error dos veces en el mismo dominio.

---

### Módulo 2: Agente Bash-Native (mini-SWE-agent style)
**Duración**: 30 min | **Ejercicios**: 3

#### Ejercicio 2.1: Programador con Shell Real
En lugar de solo generar archivos, el Programador puede:
- Ejecutar `python3 script.py` para probar su código
- Usar `pip install` para dependencias
- Correr `pytest` directamente
- Ver el output real de sus comandos

#### Ejercicio 2.2: Historial Lineal
Seguir el patrón mini-SWE-agent:
- Cada paso del agente es un mensaje en la historia
- No hay bifurcaciones complejas
- El "state" es simplemente la conversación acumulada

#### Ejercicio 2.3: Sandbox Local
- Ejecutar código en subprocess con timeout
- Capturar stdout/stderr
- Volumen montado para archivos compartidos

**Criterio de éxito**: El Programador puede auto-corregirse basado en output real de ejecución.

---

### Módulo 3: Benchmark Suite y Eval Automática
**Duración**: 30 min | **Ejercicios**: 2

#### Ejercicio 3.1: Generación Automática de Tests
- Analizar el blueprint y generar tests unitarios
- Ejecutar code coverage
- Reportar métricas de calidad

#### Ejercicio 3.2: Tracking Temporal
- Guardar resultados de cada ejecución con timestamp
- Calcular tendencias (mejora/empeora)
- Alertar si el rendimiento baja

**Criterio de éxito**: Cada ejecución produce un reporte de rendimiento completo.

---

### Módulo 4: Self-Play y Generación de Datos de Entrenamiento
**Duración**: 30 min | **Ejercicios**: 2

#### Ejercicio 4.1: Generación de Pares (Problema → Solución)
De cada ejecución exitosa, extraer:
- El problema (requirement)
- La solución (código final)
- El proceso (iteraciones, errores, correcciones)
- La metadata (dominio, complejidad, modelos usados)

#### Ejercicio 4.2: Fine-tuning Data Pipeline
- Formatear los pares como datos de entrenamiento
- Almacenar en formato estándar (JSONL)
- Preparar para futuro fine-tuning

**Criterio de éxito**: 100+ pares de entrenamiento generados automáticamente.

---

### Módulo 5: Agente Replication Engine
**Duración**: 30 min | **Ejercicios**: 2

#### Ejercicio 5.1: Skill Cloning
- Analizar la estructura de un agente exitoso
- Extraer su "receta" (prompts, config, thresholds)
- Generar automáticamente un nuevo subagente con la misma receta

#### Ejercicio 5.2: Cross-Domain Transfer
- Tomar un patrón aprendido en dominio A
- Adaptarlo automáticamente al dominio B
- Validar que funciona

**Criterio de éxito**: Nuevo subagente funcional creado en < 5 minutos.

---

### Módulo 6: Multi-LLM Orchestrator Inteligente
**Duración**: 30 min | **Ejercicios**: 2

#### Ejercicio 6.1: Dynamic Model Selection
- Basado en el requerimiento, seleccionar el mejor modelo
- Considerar: tipo de tarea, complejidad, presupuesto, historial
- Soporte para: DeepSeek V4 Flash, Pro, GPT-4o, Claude Sonnet, Gemini

#### Ejercicio 6.2: Ensemble Decoding
- Para decisiones críticas, consultar 2+ modelos
- Si hay consenso → usar
- Si hay conflicto → tercer modelo desempata

**Criterio de éxito**: 15% mejora en tasa de éxito en primera iteración.

---

## 📈 Métricas de Éxito

| KPI | Actual | Target | Medición |
|-----|--------|--------|----------|
| Tasa de éxito (PASS) | ~60% | >85% | `scoreboard.json` |
| Iteraciones promedio | 4-5 | <3 | `router_stats.history` |
| Errores reintroducidos | Sí | 0 | `debug_history` |
| Auto-corrección sin Gate3 | 30% | >80% | `audit_trail` |
| Reutilización de lecciones | Manual | Automática | `lessons_engine` |
| Tiempo por tarea | ~3 min | <90s | `metrics` |
| Nuevos dominios aprendidos | 0/mes | >5/mes | `skills/` count |

## 🚀 Orden de Implementación

```
Semana 1: Módulo 1 (Meta-Cognición) → Impacto inmediato en calidad
Semana 1: Módulo 2 (Bash-Native) → Ejecución real auto-corregida
Semana 2: Módulo 3 (Benchmarks) → Medición objetiva
Semana 2: Módulo 4 (Self-Play) → Generación de datos
Semana 3: Módulo 5 (Replication) → Escalabilidad
Semana 3: Módulo 6 (Multi-LLM) → Rendimiento óptimo
```
