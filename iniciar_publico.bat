@echo off
setlocal

cd /d "%~dp0"

echo ==============================================
echo  VENTAS - Inicio publico (Flask + ngrok)
echo ==============================================

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] No se encontro .venv\Scripts\activate.bat
    echo Crea/activa el entorno virtual antes de usar este script.
    pause
    exit /b 1
)

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] No se encontro el ejecutable de Python en .venv\Scripts\python.exe
    pause
    exit /b 1
)

set "NGROK_EXE=%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
if not exist "%NGROK_EXE%" (
    set "NGROK_EXE=ngrok"
)

if /i "%NGROK_EXE%"=="ngrok" (
    where ngrok >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] No se encontro ngrok. Instala ngrok o corrige la ruta en este archivo.
        pause
        exit /b 1
    )
)

echo [PRECHECK] Verificando que el puerto 5000 este libre...
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo [ERROR] El puerto 5000 ya esta en uso por otro proceso.
    echo Cierra la ventana anterior de Flask o cambia el puerto antes de continuar.
    pause
    exit /b 1
)

echo [1/3] Iniciando servidor Flask en una ventana nueva...
start "Ventas - Servidor Flask" cmd /k ""%PYTHON_EXE%" "%~dp0app.py""

echo [2/3] Esperando a que Flask abra el puerto 5000...
set /a WAIT_SECONDS=0
:wait_flask
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 goto flask_ready
set /a WAIT_SECONDS+=1
if %WAIT_SECONDS% GEQ 25 goto flask_failed
timeout /t 1 /nobreak >nul
goto wait_flask

:flask_failed
echo [ERROR] Flask no abrio el puerto 5000 en 25 segundos.
echo Revisa la ventana "Ventas - Servidor Flask" para ver el error exacto.
pause
exit /b 1

:flask_ready
echo [OK] Flask activo en puerto 5000.

echo [3/3] Iniciando tunel publico ngrok en otra ventana...
start "Ventas - Tunel Publico (ngrok)" "%NGROK_EXE%" http 5000

echo.
echo Intentando leer la URL publica desde la API local de ngrok...
timeout /t 5 /nobreak >nul
powershell -NoProfile -Command "try { ($t=Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels').tunnels | ForEach-Object { $_.public_url } } catch { 'Aun no disponible. Revisa la ventana de ngrok.' }"

echo.
echo Si no aparece URL aqui, revisa la ventana: "Ventas - Tunel Publico (ngrok)".
echo Para cerrar todo, cierra ambas ventanas.
pause
