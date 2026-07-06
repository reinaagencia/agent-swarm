<#
🧠 Agent Swarm Installer — v1.0 (Windows PowerShell)
=====================================================
Un solo comando para desplegar el Enjambre de Agentes
Superinteligente en una máquina Windows.

USO (PowerShell como Administrador):
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .\install-agent-swarm.ps1
#>

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.ForegroundColor = "Green"

Write-Host ""
Write-Host "  🧠  ENJAMBRE DE AGENTES — SUPERINTELIGENCIA CONTINUA"
Write-Host "             Instalación Automatizada (Windows)"
Write-Host ""

# ── 1. Verificar Python ──
Write-Host "`n📋 1. Verificando Python 3.11+..." -ForegroundColor Cyan

$python = $null
$python_versions = @("python3", "python", "py")
foreach ($cmd in $python_versions) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "(\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 11) {
                $python = $cmd
                Write-Host "✅ Python $version encontrado" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Host "⚠️  Python 3.11+ no encontrado. Instalando..." -ForegroundColor Yellow
    Write-Host "  Abre https://www.python.org/downloads/ en tu navegador"
    Write-Host "  Descarga Python 3.11+ (marca 'Add Python to PATH')"
    Write-Host "  Luego vuelve a ejecutar este script.`n"
    Write-Host "  O ejecuta en PowerShell como Administrador:" -ForegroundColor Gray
    Write-Host "    winget install Python.Python.3.11" -ForegroundColor Gray
    Read-Host "`nPresiona Enter cuando hayas instalado Python"
    
    # Re-verificar
    try {
        $version = & python --version 2>&1
        if ($version -match "3\.(1[1-9]|[2-9]\d)") {
            $python = "python"
            Write-Host "✅ Python $version encontrado" -ForegroundColor Green
        } else {
            throw "Python version incorrecta"
        }
    } catch {
        Write-Host "❌ Python no detectado. Instálalo manualmente." -ForegroundColor Red
        exit 1
    }
}

# ── 2. Verificar Git ──
Write-Host "`n📦 2. Verificando Git..." -ForegroundColor Cyan
try { git --version 2>&1 | Out-Null; Write-Host "✅ Git OK" -ForegroundColor Green }
catch {
    Write-Host "⚠️  Instalando Git..." -ForegroundColor Yellow
    try { winget install Git.Git -h --accept-package-agreements | Out-Null }
    catch {
        Write-Host "  Abre https://git-scm.com/download/win, instala y vuelve" -ForegroundColor Yellow
        Read-Host "`nPresiona Enter cuando hayas instalado Git"
    }
}

# ── 3. Clonar repo ──
Write-Host "`n📥 3. Clonando Agent Swarm..." -ForegroundColor Cyan
$targetDir = "$env:USERPROFILE\agent-swarm"

if (Test-Path $targetDir) {
    Write-Host "⚠️  El directorio $targetDir ya existe." -ForegroundColor Yellow
    $resp = Read-Host "  ¿Sobrescribir? (s/N)"
    if ($resp -eq "s" -or $resp -eq "S") {
        Remove-Item -Recurse -Force $targetDir
    }
}

if (-not (Test-Path $targetDir)) {
    git clone --depth 1 https://github.com/reinaagenciacol/agent-swarm.git $targetDir
    Write-Host "✅ Repositorio clonado" -ForegroundColor Green
}

Set-Location $targetDir

# ── 4. Entorno virtual ──
Write-Host "`n🔧 4. Creando entorno virtual..." -ForegroundColor Cyan
if (Test-Path ".venv") {
    Write-Host "  Entorno virtual ya existe" -ForegroundColor Yellow
} else {
    & $python -m venv .venv
    Write-Host "✅ Entorno virtual creado" -ForegroundColor Green
}

# Activar venv
.\.venv\Scripts\Activate.ps1

# ── 5. Configurar .env ──
Write-Host "`n🔑 5. Configurando API keys..." -ForegroundColor Cyan

$reconfig = $false
if (Test-Path ".env") {
    Write-Host "⚠️  Archivo .env ya existe." -ForegroundColor Yellow
    $resp = Read-Host "  ¿Reconfigurar? (s/N)"
    if ($resp -eq "s" -or $resp -eq "S") { $reconfig = $true }
} else { $reconfig = $true }

if ($reconfig) {
    Write-Host "`n► OPENCODE API KEY (obténla en https://opencode.ai/account):" -ForegroundColor Cyan
    $apiKey = Read-Host "  OPENCODE_API_KEY"
    while ([string]::IsNullOrEmpty($apiKey)) {
        Write-Host "  La API key es obligatoria" -ForegroundColor Yellow
        $apiKey = Read-Host "  OPENCODE_API_KEY"
    }

    Write-Host "`n► SUPABASE (opcional — presiona Enter para omitir):" -ForegroundColor Cyan
    $supaUrl = Read-Host "  SUPABASE_URL"
    $supaKey = Read-Host "  SUPABASE_SERVICE_KEY"

    @"
# OpenCode API — DeepSeek V4 Flash
OPENCODE_API_KEY=$apiKey
OPENCODE_BASE_URL=https://opencode.ai/zen/v1
OPENCODE_MODEL=deepseek-v4-flash-free
OPENCODE_MODE=max

# Supabase (opcional)
SUPABASE_URL=$supaUrl
SUPABASE_SERVICE_KEY=$supaKey
"@ | Out-File -FilePath .env -Encoding ASCII

    Write-Host "✅ Archivo .env creado" -ForegroundColor Green
}

# ── 6. Instalar dependencias ──
Write-Host "`n📚 6. Instalando dependencias Python..." -ForegroundColor Cyan
& $python -m pip install --upgrade pip -q
& $python -m pip install -r requirements.txt -q
Write-Host "✅ Dependencias instaladas" -ForegroundColor Green

# ── 7. Verificar ──
Write-Host "`n🔍 7. Verificando configuración..." -ForegroundColor Cyan
try {
    $output = & $python main.py --verify 2>&1 | Out-String
    Write-Host $output
    Write-Host "`n✅ Configuración verificada correctamente" -ForegroundColor Green
} catch {
    Write-Host "❌ Error en verificación. Revisa tus API keys." -ForegroundColor Red
    exit 1
}

# ── Resumen ──
Write-Host "`n🎉 INSTALACIÓN COMPLETADA" -ForegroundColor Green
Write-Host "=" * 50 -ForegroundColor Green
Write-Host "  📍 Directorio: $targetDir" -ForegroundColor Cyan
Write-Host "  🐍 Python:     $(& $python --version 2>&1)"
Write-Host ""
Write-Host "  Próximos pasos:" -ForegroundColor White
Write-Host "  1. Para ejecutar:"
Write-Host "     cd $targetDir"
Write-Host "     .venv\Scripts\Activate.ps1"
Write-Host "     python main.py"
Write-Host ""
Write-Host "  2. Con un requerimiento:"
Write-Host "     python main.py `"Crea una API REST...`""
Write-Host ""
Write-Host "  3. Solo verificar configuración:"
Write-Host "     python main.py --verify"
Write-Host ""

Read-Host "`nPresiona Enter para salir"
