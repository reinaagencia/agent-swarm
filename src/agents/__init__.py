"""Agentes especializados del Enjambre 4.0.

Cada agente es un módulo independiente con prompt propio, herramientas y memoria.
Smith 1.0 es el orquestador principal que delega a los demás agentes.

Agentes disponibles:
    - smith:      Orquestador principal con model router flash↔pro
    - auditor:    (futuro) Validación de calidad (pro)
    - trader:     (futuro) Análisis financiero
    - visor:      (futuro) Análisis multimodal
    - investigador: (futuro) Research multi-fuente
    - arquitecto: (futuro) Diseño de sistemas
    - programador: (futuro) Generación de código
    - tester:     (futuro) QA y validación
    - extractor:  (futuro) Destilación de conocimiento
    - estratega:  (futuro) Planificación y descomposición de tareas
    - desplegador: (futuro) Instalación y despliegue multi-cliente
"""
