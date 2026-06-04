# Plan de Mejora del Enjambre — Implementado ✅

## 📊 Estado actual vs Implementado

| Mejora | Estado | Archivo |
|--------|--------|---------|
| Model Router inteligente flash↔pro | ✅ Implementado | `src/model_router.py` |
| Escalado quirúrgico (4 niveles) | ✅ Implementado | `src/model_router.py` |
| Presupuesto dinámico por complejidad | ✅ Implementado | `src/model_router.py` |
| Cortocircuito de bucle (loop detection) | ✅ Implementado | `src/graph.py` |
| Debug Memory para Programador | ✅ Implementado | `src/nodes/programmer.py` |
| Tester con pytest real + tracebacks | ✅ Implementado | `src/nodes/tester.py` |
| Router consciente en todos los nodos | ✅ Implementado | `src/config.py` |

---

## 🧠 Model Router — Estrategia de escalado quirúrgico

### Niveles de escalado

| Nivel | Nombre | Cuándo | Pro usado en |
|------:|--------|--------|-------------|
| 0 | `FLASH_TODO` | Iter 0, sin errores | Solo Gates Auditor |
| 1 | `GATES_PRO` | Iter 1+, errores leves | Gates + nodos críticos |
| 2 | `DEBUG_PRO` | Iter 3+, errores ≥5 | Programador si falla |
| 3 | `PROGRAMADOR_PRO` | Iter 4+, errores ≥10 | Programador + Gates |
| 4 | `TODO_PRO` | Loop detectado o iter ≥5 | Todo |

### Presupuesto por complejidad

| Complejidad | Max calls Pro | Estrategia |
|-------------|:------------:|------------|
| `low` | 1 | Solo para Gates Auditor |
| `medium` | 2 | Gates + 1 debug si es necesario |
| `high` | 4 | Gates + Programador Pro + debug |

### Perfiles de nodo (quién merece Pro)

| Nodo | ¿Crítico? | Beneficio Pro | Usa Pro en nivel |
|------|:---------:|:-------------:|:----------------:|
| Auditor Gate 1 | ✅ | 0.9 | Siempre |
| Auditor Gate 2 | ✅ | 0.9 | Siempre |
| Auditor Gate 3 | ✅ | 0.95 | Siempre |
| Programador | ❌ | 0.7 | Nivel 2+ |
| Arquitecto | ✅ | 0.5 | Nivel 1+ |
| Orquestador | ✅ | 0.3 | Nivel 1+ |
| Tester | ❌ | 0.4 | Nivel 2+ |
| Investigador | ❌ | 0.1 | Nunca |
| Extractor | ❌ | 0.1 | Nunca |

---

## 🔄 Flujo del pipeline con Router

```
Inicio → reset_router(complexity)
         ↓
ParallelPrep (flash)
         ↓
Orquestador (flash)
         ↓
Gate 1 (pro — SIEMPRE)
         ↓
Arquitecto (flash|pro según router)
         ↓
Gate 2 (pro — SIEMPRE si router dice)
         ↓
Programador (router decide flash↔pro)
         ↓
Tester (router decide flash↔pro + pytest real)
         ↓
┌─ PASS → Extractor (flash)
│  FAIL → ¿Loop? → Sí → Cortocircuito → Diagnóstico
│       → No → ¿Iter < 3? → Programador (flash)
│       → No → ¿Iter ≥ 3? → Gate 3 (pro) + Programador (pro si presupuesto)
│       → No → ¿Iter ≥ 5? → Programador (pro siempre)
└─────────────────────────────────────────
```

## 📈 Costo estimado por ejecución típica

| Tarea | Calls Flash | Calls Pro | Costo |
|-------|:----------:|:---------:|:-----:|
| Simple (low) | 6-7 | 1-2 | ~$0.002 |
| Media (medium) | 7-10 | 2-3 | ~$0.005 |
| Compleja (high) | 10-15 | 3-5 | ~$0.010 |

*Flash es gratis (Zen). Pro cuesta ~$0.002 por call.*
