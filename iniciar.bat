@echo off
cd /d "C:\Users\dajha\Proyectos\Ventas"

if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: No se encontro el entorno virtual
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo Iniciando servidor Flask...
echo.

:: Iniciar el servidor en segundo plano
start /B python app.py

:: Esperar a que el servidor inicie
timeout /t 3 /nobreak >nul

:: Abrir el navegador
start "" "http://127.0.0.1:5000"

echo.
echo Servidor ejecutandose en http://127.0.0.1:5000
echo Presiona Ctrl+C para detener
echo.
pause
