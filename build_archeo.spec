# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata, collect_data_files
import sys
import os

block_cipher = None

# =============================================================================
# 1. LISTA MAESTRA DE IMPORTS (OBLIGATORIA PARA PYARMOR)
# =============================================================================
mis_hiddenimports = [
    # A) SEGURIDAD PYARMOR (SÓLO si existe la carpeta)
    'pyarmor_runtime_000000',

    # B) SISTEMA Y RED
    'smtplib', 'ssl', 'email', 'email.message', 'email.mime.text', 
    'email.mime.multipart', 'email.mime.image', 'email.mime.base', 
    'uuid', 'hashlib', 'hmac', 'base64', 'json', 'threading', 'time', 
    'secrets', 'queue', 'logging', 'random', 're', 'io', 'datetime', 
    'subprocess', 'shutil', 'sqlite3', 'ctypes', 'webbrowser', 
    'urllib', 'urllib.parse', 'difflib', 'html', 'collections', 'os', 'sys',
    'collections.abc', 'datetime.timezone','babel', 
    'babel.numbers',

    # C) TUS MÓDULOS (Encriptados)
    'Archeo32n', 'archeon_cloud', 'archeon_music', 'archeon_neuro', 
    'archeon_social', 'archeon_vision', 'sistema_predicciones', 
    'archeon_openrouter', 'archeon_system',
    'archeon_dialog_manager', 'archeon_knowledge', 'archeon_reasoner',

    # D) AUDIO, VISIÓN E IA
    'speech_recognition', 'pyttsx3', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5',
    'pyaudio', 'numpy', 'numpy.core._multiarray_umath', 'PIL', 'PIL.Image', 
    'pyautogui', 'pyscreeze', 'mouseinfo', 'pygetwindow', 'pyrect', 
    'yt_dlp', 'wikipedia', 'pyperclip', 'psutil', 'requests', 'dotenv',

    # E) GOOGLE & FIREBASE (CRÍTICO PARA LA BASE DE DATOS)
    'firebase_admin', 'firebase_admin.firestore', 'firebase_admin.credentials',
    'google.cloud.firestore', 'grpc', 'google.api_core', 'google.auth', 
    'google.protobuf', 'win32timezone', 'babel.numbers', 'pkg_resources',
    'google.generativeai',
    
    # F) UI Y WEB
    'flask', 'flask_cors', 'werkzeug', 'webview', 'webview.platforms.winforms',
    'webview.platforms.qt', 'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtWidgets',
    'PyQt5.QtGui', 'PyQt5.QtWebEngineWidgets', 'PyQt5.sip',
    
    # G) COMUNICACIÓN Y OTROS
    'websockets', 'engineio', 'engineio.async_drivers.threading',
    'winsound', 'pythoncom', 'win32com', 'win32api', 'win32con', 
    'win32process', 'win32security', 'win32evtlog',
    'cryptography', 'OpenSSL', 'charset_normalizer', 'cachetools',
    'rsa', 'comtypes', 'comtypes.client', 'pocketsphinx',
    'requests_toolbelt', 'requests_oauthlib',
]

# =============================================================================
# 2. RECOLECCIÓN AUTOMÁTICA DE DEPENDENCIAS
# =============================================================================
mis_datas = []
mis_binaries = []

# Función auxiliar para recolectar todo de una librería
def recolectar_libreria_completa(nombre):
    global mis_datas, mis_binaries, mis_hiddenimports
    try:
        print(f"🔍 Recolectando {nombre}...")
        tmp_ret = collect_all(nombre)
        mis_datas += tmp_ret[0]
        mis_binaries += tmp_ret[1]
        mis_hiddenimports += tmp_ret[2]
        print(f"   ✓ Añadidos {len(tmp_ret[1])} binarios de {nombre}")
    except Exception as e:
        print(f"   ✗ Error recolectando {nombre}: {e}")

# Recolectamos TODO de las librerías conflictivas
librerias_criticas = [
    'grpc',                     # CRÍTICO: Motor de conexión de Firebase
    'grpcio',                   # CRÍTICO: Motor de conexión de Firebase
    'google.cloud.firestore',   # CRÍTICO: Base de datos
    'firebase_admin',           # CRÍTICO: Admin SDK
    'pyaudio',                  # CRÍTICO: Audio y Micrófono
    'sounddevice',              # CRÍTICO: Audio alternativo
    'speech_recognition',       # CRÍTICO: Escucha
    'pyautogui',                # Control de pantalla
    'yt_dlp',                   # Música
    'PyQt5',                    # UI Web
    'webview',                  # Ventanas
    'flask',                    # Servidor web
    'werkzeug',                 # Middleware Flask
    'babel', 
    'certifi',
]

for lib in librerias_criticas:
    recolectar_libreria_completa(lib)

# Metadatos (Certificados SSL y versiones)
print("📦 Recolectando metadatos...")
packages_to_fix = [
    'google-cloud-firestore', 'firebase-admin', 'grpcio', 'google-api-core',
    'requests', 'charset_normalizer', 'speech_recognition', 'cryptography',
    'OpenSSL', 'numpy', 'PIL', 'certifi', 'yt_dlp', 'pyaudio', 'pyautogui',
    'PyQt5', 'webview', 'flask', 'werkzeug'
]

for package in packages_to_fix:
    try:
        mis_datas += copy_metadata(package)
        print(f"   ✓ Metadatos de {package}")
    except Exception as e:
        print(f"   ⚠️  Sin metadatos de {package}: {e}")

# =============================================================================
# 3. ARCHIVOS FÍSICOS (SÓLO SI EXISTEN)
# =============================================================================
added_files = []

# Archivos básicos que deben existir
basic_files = [
    ('chime.wav', '.'),
    ('web', 'web'),
    ('archeon_files.db', '.'),
]

for file_tuple in basic_files:
    file_path, dest = file_tuple
    if os.path.exists(file_path):
        added_files.append((file_path, dest))
        print(f"📄 Añadido: {file_path} → {dest}")
    else:
        print(f"⚠️  No existe: {file_path}")

# FFMpeg - busca en diferentes ubicaciones posibles
ffmpeg_locations = [
    'ffmpeg.exe',
    'ffmpeg-8.0.1-essentials_build/bin/ffmpeg.exe',
    'ffmpeg/bin/ffmpeg.exe',
    'ffmpeg',
]

for ffmpeg_loc in ffmpeg_locations:
    if os.path.exists(ffmpeg_loc):
        added_files.append((ffmpeg_loc, '.'))
        print(f"🎵 FFMpeg encontrado: {ffmpeg_loc}")
        break
else:
    print("⚠️  FFMpeg no encontrado, se usará del PATH")

# PyArmor runtime - SÓLO si existe
pyarmor_dir = 'pyarmor_runtime_000000'
if os.path.exists(pyarmor_dir):
    print(f"🔐 Carpeta PyArmor encontrada: {pyarmor_dir}")
    # Añadir recursivamente toda la carpeta
    for root, dirs, files in os.walk(pyarmor_dir):
        for file in files:
            file_path = os.path.join(root, file)
            rel_dir = os.path.relpath(root, pyarmor_dir)
            if rel_dir == '.':
                added_files.append((file_path, pyarmor_dir))
            else:
                added_files.append((file_path, os.path.join(pyarmor_dir, rel_dir)))
    print(f"   ✓ Añadida carpeta PyArmor completa")
else:
    print("⚠️  NO se encontró pyarmor_runtime_000000")
    print("   Si usas PyArmor, primero debes encriptar los archivos")
    print("   Si NO usas PyArmor, quita 'pyarmor_runtime_000000' de hiddenimports")

mis_datas += added_files

# =============================================================================
# 4. ELIMINAR DUPLICADOS
# =============================================================================
def remove_duplicates(items):
    seen = set()
    unique = []
    for item in items:
        if isinstance(item, tuple):
            if item not in seen:
                seen.add(item)
                unique.append(item)
        else:
            if item not in seen:
                seen.add(item)
                unique.append(item)
    return unique

mis_datas = remove_duplicates(mis_datas)
mis_binaries = remove_duplicates(mis_binaries)
mis_hiddenimports = remove_duplicates(mis_hiddenimports)

print(f"\n📊 RESUMEN DE RECOLECCIÓN:")
print(f"   • Datas: {len(mis_datas)} archivos")
print(f"   • Binaries: {len(mis_binaries)} binarios")
print(f"   • Hidden Imports: {len(mis_hiddenimports)} módulos\n")

# =============================================================================
# 5. CONFIGURACIÓN DEL EXE
# =============================================================================
a = Analysis(
    ['Archeo32n.py'],
    pathex=[os.getcwd()],  # Sólo la ruta actual
    binaries=mis_binaries,
    datas=mis_datas,
    hiddenimports=mis_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'test', 'unittest', 'pydoc', 'pdb',  # Excluir módulos no necesarios
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Archeo32n',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],  # Puedes excluir DLLs críticas si upx causa problemas
    runtime_tmpdir=None,
    console=False,  # Cambia a True para ver errores durante desarrollo
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='web/logo_asitente.ico' if os.path.exists('web/logo_asitente.ico') else None,
)

print("✅ Configuración .spec completada.")
print("\n💡 INSTRUCCIONES:")
print("1. Si usas PyArmor, primero encripta tus archivos")
print("2. Si NO usas PyArmor, edita el archivo .spec y:")
print("   - Comenta la línea: 'pyarmor_runtime_000000',")
print("   - Comenta todo el bloque de PyArmor en la sección 3")
print("\n3. Ejecuta:")
print("   pyinstaller build_archeo.spec --clean --noconfirm")