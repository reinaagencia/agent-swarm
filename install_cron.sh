#!/bin/bash
# 🕐 Instalación de Operación Continua para el Enjambre Superinteligente
#
# Este script instala las tareas programadas en cron para ejecución automática
# de las operaciones diarias del negocio.
#
# USO:
#   ./install_cron.sh              # Instala todas las tareas
#   ./install_cron.sh --status     # Muestra estado actual
#   ./install_cron.sh --remove     # Elimina todas las tareas

CRON_FILE="/tmp/enjambre_cron"
SCRIPT_PATH="/Users/isabeldiaz/Dev/agent-swarm/run_daily_operations.sh"

case "${1:-install}" in
    install)
        echo "🕐 Instalando operación continua del Enjambre..."
        
        # Respaldar cron actual
        crontab -l > /tmp/crontab_backup 2>/dev/null || true
        
        # Agregar nuestras tareas (solo si no existen ya)
        if grep -q "run_daily_operations" /tmp/crontab_backup 2>/dev/null; then
            echo "⚠️  Las tareas ya están instaladas. Usa --remove y luego install para reinstalar."
            crontab -l
            exit 0
        fi
        
        cat >> /tmp/crontab_backup << 'CRON'

# ══════════════════════════════════════════════════════════
# 🏢 ENJAMBRE SUPERINTELIGENTE — Operación Continua
# ══════════════════════════════════════════════════════════

# 6:00 AM - Días hábiles: Rutina completa
30 6 * * 1-5 /Users/isabeldiaz/Dev/agent-swarm/run_daily_operations.sh

# 12:00 PM - Mediodía: Solo tareas críticas
0 12 * * 1-5 /Users/isabeldiaz/Dev/agent-swarm/run_daily_operations.sh --quick

# 6:00 PM - Cierre: Generar reporte del día
0 18 * * 1-5 /Users/isabeldiaz/Dev/agent-swarm/run_daily_operations.sh --report

# ══════════════════════════════════════════════════════════
CRON
        
        crontab /tmp/crontab_backup
        echo "✅ Tareas instaladas en cron:"
        echo "   • 6:30 AM — Rutina completa (facturas, obras, conciliación)"
        echo "   • 12:00 PM — Tareas críticas rápido"
        echo "   • 6:00 PM — Reporte de cierre del día"
        echo ""
        echo "📋 Cron actual:"
        crontab -l
        ;;
        
    status)
        echo "📋 Estado de la operación continua:"
        echo ""
        if crontab -l | grep -q "run_daily_operations"; then
            echo "✅ Tareas instaladas:"
            crontab -l | grep "run_daily_operations"
        else
            echo "❌ No hay tareas instaladas"
            echo "   Ejecuta: ./install_cron.sh"
        fi
        echo ""
        echo "📊 Últimas ejecuciones:"
        ls -lt /Users/isabeldiaz/Dev/agent-swarm/logs/*.log 2>/dev/null | head -5 || echo "   (sin logs aún)"
        echo ""
        echo "📈 Resumen más reciente:"
        cat /Users/isabeldiaz/Dev/agent-swarm/logs/summary_latest.json 2>/dev/null || echo "   (sin resumen aún)"
        ;;
        
    remove)
        echo "🗑️  Eliminando operación continua..."
        crontab -l | grep -v "run_daily_operations" | crontab -
        echo "✅ Tareas eliminadas"
        ;;
        
    *)
        echo "USO: $0 [install|status|remove]"
        exit 1
        ;;
esac
