#!/usr/bin/env bash
# ==============================================================================
# 🧠 Agent Swarm Installer — v1.0
# ==============================================================================
# Un solo comando para desplegar el Enjambre de Agentes Superinteligente
# en la máquina del cliente.
#
# USO:
#   curl -fsSL https://raw.githubusercontent.com/reinaagenciacol/agent-swarm/main/install-agent-swarm.sh | bash
#   ~~~~ o ~~~~
#   bash install-agent-swarm.sh
#
# REQUISITOS: macOS 12+ o Linux (Ubuntu 22+), conexión a internet
# ==============================================================================

set -e

# ░░░░░░░░░░░░░░ COLORES ░░░░░░░░░░░░░░
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
BOLD='\033[1m'
info()  { echo -e "${BLUE}🔹${NC} $1"; }
ok()    { echo -e "${GREEN}✅${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; }
header(){ echo -e "\n${CYAN}════════════════════════════════════════════════════════════${NC}"; echo -e "${BOLD}$1${NC}"; echo -e "${CYAN}────────────────────────────────────────────────────────────────${NC}"; }

# ░░░░░░░░░░░░░░ BIENVENIDA ░░░░░░░░░░░░░░
clear
cat << "EOF"
  🧠  ENJAMBRE DE AGENTES — SUPERINTELIGENCIA CONTINUA
             Instalación Automatizada
EOF
echo ""

# ░░░░░░░░░░░░░░ VERIFICACIÓN DE SO ░░░░░░░░░░░░░░
header "📋 1. Verificando sistema operativo"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin)
        os_name="macOS"
        os_version=$(sw_ver -productVersion 2>/dev/null || echo "desconocido")
        info "Sistema: macOS $os_version ($ARCH)"
        # Verificar versión mínima
        if [[ "$(echo $os_version | cut -d. -f1)" -lt 12 ]]; then
            error "Se requiere macOS 12+ (tienes $os_version)"
            exit 1
        fi
        ;;
    Linux)
        os_name="Linux"
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            os_version="$PRETTY_NAME"
        else
            os_version="desconocido"
        fi
        info "Sistema: $os_version ($ARCH)"
        ;;
    *)
        error "SO no soportado: $OS. Se requiere macOS o Linux."
        exit 1
        ;;
esac
ok "Sistema operativo compatible: $os_name"

# ░░░░░░░░░░░░░░ PYTHON ░░░░░░░░░░░░░░
header "🐍 2. Verificando Python 3.11+"

PYTHON=""
for cmd in python3.11 python3.12 python3.13 python3; do
    if command -v "$cmd" &>/dev/null; then
        pyver=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
        pymajor=$(echo "$pyver" | cut -d. -f1)
        pyminor=$(echo "$pyver" | cut -d. -f2)
        if [[ "$pymajor" -ge 3 && "$pyminor" -ge 11 ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -n "$PYTHON" ]; then
    ok "Python $($PYTHON --version 2>&1) encontrado"
else
    warn "Python 3.11+ no encontrado. Instalando..."
    if [[ "$OS" == "Darwin" ]]; then
        # macOS: intentar con Homebrew
        if command -v brew &>/dev/null; then
            info "Instalando Python 3.11 con Homebrew..."
            brew install python@3.11
            PYTHON="$(brew --prefix python@3.11)/bin/python3.11"
        else
            warn "Homebrew no instalado. Intentando instalar..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            brew install python@3.11
            PYTHON="$(brew --prefix python@3.11)/bin/python3.11"
        fi
    elif [[ "$OS" == "Linux" ]]; then
        # Linux: apt install
        if command -v apt &>/dev/null; then
            sudo apt update -qq && sudo apt install -y -qq python3.11 python3.11-venv python3.11-dev
            PYTHON="python3.11"
        else
            error "No se pudo instalar Python 3.11 automáticamente."
            error "Instálalo manualmente y vuelve a ejecutar este script."
            exit 1
        fi
    fi
    ok "Python $($PYTHON --version 2>&1) instalado"
fi

# ░░░░░░░░░░░░░░ GIT ░░░░░░░░░░░░░░
header "📦 3. Verificando Git"

if ! command -v git &>/dev/null; then
    warn "Git no encontrado. Instalando..."
    if [[ "$OS" == "Darwin" ]]; then
        xcode-select --install 2>/dev/null || true
        # Si xcode-select no funciona, esperar o usar brew
        if ! command -v git &>/dev/null; then
            brew install git
        fi
    elif command -v apt &>/dev/null; then
        sudo apt install -y -qq git
    fi
fi
ok "Git $(git --version 2>&1)"

# ░░░░░░░░░░░░░░ CLONAR REPO ░░░░░░░░░░░░░░
header "📥 4. Clonando Agent Swarm"

TARGET_DIR="$HOME/agent-swarm"

if [ -d "$TARGET_DIR" ]; then
    warn "El directorio $TARGET_DIR ya existe."
    read -p "  ¿Sobrescribir? (s/N): " OVERWRITE
    if [[ "$OVERWRITE" =~ ^[sS]$ ]]; then
        rm -rf "$TARGET_DIR"
    else
        info "Usando directorio existente..."
    fi
fi

if [ ! -d "$TARGET_DIR" ]; then
    git clone --depth 1 https://github.com/reinaagenciacol/agent-swarm.git "$TARGET_DIR"
    ok "Repositorio clonado en $TARGET_DIR"
fi

cd "$TARGET_DIR"

# ░░░░░░░░░░░░░░ ENTORNO VIRTUAL ░░░░░░░░░░░░░░
header "🔧 5. Creando entorno virtual"

if [ -d ".venv" ]; then
    info "Entorno virtual ya existe"
else
    "$PYTHON" -m venv .venv
    ok "Entorno virtual creado"
fi

source .venv/bin/activate

# ░░░░░░░░░░░░░░ CONFIGURACIÓN .env ░░░░░░░░░░░░░░
header "🔑 6. Configurando API keys"

if [ -f ".env" ]; then
    warn "Archivo .env ya existe. ¿Deseas reconfigurarlo?"
    read -p "  ¿Reconfigurar? (s/N): " RECONFIG
    if [[ ! "$RECONFIG" =~ ^[sS]$ ]]; then
        info "Manteniendo .env existente"
        HAS_ENV=true
    fi
fi

if [ ! -f ".env" ] || [[ "$RECONFIG" =~ ^[sS]$ ]]; then
    echo ""
    info "Necesitamos configurar las API keys."
    echo "  (Las escribirás directamente, no se almacenan en ningún otro lado)"
    echo ""

    # ── OPENCODE API KEY ──────────────────────────────────────────────
    echo -e "${CYAN}► OPENCODE API KEY${NC}"
    echo "  Tu API key de OpenCode (cuenta reinaagenciacol@gmail.com)"
    echo "  La obtienes en: https://opencode.ai/account"
    echo ""
    read -p "  OPENCODE_API_KEY: " OPENCODE_API_KEY
    while [ -z "$OPENCODE_API_KEY" ]; do
        warn "La API key es obligatoria"
        read -p "  OPENCODE_API_KEY: " OPENCODE_API_KEY
    done

    # ── SUPABASE URL ──────────────────────────────────────────────────
    echo ""
    echo -e "${CYAN}► SUPABASE${NC}"
    echo "  URL de tu proyecto Supabase (ej: https://xxxxx.supabase.co)"
    echo ""
    read -p "  SUPABASE_URL: " SUPABASE_URL

    # ── SUPABASE KEY ──────────────────────────────────────────────────
    echo ""
    echo "  Service Role Key de Supabase (Settings → API → service_role key)"
    echo ""
    read -p "  SUPABASE_SERVICE_KEY: " SUPABASE_SERVICE_KEY

    cat > .env << EOF
# OpenCode API — DeepSeek V4 Flash
OPENCODE_API_KEY=${OPENCODE_API_KEY}
OPENCODE_BASE_URL=https://opencode.ai/zen/v1
OPENCODE_MODEL=deepseek-v4-flash-free
OPENCODE_MODE=max

# Supabase (opcional — el pipeline funciona sin ella)
SUPABASE_URL=${SUPABASE_URL}
SUPABASE_SERVICE_KEY=${SUPABASE_SERVICE_KEY}
EOF

    ok "Archivo .env creado en $TARGET_DIR/.env"
fi

chmod 600 .env 2>/dev/null || true

# ░░░░░░░░░░░░░░ INSTALAR DEPENDENCIAS ░░░░░░░░░░░░░░
header "📚 7. Instalando dependencias Python"

"$PYTHON" -m pip install --upgrade pip -q
"$PYTHON" -m pip install -r requirements.txt -q
ok "Dependencias instaladas"

# ░░░░░░░░░░░░░░ VERIFICAR CONFIGURACIÓN ░░░░░░░░░░░░░░
header "🔍 8. Verificando configuración"

set +e
VERIFY_OUTPUT=$("$PYTHON" main.py --verify 2>&1)
VERIFY_EXIT=$?
set -e

echo "$VERIFY_OUTPUT"

if [ $VERIFY_EXIT -ne 0 ]; then
    error "La verificación falló. Revisa tus API keys."
    echo ""
    echo "$VERIFY_OUTPUT" | grep -i "error\|fail\|✗\|missing" || true
    exit 1
fi

ok "Configuración verificada correctamente ✅"

# ░░░░░░░░░░░░░░ REGISTRAR CLIENTE ░░░░░░░░░░░░░░
header "🌐 9. Registrando cliente en Supabase"

HOSTNAME="$(hostname 2>/dev/null || echo 'unknown')"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Registrar en Supabase vía Python directo
"$PYTHON" -c "
import os, json
from dotenv import load_dotenv
load_dotenv()

try:
    from supabase import create_client
    supabase = create_client(
        os.getenv('SUPABASE_URL', ''),
        os.getenv('SUPABASE_SERVICE_KEY', '')
    )
    data = {
        'hostname': '$HOSTNAME',
        'os': '$os_name $os_version',
        'python': '$($PYTHON --version 2>&1)',
        'installed_at': '$TIMESTAMP',
        'status': 'ready'
    }
    result = supabase.table('clientes').insert(data).execute()
    print('✅ Cliente registrado en Supabase')
except Exception as e:
    print('⚠️  No se pudo registrar en Supabase (el pipeline funciona igual):', e)
" 2>&1 || true

# ░░░░░░░░░░░░░░ RESUMEN FINAL ░░░░░░░░░░░░░░
header "🎉 10. Instalación completada"

echo ""
echo -e "  ${GREEN}═══ ENJAMBRE DESPLEGADO ═══${NC}"
echo ""
echo -e "  📍 Directorio:  ${CYAN}$TARGET_DIR${NC}"
echo -e "  🐍 Python:      $($PYTHON --version 2>&1)"
echo -e "  🧠 Modelo:      deepseek-v4-flash-free (Zen)"
echo -e "  ⚖️  Auditor:    deepseek-v4-pro (Go)"
echo -e "  🔁 Fallback:    deepseek-v4-flash (Go, pago)"
echo ""
echo -e "  ${BOLD}Próximos pasos:${NC}"
echo -e "  1. Para ejecutar el pipeline:"
echo -e "     ${CYAN}cd $TARGET_DIR && source .venv/bin/activate && python main.py${NC}"
echo -e ""
echo -e "  2. Para ejecutar con un requerimiento:"
echo -e "     ${CYAN}python main.py \"Crea una API REST en Flask...\"${NC}"
echo -e ""
echo -e "  3. Solo verificar configuración:"
echo -e "     ${CYAN}python main.py --verify${NC}"
echo ""
echo -e "  ${YELLOW}💡 Consejo: Conecta esta máquina vía Tenvo para que${NC}"
echo -e "  ${YELLOW}   Smith (el orquestador) pueda ayudarte remotamente.${NC}"
echo ""
