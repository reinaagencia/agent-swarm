#!/bin/bash
# 🗄️ Supabase Local — Control de la base de datos vectorial
# Uso: ./supabase_local.sh start|stop|status|reset|psql

set -e

DB_NAME="supabase_db"
DB_PORT="54322"
DB_IMAGE="supabase/postgres:15.8.1.020"
DB_NETWORK="supabase_network_agent-swarm"
DB_PASS="postgres"

case "${1:-status}" in
    start)
        echo "🚀 Iniciando Supabase Local..."
        # Asegurar red
        docker network create "$DB_NETWORK" 2>/dev/null || true
        
        # Verificar si ya existe
        if docker ps -a --format '{{.Names}}' | grep -q "^${DB_NAME}$"; then
            docker start "$DB_NAME"
        else
            docker run -d \
                --name "$DB_NAME" \
                --network "$DB_NETWORK" \
                -e POSTGRES_PASSWORD="$DB_PASS" \
                -e POSTGRES_DB=postgres \
                -p "$DB_PORT":5432 \
                "$DB_IMAGE" \
                -c wal_level=logical \
                -c listen_addresses='*' \
                -c max_wal_senders=10 \
                -c max_replication_slots=10
            
            echo "⏳ Esperando que PostgreSQL esté listo..."
            sleep 5
            
            # Aplicar schema
            SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
            if [ -f "$SCRIPT_DIR/src/supabase_schema.sql" ]; then
                docker cp "$SCRIPT_DIR/src/supabase_schema.sql" "$DB_NAME:/tmp/schema.sql"
                docker exec "$DB_NAME" psql -U supabase_admin -f /tmp/schema.sql 2>/dev/null
                docker exec "$DB_NAME" psql -U supabase_admin -c "
                    GRANT ALL PRIVILEGES ON TABLE agent_memory TO postgres;
                    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO postgres;
                " 2>/dev/null
                echo "✅ Schema aplicado"
            fi
        fi
        
        echo "✅ Supabase Local corriendo en puerto $DB_PORT"
        echo "   URL: postgresql://postgres:postgres@127.0.0.1:$DB_PORT/postgres"
        ;;
    
    stop)
        echo "🛑 Deteniendo Supabase Local..."
        docker stop "$DB_NAME" 2>/dev/null || true
        echo "✅ Detenido"
        ;;
    
    status)
        if docker ps --format '{{.Names}}' | grep -q "^${DB_NAME}$"; then
            echo "✅ Corriendo"
            docker exec "$DB_NAME" psql -U postgres -c "
                SELECT 'pgvector: ' || extversion FROM pg_extension WHERE extname = 'vector'
                UNION ALL
                SELECT 'registros: ' || COUNT(*)::text FROM agent_memory;
            " 2>/dev/null
        else
            echo "❌ Detenido"
        fi
        ;;
    
    reset)
        echo "🧹 Reseteando base de datos..."
        docker stop "$DB_NAME" 2>/dev/null || true
        docker rm "$DB_NAME" 2>/dev/null || true
        echo "✅ Eliminado. Usa '$0 start' para recrear."
        ;;
    
    psql)
        shift
        docker exec -it "$DB_NAME" psql -U postgres "$@"
        ;;
    
    *)
        echo "Uso: $0 {start|stop|status|reset|psql}"
        exit 1
        ;;
esac
