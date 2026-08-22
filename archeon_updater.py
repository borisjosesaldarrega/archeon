import requests
import os
import sys
import subprocess
import threading
import tempfile
import tkinter as tk
from tkinter import messagebox

# CONFIGURACIÓN
INTERNAL_VERSION = 9.6  
VERSION_URL = "https://archeon.netlify.app/version.json"

def check_for_updates():
    """Busca actualizaciones silenciosamente."""
    try:
        response = requests.get(VERSION_URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            cloud_version = float(data.get("version", 0.0))
            exe_url = data.get("exe_url", "")
            msg = data.get("message", "Mejoras generales.")

            if cloud_version > INTERNAL_VERSION:
                # Si hay update, preguntamos al usuario si quiere reiniciar
                ask_for_restart(cloud_version, msg, exe_url)
    except Exception as e:
        print(f"Error update: {e}")

def ask_for_restart(new_ver, msg, url):
    """Muestra la notificación estilo Opera GX."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    # El mensaje ahora es diferente: "Ya está lista, ¿reiniciamos?"
    choice = messagebox.askyesno(
        "Archeon AI Actualizado",
        f"Se ha detectado la versión {new_ver}.\n\n"
        f"Novedades: {msg}\n\n"
        "Para aplicar los cambios, Archeon necesita reiniciarse.\n"
        "¿Reiniciar ahora?"
    )
    root.destroy()

    if choice:
        perform_silent_update(url)

def perform_silent_update(url):
    """Descarga y ejecuta el instalador en MODO FANTASMA."""
    try:
        # 1. Ruta temporal
        temp_dir = tempfile.gettempdir()
        installer_name = "Archeon_Setup_Silent.exe"
        installer_path = os.path.join(temp_dir, installer_name)
        
        # 2. Descargar (podrías poner una barra de progreso aquí si quisieras, pero lo haremos invisible)
        print("⬇️ Descargando actualización en segundo plano...")
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(installer_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        print("✅ Descarga lista. Iniciando modo fantasma...")

        # 3. COMANDOS SECRETOS DE INNO SETUP
        # /VERYSILENT -> No muestra ninguna ventana
        # /SUPPRESSMSGBOXES -> No muestra alertas
        # /CLOSEAPPLICATIONS -> Intenta cerrar Archeon si estorba (aunque lo cerraremos nosotros)
        # /RESTARTAPPLICATIONS -> Vuelve a abrir la app al terminar
        
        cmd = [
            installer_path,
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/CLOSEAPPLICATIONS", 
            "/RESTARTAPPLICATIONS" 
        ]

        # Lanzamos el instalador independiente
        subprocess.Popen(cmd, shell=True)
        
        # 4. SUICIDIO DEL PROCESO ACTUAL
        # Cerramos Archeon inmediatamente para dejar que el instalador sobrescriba
        sys.exit(0)

    except Exception as e:
        messagebox.showerror("Error", f"No se pudo actualizar: {e}")

def start_updater_thread():
    threading.Thread(target=check_for_updates, daemon=True).start()