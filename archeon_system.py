# =======================================================================
# ARCHIVO: archeon_system.py v3.0 (JARVIS EDITION)
# Control Total: Ventanas, Archivos, Privacidad, Hardware y Navegación
# =======================================================================
import os
import shutil
import sqlite3
import psutil 
import subprocess
import threading
import ctypes
import time
import webbrowser
import urllib.parse
from datetime import datetime
from difflib import get_close_matches

# Intentamos importar librerías de control y red
try:
    import pyautogui
    import requests
    EXTRAS_AVAILABLE = True
except ImportError:
    EXTRAS_AVAILABLE = False
    print("!! [SISTEMA] Faltan 'pyautogui' o 'requests'. Funciones limitadas.")

# Rutas clave
USER_PATH = os.path.expanduser("~")
DOCS_PATH = os.path.join(USER_PATH, "Documents")
DOWNLOADS_PATH = os.path.join(USER_PATH, "Downloads")
DESKTOP_PATH = os.path.join(USER_PATH, "Desktop")
TEMP_PATH = os.path.join(os.environ.get('TEMP', 'C:\\Windows\\Temp'))
DB_FILES = "archeon_files.db"

class SystemCore:
    def __init__(self):
        self._init_db()
        # Diccionario de alias para programas comunes
        self.apps_conocidas = {
            "chrome": "chrome.exe", "google": "chrome.exe", "navegador": "chrome.exe",
            "brave": "brave.exe", "edge": "msedge.exe",
            "notepad": "notepad.exe", "notas": "notepad.exe", "bloc de notas": "notepad.exe",
            "calculadora": "calc.exe",
            "spotify": "spotify.exe",
            "discord": "discord.exe",
            "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe",
            "cmd": "cmd.exe", "terminal": "wt.exe",
            "archivos": "explorer.exe", "carpetas": "explorer.exe",
            "steam": "steam.exe", "epic": "EpicGamesLauncher.exe"
        }
        # Iniciar indexación silenciosa al arrancar
        self.indexar_background()

    def _init_db(self):
        conn = sqlite3.connect(DB_FILES)
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS file_index 
                       (name TEXT, path TEXT, type TEXT, last_seen DATETIME)''')
        conn.commit(); conn.close()

    # =========================================================
    # 1. CONTROL DE VENTANAS Y ESCRITORIO (UI CONTROL)
    # =========================================================
    
    def minimizar_todo(self):
        """Modo Pánico / Escritorio Limpio."""
        if EXTRAS_AVAILABLE:
            pyautogui.hotkey('win', 'd')
            return "Escritorio despejado."
        return "Error: Falta librería pyautogui."

    def cerrar_ventana_activa(self):
        """Cierra lo que sea que estés viendo (Alt+F4)."""
        if EXTRAS_AVAILABLE:
            pyautogui.hotkey('alt', 'f4')
            return "Ventana cerrada."
        return "Error: Falta librería pyautogui."

    def cambiar_ventana(self):
        """Alterna a la siguiente ventana (Alt+Tab)."""
        if EXTRAS_AVAILABLE:
            pyautogui.hotkey('alt', 'tab')
            return "Cambiando ventana..."
        return "Error: Falta librería pyautogui."
    
    def escribir_texto(self, texto):
        """Escribe texto automáticamente donde esté el cursor."""
        if EXTRAS_AVAILABLE:
            pyautogui.write(texto, interval=0.05)
            return "Texto escrito."
        return "Error: Falta librería pyautogui."

    def tomar_captura(self):
        """Toma una captura de pantalla y la guarda en el escritorio."""
        if EXTRAS_AVAILABLE:
            nombre = f"Captura_{int(time.time())}.png"
            ruta = os.path.join(DESKTOP_PATH, nombre)
            pyautogui.screenshot(ruta)
            return f"Captura guardada en el escritorio: {nombre}"
        return "No puedo ver la pantalla."

    # =========================================================
    # 2. SEGURIDAD Y PRIVACIDAD (LIMPIEZA)
    # =========================================================

    def vaciar_papelera(self):
        """Vacía la papelera de reciclaje de Windows."""
        try:
            # SHEmptyRecycleBinW flags: 1=NoSound, 2=NoConfirmation, 4=NoProgressUI
            SHEmptyRecycleBin = ctypes.windll.shell32.SHEmptyRecycleBinW
            SHEmptyRecycleBin(None, None, 7) 
            return "Papelera de reciclaje purgada."
        except Exception as e:
            return f"No pude vaciar la papelera: {e}"

    def limpiar_temporales(self):
        """Elimina archivos basura de la carpeta TEMP de Windows."""
        eliminados = 0
        errores = 0
        for root, dirs, files in os.walk(TEMP_PATH):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                    eliminados += 1
                except: errores += 1
        return f"Limpieza de sistema completada. {eliminados} archivos eliminados."

    def purgar_portapapeles(self):
        """Borra el contenido del portapapeles por seguridad."""
        try:
            os.system('echo off | clip')
            return "Portapapeles purgado. Datos sensibles eliminados."
        except:
            return "Error al limpiar portapapeles."

    def obtener_ip_publica(self):
        """Verifica tu IP real (útil para VPNs)."""
        if EXTRAS_AVAILABLE:
            try:
                ip = requests.get('https://api.ipify.org', timeout=3).text
                return f"Tu dirección IP pública es: {ip}"
            except: return "Sin conexión a internet."
        return "Librería requests no instalada."

    # =========================================================
    # 3. MULTIMEDIA VISUAL (YOUTUBE / NAVEGADOR)
    # =========================================================
    
    def poner_video_web(self, busqueda):
        """
        Abre el navegador y busca el video.
        Diferente a 'reproducir música' que es solo audio de fondo.
        """
        busqueda = busqueda.replace("pon", "").replace("video", "").replace("el", "").replace("de", "").strip()
        
        if not busqueda: return "¿Qué video quieres que ponga?"
        
        # Codificar búsqueda para URL
        query_encoded = urllib.parse.quote(busqueda)
        url = f"https://www.youtube.com/results?search_query={query_encoded}"
        
        # Abrir en navegador predeterminado
        webbrowser.open(url)
        
        # Opcional: Si tienes pyautogui, intentar dar click al primer video
        if EXTRAS_AVAILABLE:
            # Esperar a que cargue la página
            # (Esto es experimental, a veces es mejor solo abrir la búsqueda)
            pass 
            
        return f"Buscando '{busqueda}' en YouTube."

    # =========================================================
    # 4. GESTIÓN DE ARCHIVOS Y APPS
    # =========================================================
    
    def abrir_programa(self, nombre_app):
        nombre_app = nombre_app.lower().strip()
        ejecutable = self.apps_conocidas.get(nombre_app, nombre_app)
        try:
            subprocess.Popen(ejecutable, shell=True)
            return f"Abriendo {nombre_app}..."
        except:
            # Fallback a búsqueda de archivos
            ruta = self.buscar_archivo(nombre_app + ".exe") or self.buscar_archivo(nombre_app + ".lnk")
            if ruta:
                os.startfile(ruta)
                return f"Encontré y ejecuté {nombre_app}."
            return f"No encuentro la aplicación '{nombre_app}'."

    def cerrar_programa(self, nombre_proceso):
        nombre_proceso = nombre_proceso.lower().replace(" ", "")
        matados = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if nombre_proceso in proc.info['name'].lower():
                    proc.kill()
                    matados += 1
            except: pass
        if matados > 0: return f"Proceso {nombre_proceso} terminado ({matados} instancias)."
        return f"No encontré {nombre_proceso} en ejecución."

    def indexar_background(self):
        t = threading.Thread(target=self.escanear_disco)
        t.start()

    def escanear_disco(self):
        conn = sqlite3.connect(DB_FILES)
        cur = conn.cursor()
        cur.execute("DELETE FROM file_index") 
        ext_interes = ('.pdf', '.docx', '.txt', '.pptx', '.xlsx', '.png', '.jpg', '.mp4', '.mkv', '.exe', '.lnk')
        
        # Directorios comunes
        rutas = [DOCS_PATH, DOWNLOADS_PATH, DESKTOP_PATH]
        
        for ruta_base in rutas:
            if os.path.exists(ruta_base):
                for root, dirs, files in os.walk(ruta_base):
                    for file in files:
                        if file.lower().endswith(ext_interes):
                            path_full = os.path.join(root, file)
                            try:
                                cur.execute("INSERT INTO file_index VALUES (?, ?, ?, ?)", 
                                            (file.lower(), path_full, file.split('.')[-1], datetime.now()))
                            except: pass
        conn.commit(); conn.close()

    def buscar_archivo(self, nombre_aprox):
        try:
            conn = sqlite3.connect(DB_FILES)
            cur = conn.cursor()
            cur.execute("SELECT name, path FROM file_index")
            datos = cur.fetchall()
            conn.close()
            nombres = [n for n, _ in datos]
            match = get_close_matches(nombre_aprox.lower(), nombres, n=1, cutoff=0.4)
            if match:
                mejor = match[0]
                for n, p in datos:
                    if n == mejor: return p
            return None
        except: return None

    def organizar_descargas(self):
        mapa = {
            "Imágenes": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
            "Documentos": [".pdf", ".docx", ".txt", ".xlsx"],
            "Instaladores": [".exe", ".msi"],
            "Comprimidos": [".zip", ".rar", ".7z"],
            "Videos": [".mp4", ".mkv", ".avi"]
        }
        movidos = 0
        for archivo in os.listdir(DOWNLOADS_PATH):
            ruta_origen = os.path.join(DOWNLOADS_PATH, archivo)
            if os.path.isfile(ruta_origen):
                ext = os.path.splitext(archivo)[1].lower()
                for carpeta, extensiones in mapa.items():
                    if ext in extensiones:
                        ruta_destino = os.path.join(DOWNLOADS_PATH, carpeta)
                        if not os.path.exists(ruta_destino): os.makedirs(ruta_destino)
                        try:
                            shutil.move(ruta_origen, os.path.join(ruta_destino, archivo))
                            movidos += 1
                        except: pass
                        break
        return f"Archivos organizados: {movidos}."

    def obtener_estado_pc(self):
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        try:
            bat = psutil.sensors_battery()
            bat_info = f", Batería: {bat.percent}%" if bat else ""
        except: bat_info = ""
        return f"CPU: {cpu}%, RAM: {ram}%{bat_info}"

    # =========================================================
    # 5. ROUTER DE COMANDOS (CEREBRO DE SISTEMA)
    # =========================================================
    def ejecutar_accion_sistema(self, accion):
        """
        Interpreta comandos complejos enviados por NeuroCore.
        """
        a = accion.lower()
        
        # --- VIDEO / WEB (Lo nuevo) ---
        if any(x in a for x in ["video", "pelicula", "youtube", "trailer"]):
            return self.poner_video_web(a)

        # --- VENTANAS ---
        if "minimiza" in a or "escritorio" in a: return self.minimizar_todo()
        if "cierra" in a and "ventana" in a: return self.cerrar_ventana_activa()
        if "cambia" in a and "ventana" in a: return self.cambiar_ventana()
        if "captura" in a or "foto" in a: return self.tomar_captura()
        
        # --- SEGURIDAD / PRIVACIDAD ---
        if "papelera" in a: return self.vaciar_papelera()
        if "temporal" in a or "limpia" in a: return self.limpiar_temporales()
        if "portapapeles" in a: return self.purgar_portapapeles()
        if "ip" in a: return self.obtener_ip_publica()
        
        # --- UTILIDADES ---
        if "nota" in a and "escribe" in a:
            return self.crear_nota_escritorio(a.split("escribe")[-1].strip())

        # --- APPS Y HARDWARE ---
        if "organiza" in a: return self.organizar_descargas()
        if "estado" in a or "rendimiento" in a: return self.obtener_estado_pc()
        
        if "abre" in a: return self.abrir_programa(a.replace("abre", "").strip())
        if "cierra" in a: return self.cerrar_programa(a.replace("cierra", "").strip())
        
        # --- ENERGÍA ---
        if "apagar" in a: return os.system("shutdown /s /t 5")
        if "reiniciar" in a: return os.system("shutdown /r /t 5")
        if "suspender" in a: return os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        if "bloquear" in a: return ctypes.windll.user32.LockWorkStation()

        return "Comando de sistema no reconocido."
    
    def obtener_apps_instaladas(self):
        """
        Escanea automáticamente los accesos directos del Menú Inicio y Escritorio.
        Devuelve una lista limpia para el frontend.
        """
        apps_encontradas = []
        nombres_vistos = set()

        # Rutas clave donde Windows guarda los accesos directos
        rutas_scan = [
            os.path.join(os.environ["ProgramData"], "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.environ["PUBLIC"], "Desktop")
        ]

        for ruta_base in rutas_scan:
            if not os.path.exists(ruta_base): continue
            
            for root, dirs, files in os.walk(ruta_base):
                for file in files:
                    if file.lower().endswith(".lnk"):
                        nombre_limpio = os.path.splitext(file)[0]
                        
                        # Filtros de limpieza (evitar desinstaladores o ayudas)
                        if "uninstall" in nombre_limpio.lower() or "ayuda" in nombre_limpio.lower():
                            continue
                            
                        if nombre_limpio not in nombres_vistos:
                            ruta_completa = os.path.join(root, file)
                            apps_encontradas.append({
                                "nombre": nombre_limpio,
                                "ruta": ruta_completa,
                                "tipo": "app"
                            })
                            nombres_vistos.add(nombre_limpio)
        
        # Ordenar alfabéticamente
        return sorted(apps_encontradas, key=lambda x: x['nombre'])