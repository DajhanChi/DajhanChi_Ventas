# Script para crear un acceso directo con icono para iniciar.bat
$rutaBat = "C:\Users\dajha\Proyectos\Ventas\iniciar.bat"
$rutaEscritorio = [Environment]::GetFolderPath("Desktop")
$rutaAcceso = "$rutaEscritorio\Iniciar Ventas.lnk"
$rutaIcono = "C:\Users\dajha\Proyectos\Ventas\ico\DajhanChi.ico"

# Crear el COM object para el atajo
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($rutaAcceso)

# Configurar propiedades
$Shortcut.TargetPath = $rutaBat
$Shortcut.WorkingDirectory = "C:\Users\dajha\Proyectos\Ventas"
$Shortcut.IconLocation = $rutaIcono
$Shortcut.WindowStyle = 1  # Normal window
$Shortcut.Description = "Inicia el servidor de Ventas"

# Guardar el atajo
$Shortcut.Save()

Write-Host "Acceso directo creado en: $rutaAcceso"
Write-Host "Se usa el icono: DajhanChi.ico"
