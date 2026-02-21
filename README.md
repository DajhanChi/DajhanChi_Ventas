# 📦 Sistema de Ventas

Sistema de gestión de ventas desarrollado con Flask, SQLite y Bootstrap.

## 🚀 Formas de Ejecutar

### 1️⃣ Ejecutar como Ejecutable (Recomendado para distribución)

**Para crear el ejecutable:**
```batch
build_exe.bat
```

**Ubicación del ejecutable:**
```
dist\SistemaVentas\SistemaVentas.exe
```

**Para probar el ejecutable y ver errores:**
```batch
test_exe.bat
```

### 2️⃣ Ejecutar con Python (Desarrollo)

**Opción A - Usando launcher:**
```batch
run_app.bat
```

**Opción B - Ejecutar directamente:**
```batch
.venv\Scripts\activate
python app.py
```

## 📋 Requisitos (Solo para desarrollo)

- Python 3.10+
- Ver `requirements.txt` para las dependencias

```bash
pip install -r requirements.txt
```

## 🎯 Características

- ✅ Gestión de productos
- ✅ Registro de ventas
- ✅ Control de deudas/créditos
- ✅ Reportes y estadísticas
- ✅ Sistema de usuarios
- ✅ Autenticación segura

## 🔐 Acceso Inicial

**Usuario por defecto:**
- Usuario: `admin`
- Contraseña: `admin123`

⚠️ **IMPORTANTE:** Cambiar la contraseña después del primer inicio.

## 📁 Estructura del Proyecto

```
Ventas/
├── app.py                    # Aplicación principal
├── launcher.py               # Launcher para el ejecutable
├── requirements.txt          # Dependencias
├── ventas.spec              # Configuración PyInstaller
├── build_exe.bat            # Construir ejecutable (Windows)
├── build_exe.ps1            # Construir ejecutable (PowerShell)
├── run_app.bat              # Ejecutar en modo desarrollo
├── test_exe.bat             # Probar ejecutable
├── installer_script.iss     # Script Inno Setup (instalador)
├── templates/               # Plantillas HTML
├── static/                  # Archivos estáticos (CSS/JS)
└── migrations/              # Migraciones de base de datos
```

## 📚 Documentación Adicional

- [📘 Cómo crear el ejecutable](COMO_CREAR_EJECUTABLE.md)
- [🔧 Solución de problemas](SOLUCION_PROBLEMAS.md)

## 🛠️ Desarrollo

### Activar entorno virtual
```bash
.venv\Scripts\activate
```

### Crear migración
```bash
flask db migrate -m "descripción"
```

### Aplicar migración
```bash
flask db upgrade
```

## 📦 Distribución

### Para compartir con usuarios finales:

1. **Construye el ejecutable:**
   ```batch
   build_exe.bat
   ```

2. **Comprime la carpeta:**
   ```
   dist\SistemaVentas\ → SistemaVentas.zip
   ```

3. **Comparte el ZIP**
   - Los usuarios solo necesitan extraer y ejecutar `SistemaVentas.exe`
   - No necesitan Python ni dependencias

### Para crear un instalador profesional:

1. Instala [Inno Setup](https://jrsoftware.org/isdl.php)
2. Abre `installer_script.iss` con Inno Setup
3. Compila → Obtendrás `Setup_SistemaVentas.exe`

## 💾 Base de Datos

- **Desarrollo:** `instance/app.db`
- **Ejecutable:** `%APPDATA%\SistemaVentas\app.db`

## 🐛 Solución de Problemas

Si el ejecutable no funciona, ver [SOLUCION_PROBLEMAS.md](SOLUCION_PROBLEMAS.md)

**Problema común:** El programa se cierra inmediatamente
- **Solución:** Ejecuta `test_exe.bat` para ver el error

## 📝 Licencia

Proyecto personal de gestión de ventas.

---

**Última actualización:** Febrero 2026
