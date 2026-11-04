@echo off
rem Omnivault - cria o atalho "Omnivault" na Area de Trabalho, com o icone do app.
rem Pode rodar de novo a qualquer momento (ex.: depois de mover a pasta do projeto).
setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $l=Join-Path $d 'Omnivault.lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($l); $s.TargetPath=Join-Path $env:ROOT 'start.bat'; $s.WorkingDirectory=$env:ROOT; $s.IconLocation=(Join-Path $env:ROOT 'static\emblem.ico')+',0'; $s.Description='Iniciar o Omnivault'; $s.Save(); Write-Host ('  Atalho criado: '+$l)"
if errorlevel 1 (
  echo   Nao foi possivel criar o atalho.
  echo   Alternativa: botao direito em start.bat - Enviar para - Area de trabalho.
)
endlocal
