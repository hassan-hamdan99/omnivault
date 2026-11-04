@echo off
chcp 65001 > nul
echo.
echo ╔══════════════════════════════════╗
echo ║     Omnivault — Setup            ║
echo ╚══════════════════════════════════╝
echo.

:: Verificar Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python não encontrado.
    echo Instale o Python 3.11 ou 3.12 em https://python.org
    echo e marque "Add python.exe to PATH" no instalador.
    pause
    exit /b 1
)

echo [1/3] Instalando dependências Python...
cd /d "%~dp0backend"
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERRO] Falha na instalação das dependências.
    echo Confira se o Python é 3.11 ou 3.12 ^(3.13+ ainda não é suportado^).
    pause
    exit /b 1
)
cd /d "%~dp0"

echo [2/3] Criando pastas necessárias...
if not exist "credentials" mkdir credentials
if not exist "cache\covers" mkdir cache\covers
if not exist "cache\comics" mkdir cache\comics

echo [3/3] Atalho na Área de Trabalho
choice /C SN /M "Criar o atalho Omnivault na Área de Trabalho"
if not errorlevel 2 call "%~dp0criar-atalho.bat"

echo.
echo ✅ Setup concluído!
echo.
echo Para iniciar: atalho Omnivault na Área de Trabalho (ou start.bat).
echo Google Drive (opcional): veja docs\GOOGLE_DRIVE.md
echo Guia completo: README.md
echo.
pause
