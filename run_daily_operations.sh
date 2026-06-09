#!/bin/bash
# 🏢 Operación Continua del Enjambre Superinteligente
# Ejecuta las tareas diarias del negocio de forma automática
# 
# USO:
#   ./run_daily_operations.sh              # Ejecuta todas las tareas del día
#   ./run_daily_operations.sh --report     # Solo genera reporte de estado
#   ./run_daily_operations.sh --quick      # Solo tareas críticas
#
# INSTALACIÓN (cron):
#   crontab -e
#   # Agregar: 0 6 * * 1-5 /Users/isabeldiaz/Dev/agent-swarm/run_daily_operations.sh
#   # Esto ejecuta cada día hábil a las 6:00 AM
#
# REQUISITOS:
#   - Python 3.11+ con virtualenv en .venv/
#   - Variables de entorno en .env
#   - Acceso a OpenCode API (plan Zen)

set -e

# ── Configuración ──
PROJECT_DIR="/Users/isabeldiaz/Dev/agent-swarm"
VENV="$PROJECT_DIR/.venv/bin/python3"
LOG_DIR="$PROJECT_DIR/logs"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
LOG_FILE="$LOG_DIR/operations_$TIMESTAMP.log"
SUMMARY_FILE="$LOG_DIR/summary_latest.json"

mkdir -p "$LOG_DIR"

# ── Helper: loggear ──
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ── Banner ──
echo ""
echo "=========================================="
echo "  🏢 ENJAMBRE SUPERINTELIGENTE"
echo "  Operación Continua — $(date)"
echo "=========================================="
echo ""

# ── 1. Verificar entorno ──
log "🔍 Verificando entorno..."
cd "$PROJECT_DIR"

if [ ! -f ".env" ]; then
    log "❌ .env no encontrado. Ejecutar: cp .env.example .env y configurar"
    exit 1
fi

# Probar conexión con API
$VENV -c "from src.config import get_llm; print('✅ API OK')" >> "$LOG_FILE" 2>&1 || {
    log "❌ Error de conexión con API"
    exit 1
}
log "✅ Entorno verificado"

# ── 2. Ejecutar tareas programadas ──
TASKS=()

# Determinar qué tareas ejecutar según el día
DIA_SEMANA=$(date +%u)  # 1=lunes, 7=domingo

if [ "$1" == "--quick" ]; then
    # Solo tareas críticas
    log "⚡ Modo rápido: solo tareas críticas"
    TASKS+=("Procesar facturas del día" "Generar reporte ejecutivo")
elif [ "$1" == "--report" ]; then
    # Solo generar reporte
    log "📊 Generando reporte de estado..."
    cd "$PROJECT_DIR"
    $VENV main.py --report >> "$LOG_FILE" 2>&1
    $VENV main.py --episodic >> "$LOG_FILE" 2>&1
    $VENV main.py --selfplay >> "$LOG_FILE" 2>&1
    log "✅ Reporte generado"
    exit 0
else
    # Rutina completa según día
    TASKS+=("Procesar facturas del día")
    
    if [ "$DIA_SEMANA" -eq 1 ] || [ "$DIA_SEMANA" -eq 4 ]; then
        # Lunes y jueves: tareas pesadas
        TASKS+=("Actualizar avance de obra semanal")
        TASKS+=("Conciliación bancaria")
    fi
    
    TASKS+=("Generar reporte ejecutivo diario")
fi

# ── Ejecutar cada tarea ──
RESULTS=()
TOTAL_TASKS=${#TASKS[@]}
COMPLETED=0
FAILED=0

for TASK in "${TASKS[@]}"; do
    log "🎯 Ejecutando: $TASK"
    
    START_TIME=$(date +%s)
    
    # Ejecutar el pipeline con el requerimiento de la tarea
    $VENV main.py "$TASK" >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    
    if [ $EXIT_CODE -eq 0 ]; then
        log "  ✅ Completada en ${DURATION}s"
        COMPLETED=$((COMPLETED + 1))
        RESULTS+=("✅ $TASK (${DURATION}s)")
    else
        log "  ❌ Falló (exit=$EXIT_CODE) después de ${DURATION}s"
        FAILED=$((FAILED + 1))
        RESULTS+=("❌ $TASK (${DURATION}s)")
    fi
done

# ── 3. Generar resumen del día ──
log ""
log "📊 Resumen del día:"
for R in "${RESULTS[@]}"; do
    log "  $R"
done
log "  Total: $TOTAL_TASKS tareas, $COMPLETED exitosas, $FAILED fallidas"

# Guardar resumen en JSON
cat > "$SUMMARY_FILE" << EOF
{
  "date": "$(date +%Y-%m-%d)",
  "timestamp": "$TIMESTAMP",
  "total_tasks": $TOTAL_TASKS,
  "completed": $COMPLETED,
  "failed": $FAILED,
  "results": $(printf '%s\n' "${RESULTS[@]}" | jq -R . | jq -s . 2>/dev/null || echo '[]'),
  "log_file": "$LOG_FILE"
}
EOF

log "✅ Operación completada. Log: $LOG_FILE"
echo ""
echo "=========================================="
echo "  📊 Operación diaria completada"
echo "  ✅ $COMPLETED/$TOTAL_TASKS tareas exitosas"
echo "  📝 Log: $LOG_FILE"
echo "=========================================="
