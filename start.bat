@echo off
title Omnivault
echo.
echo  ============================================
echo   Omnivault - A iniciar...
echo  ============================================
echo.

cd /d "%~dp0backend"

echo  A verificar dependencias...
python -m pip install -r requirements.txt -q 2>nul
if errorlevel 1 (
    echo.
    echo  ERRO: Falha ao instalar dependencias.
    echo  Garante que o Python esta instalado e adicionado ao PATH.
    echo.
    pause
    exit /b 1
)

echo  Dependencias OK.
echo.
echo  Servidor em http://localhost:8000
echo  O browser abre sozinho quando o servidor estiver pronto.
echo  Para encerrar, usa o botao na app ou Ctrl+C aqui.
echo.
rem Nao abrir o browser aqui: o servidor ainda nao subiu e o service worker
rem serviria a copia em cache (sem API). O main.py abre a aba quando sobe.
python main.py
pause
