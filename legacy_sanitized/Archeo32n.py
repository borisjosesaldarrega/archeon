# =======================================================================
# ARCHIVO: Archeo32n.py v.8.1 (BLINDADO - MODO .EXE COMPATIBLE)
# =======================================================================
import os
import sys
import locale
import archeon_updater


# --- FIX SSL PARA FIREBASE EN EXE ---
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
os.environ['GRPC_DEFAULT_SSL_ROOTS_FILE_PATH'] = certifi.where()

# ========================================================================
# DETECCIÓN DE MODO .EXE Y CONFIGURACIÓN DE RUTAS (CRÍTICO)
# ========================================================================
def is_exe():
    """Determina si estamos ejecutando desde un .exe de PyInstaller"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

def get_base_path():
    """Obtiene la ruta base correcta según el modo"""
    if is_exe():
        # Modo .exe: los recursos están en _MEIPASS
        return sys._MEIPASS
    else:
        # Modo desarrollo: usar directorio actual
        return os.path.dirname(os.path.abspath(__file__))

def get_working_path():
    """Obtiene el directorio de trabajo donde se guardan los datos"""
    if is_exe():
        # En .exe: usar directorio donde está el ejecutable
        return os.path.dirname(sys.executable)
    else:
        # En desarrollo: usar directorio actual
        return os.path.dirname(os.path.abspath(__file__))

# Configurar rutas
BASE_PATH = get_base_path()
WORKING_PATH = get_working_path()
EXE_MODE = is_exe()

print("=" * 60)
print(f">> [SISTEMA] Modo: {'EXE' if EXE_MODE else 'DESARROLLO'}")
print(f">> [SISTEMA] Base path: {BASE_PATH}")
print(f">> [SISTEMA] Working path: {WORKING_PATH}")
print("=" * 60)

# Cambiar al directorio de trabajo para archivos de datos
os.chdir(WORKING_PATH)

def resource_path(relative_path):
    """Obtiene la ruta absoluta al recurso (compatible con PyInstaller)."""
    # Primero buscar en el directorio de trabajo (para archivos creados)
    working_path = os.path.join(WORKING_PATH, relative_path)
    if os.path.exists(working_path):
        return working_path
    
    # Luego buscar en recursos empaquetados
    return os.path.join(BASE_PATH, relative_path)

# --- 1. CONFIGURACIÓN DE SEGURIDAD (INCRUSTADA) ---
# Al definir esto ANTES de las importaciones, aseguramos que
# todos los módulos (Neuro, OpenRouter) encuentren las llaves.

# A) LLAVES DE API (Reemplazan al archivo .env)
os.environ["GOOGLE_API_KEY"] = "REDACTED_GOOGLE_API_KEY"
os.environ["OPENROUTER_API_KEY"] = "REDACTED_OPENROUTER_API_KEY"

# B) CREDENCIALES FIREBASE (Reemplazan al archivo firebase_key.json)
FIREBASE_KEY_DICT = None  # Credential removed from recovery checkpoint.

import smtplib
import ssl
from email.message import EmailMessage
import subprocess
import json
import threading
import time
import secrets
import queue
import logging
import random
import re
import io
from datetime import datetime

# Rutas críticas configuradas con la nueva función
WEB_DIR = resource_path('web')
AUDIO_PATH = resource_path('chime.wav')

# Rutas de archivos de datos en el directorio de trabajo
DB_FILES = os.path.join(WORKING_PATH, 'archeon_files.db')
HISTORIAL_PATH = os.path.join(WORKING_PATH, 'memoria_predicciones.json')
BACKUP_PATH = os.path.join(WORKING_PATH, 'memoria_predicciones.bak')
CONFIG_GUEST_PATH = os.path.join(WORKING_PATH, 'guest_config.json')

print(f">> [RUTAS] WEB_DIR: {WEB_DIR}")
print(f">> [RUTAS] DB_FILES: {DB_FILES}")
print(f">> [RUTAS] HISTORIAL_PATH: {HISTORIAL_PATH}")
print(f">> [RUTAS] ¿WEB_DIR existe? {os.path.exists(WEB_DIR)}")

# Crear archivos de datos si no existen
if not os.path.exists(DB_FILES):
    print(">> [SISTEMA] Creando archivo de base de datos...")
    try:
        import sqlite3
        conn = sqlite3.connect(DB_FILES)
        conn.close()
    except:
        pass

if not os.path.exists(HISTORIAL_PATH):
    print(">> [SISTEMA] Creando archivo de memoria predictiva...")
    try:
        with open(HISTORIAL_PATH, 'w') as f:
            json.dump({"transiciones": {}, "contexto_hora": {}, "contexto_hardware": {}, 
                      "ultima_accion": None, "contador_acciones": 0}, f)
    except:
        pass

# --- CONFIGURACIÓN WEBVIEW ---
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--autoplay-policy=no-user-gesture-required "
    "--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies "
    "--disable-site-isolation-trials"
)

# Corrección de codificación consola
class DevNull:
    """Un agujero negro para los print() cuando no hay consola"""
    def write(self, msg): pass
    def flush(self): pass

# Si estamos en modo .EXE y no hay consola, redirigir prints a la nada
if sys.platform == "win32" and getattr(sys, 'frozen', False):
    # Si sys.stdout es None (pasó console=False), le ponemos el silenciador
    if sys.stdout is None:
        sys.stdout = DevNull()
    if sys.stderr is None:
        sys.stderr = DevNull()

print("--- INICIANDO SISTEMA ARCHEON (CORE: BLINDADO) ---")

# --- IMPORTACIONES ---
try:
    import speech_recognition as sr
    import pyttsx3
    import google.generativeai as genai
    from flask import Flask, request, jsonify, send_from_directory
    import webview
    import winsound
    import webbrowser
    import pythoncom 
    import pyautogui
except ImportError as e:
    print(f"!!! FALTA LIBRERÍA: {e}")
    sys.exit(1)

# Configurar Google GenAI con la llave ya cargada en memoria
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# --- CARGA DE MÓDULOS ---
try: 
    from archeon_cloud import CloudManager
    print(">> [SISTEMA] CloudManager cargado.")
except ImportError: 
    print("!!! ERROR CRÍTICO: Falta 'archeon_cloud.py'")
    sys.exit(1)

try: 
    from archeon_music import MusicManager
    print(">> [SISTEMA] MusicManager cargado.")
except ImportError as e:
    print(f"!!! Error cargando MusicManager: {e}")
    MusicManager = None

try: 
    from archeon_social import SocialCore
    print(">> [SISTEMA] SocialCore cargado.")
except ImportError:
    print(">> [SISTEMA] SocialCore NO disponible.")
    SocialCore = None

try: 
    from archeon_neuro import NeuroCore
    print(">> [SISTEMA] NeuroCore cargado correctamente.")
except Exception as e:
    print(">> [SISTEMA] NeuroCore NO disponible:", e)
    NeuroCore = None

try:
    from sistema_predicciones import iniciar_hilo_predicciones
    # Actualizar las rutas en el módulo de predicciones
    import sistema_predicciones
    sistema_predicciones.HISTORIAL_PATH = HISTORIAL_PATH
    sistema_predicciones.BACKUP_PATH = BACKUP_PATH
    PREDICCIONES_ACTIVAS = True
    print(">> [SISTEMA] Predicciones activadas.")
except ImportError:
    PREDICCIONES_ACTIVAS = False
    print(">> [SISTEMA] Predicciones desactivadas.")


# =========================================================
# CÁPSULA DE VOZ
# =========================================================
class CapsulaVoz:
    def __init__(self, callback_control_audio):
        self.cola = queue.Queue()
        self.activo = True
        self.control_audio = callback_control_audio 
        self.lista_voces_disponibles = [] 
        self.voz_actual_id = None
        self.ultimo_texto = ""
        self.tiempo_ultimo = 0
        self.hilo = threading.Thread(target=self._bucle_habla, daemon=True)
        self.hilo.start()

    def decir(self, texto):
        txt_clean = str(texto).strip()
        if not txt_clean: return
        self.cola.put(txt_clean)

    def actualizar_voz(self, voz_id):
        self.voz_actual_id = voz_id

    def _bucle_habla(self):
        try:
            pythoncom.CoInitialize()
            engine_temp = pyttsx3.init()
            voces = engine_temp.getProperty('voices')
            self.lista_voces_disponibles = [{'id': v.id, 'name': v.name} for v in voces]
            del engine_temp 
        except: pass

        while self.activo:
            try:
                texto = self.cola.get()
                if texto is None: break
                
                ahora = time.time()
                txt_comp = texto.lower().strip()
                last_comp = self.ultimo_texto.lower().strip()
                
                if (txt_comp == last_comp or txt_comp in last_comp) and (ahora - self.tiempo_ultimo) < 5.0:
                    self.cola.task_done()
                    continue
                
                self.ultimo_texto = texto
                self.tiempo_ultimo = ahora
                print(f">> Archeon (Voz): {texto}")
                
                if self.control_audio: self.control_audio(True)
                time.sleep(0.2) 
                
                try:
                    engine = pyttsx3.init()
                    if self.voz_actual_id:
                        try: engine.setProperty('voice', self.voz_actual_id)
                        except: pass
                    engine.setProperty('rate', 160)
                    engine.setProperty('volume', 1.0)
                    engine.say(texto)
                    engine.runAndWait()
                    del engine
                except Exception as e: 
                    print(f"!! Error voz: {e}")

                if self.control_audio: self.control_audio(False)
                self.cola.task_done()
            except Exception: 
                pass

# =========================================================
# SERVIDOR WEB (FLASK)
# =========================================================
class _ServidorWeb:
    def __init__(self, asistente):
        self.asistente = asistente
        # Configurar Flask con la ruta correcta
        static_folder = WEB_DIR
        print(f">> [FLASK] Configurando static_folder: {static_folder}")
        self.app = Flask(__name__, static_folder=static_folder)
        self._rutas()

    def _rutas(self):
        @self.app.get('/')
        @self.app.get('/login')
        def view_login(): 
            print(f">> [FLASK] Sirviendo login.html desde: {WEB_DIR}")
            return send_from_directory(WEB_DIR, 'login.html')
        
        @self.app.get('/dashboard')
        def view_dashboard(): 
            return send_from_directory(WEB_DIR, 'dashboard.html')
        
        @self.app.route('/<path:filename>')
        def serve_static(filename): 
            return send_from_directory(WEB_DIR, filename)
        
        @self.app.get('/api/status')
        def api_status():
            musica_activa = False
            thumb = None
            title = "Inactivo"
            paused = False
            if self.asistente.music_manager:
                musica_activa = self.asistente.music_manager.stream_out is not None
                thumb = self.asistente.music_manager.current_thumbnail
                title = self.asistente.music_manager.current_title
                paused = self.asistente.music_manager.is_paused

            return jsonify({
                'escuchando': self.asistente.escuchando,
                'nombre': self.asistente.config.get('nombre', 'Archeon'),
                'tema': self.asistente.config.get('tema', 'dark'),
                'user_name': self.asistente.config.get('user_name', ''),
                'voces': self.asistente.voz.lista_voces_disponibles, 
                'musica_activa': musica_activa,
                'thumbnail': thumb,
                'song_title': title,
                'is_paused': paused,
                'exe_mode': EXE_MODE,
                # AGREGAR ESTOS DOS:
                'mic_threshold': self.asistente.config.get('mic_threshold', 4000),
                'mic_timeout': self.asistente.config.get('mic_timeout', 5)
            })

    
        @self.app.post('/api/music/stop')
        def api_stop():
            if self.asistente.music_manager: 
                self.asistente.music_manager.stop_audio()
            return jsonify({'ok': True})
        
        @self.app.post('/api/music/pause')
        def api_pause():
            paused = False
            if self.asistente.music_manager: 
                paused = self.asistente.music_manager.toggle_pause()
            return jsonify({'ok': True, 'paused': paused})
        
        @self.app.post('/api/volume')
        def api_volume():
            data = request.get_json(force=True)
            if self.asistente.music_manager: 
                self.asistente.music_manager.set_music_volume(int(data.get('level', 50)))
            return jsonify({'ok': True})
        
        @self.app.post('/api/send-code')
        def api_send_code():
            from email.mime.image import MIMEImage
            import secrets # Más seguro que random para criptografía
            
            data = request.get_json(force=True)
            destinatario = data.get('email', '').lower().strip()
            mode = data.get('mode', 'register')
            
            # Generar código criptográficamente seguro de 6 dígitos
            codigo = str(secrets.randbelow(900000) + 100000)

            # CONFIGURACIÓN DE CORREO (Oculta/Variable de entorno)
            # Nota: Idealmente estas variables deberían estar en os.environ al inicio del script
            SENDER_EMAIL = os.environ.get("EMAIL_USER", "archeondzknightcompanny@gmail.com")
            # IMPORTANTE: Si usas .exe, asegura que esta variable esté definida o usa tu string hardcoded 
            # SOLO si has ofuscado el código con PyArmor. Si no, es visible.
            SENDER_PASSWORD = os.environ.get("EMAIL_PASS", "spao xbbk jtfl wfzk") 
            
            REMITENTE_FINAL = "EQUIPO DZKNIGHTCOMPANNY"
            UBICACION = "Guayaquil, Ecuador"
            CURRENT_YEAR = datetime.now().year
            LOGO_PATH = os.path.join(WEB_DIR, 'logo_asitente.png')
            LOGO_CID = 'logo_archeon_cid'

            if not destinatario:
                return jsonify({'ok': False, 'error': 'Falta email'}), 400

            # 1. GUARDAR CÓDIGO EN LA NUBE (CRÍTICO)
            if self.asistente.cloud:
                self.asistente.cloud.guardar_codigo_verificacion(destinatario, codigo)
            else:
                return jsonify({'ok': False, 'error': 'Sistema de nube no disponible'}), 500

            # 2. PREPARAR CORREO
            if mode == 'recover':
                asunto = "Restablecimiento de Clave de Acceso - Archeon AI"
                titulo = "Restablecimiento de Contraseña"
                parrafo_principal = "Hemos recibido una solicitud para **restablecer la contraseña**. Utiliza el siguiente código para crear una nueva clave."
                parrafo_secundario = "Este código expirará en 15 minutos. Si no solicitaste este cambio, ignora este correo."
            else:
                asunto = "Confirmación de Registro - Bienvenido a Archeon AI"
                titulo = "Confirmación de Registro"
                parrafo_principal = "¡Bienvenido al Sistema Archeon AI! Utiliza el siguiente código para **verificar tu identidad**."
                parrafo_secundario = "Introduce este código en la aplicación para completar la creación de tu cuenta."
            
            cuerpo_html = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: 'Segoe UI', sans-serif; background-color: #09090b; margin: 0; padding: 0; }}
                    .container {{ max-width: 600px; margin: 20px auto; background-color: #1a1a1f; border-radius: 10px; overflow: hidden; }}
                    .header {{ background-color: #00f3ff; padding: 20px 30px; text-align: center; }}
                    .header h2 {{ color: #000; margin: 0; font-weight: 700; }}
                    .content {{ padding: 30px; color: #ececec; }}
                    .logo {{ max-width: 60px; height: auto; margin-bottom: 10px; }}
                    .code-box {{ background-color: #33333d; color: #ff2a6d; font-size: 28px; letter-spacing: 6px; text-align: center; padding: 15px; border-radius: 8px; margin: 25px 0; font-weight: bold; }}
                    .footer {{ background-color: #111115; color: #a1a1aa; padding: 20px 30px; font-size: 10px; text-align: center; border-top: 1px solid rgba(255, 255, 255, 0.08); }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content" style="text-align:center;">
                        <img class="logo" src="cid:{LOGO_CID}" alt="Archeon Logo">
                        <h2 style="color:#00f3ff; margin-top:0;">{titulo}</h2>
                    </div>
                    <div class="content">
                        <p style="font-size: 15px; line-height: 1.6;">{parrafo_principal}</p>
                        <p style="font-size: 15px; text-align: center; margin-top: 30px;">Su código de verificación:</p>
                        <div class="code-box">{codigo}</div>
                        <p style="font-size: 14px; color: #ccc;">{parrafo_secundario}</p>
                        <p style="font-size: 14px; margin-top: 30px;">Atentamente,<br><span style="color: #00f3ff; font-weight: bold;">{REMITENTE_FINAL}</span></p>
                    </div>
                    <div class="footer">
                        <p style="margin-bottom: 5px;">{REMITENTE_FINAL} &bull; {UBICACION}</p>
                        <p style="margin-top: 0;">&copy; {CURRENT_YEAR} {REMITENTE_FINAL}. Todos los derechos reservados.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            try:
                msg = EmailMessage()
                msg['Subject'] = asunto
                msg['From'] = SENDER_EMAIL
                msg['To'] = destinatario
                msg.set_content(f"Código Archeon AI: {codigo}") 
                msg.add_alternative(cuerpo_html, subtype='html')
                
                # Adjuntar logo si existe
                if os.path.exists(LOGO_PATH):
                    with open(LOGO_PATH, 'rb') as fp:
                        img = MIMEImage(fp.read())
                        img.add_header('Content-ID', f'<{LOGO_CID}>')
                        msg.attach(img)
                
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg)
                
                print(f">> [EMAIL] Código enviado ({mode}) a {destinatario}")
                # NO devolvemos el código al frontend por seguridad
                return jsonify({'ok': True}) 
            except Exception as e:
                print(f"!! Error enviando correo: {e}")
                return jsonify({'ok': False, 'error': "Error enviando correo. Verifique su dirección."}), 500

        @self.app.post('/api/verify-code')
        def api_verify_code():
            """Verifica el código contra la base de datos de Firebase."""
            try:
                data = request.get_json(force=True)
                # Normalización (igual que en el envío)
                email = data.get('email', '').lower().strip()
                user_code = str(data.get('code', '')).strip()
                
                print(f">> [API VERIFY] Verificando: {email} - Código: {user_code}")
                
                if not email:
                    return jsonify({'ok': False, 'error': 'Email faltante'}), 400
                
                if not self.asistente.cloud:
                    return jsonify({'ok': False, 'error': 'Modo offline'}), 500

                # Llamada a CloudManager (Que ya sabemos que funciona por tus logs)
                resultado = self.asistente.cloud.validar_codigo_verificacion(email, user_code)
                
                if resultado["ok"]:
                    print(f">> [API] ✅ Código aceptado. Enviando éxito al frontend.")
                    
                    # 🔥 ESTA ES LA CLAVE QUE TE FALTABA 🔥
                    # Tu interfaz gráfica busca 'verified' o 'success', no solo 'ok'.
                    return jsonify({
                        'ok': True, 
                        'verified': True,   # <-- IMPORTANTE
                        'success': True,    # <-- IMPORTANTE
                        'message': 'Código verificado correctamente',
                        'redirect': '/dashboard' 
                    })
                else:
                    print(f">> [API] ❌ Rechazado por Cloud: {resultado['error']}")
                    return jsonify({'ok': False, 'error': resultado["error"]}), 400
                    
            except Exception as e:
                print(f"!! [API ERROR] {e}")
                return jsonify({'ok': False, 'error': str(e)}), 500
            
        @self.app.post('/api/reset-password')
        def api_reset_password():
            """Restablece la contraseña tras una verificación exitosa."""
            data = request.get_json(force=True)
            email = data.get('email')
            new_password = data.get('password')
            # Nota: Podrías pedir el código de nuevo aquí para doble seguridad, 
            # pero asumimos que el frontend solo llega aquí tras verificar.
            
            print(f">> [API RESET] Restableciendo para: {email}")
            
            if not email or not new_password:
                return jsonify({'ok': False, 'error': 'Datos incompletos'}), 400
            
            if self.asistente.cloud:
                # Usamos la función existente en cloud
                success = self.asistente.cloud.actualizar_password(email, new_password)
                if success:
                    return jsonify({'ok': True, 'message': 'Contraseña actualizada correctamente'})
                else:
                    return jsonify({'ok': False, 'error': 'Error actualizando en base de datos'}), 500
            
            return jsonify({'ok': False, 'error': 'Nube no disponible'}), 500

        @self.app.post('/api/register')
        def api_register():
            """Crea usuario con nombre personalizado y contraseña."""
            try:
                data = request.get_json(force=True)
                email = data.get('email', '').lower().strip()
                password = data.get('password')
                user_name = data.get('user_name', 'Usuario').strip()
                
                print(f">> [API REGISTER] Nuevo usuario: {email} | Nombre: {user_name}")
                
                if not email or not password:
                    return jsonify({'ok': False, 'error': 'Datos incompletos'}), 400
                
                resultado = self.asistente.crear_usuario(email, password, user_name)
                
                if resultado["ok"]:
                    return jsonify({'ok': True})
                else:
                    return jsonify({'ok': False, 'error': resultado["error"]}), 400
                    
            except Exception as e:
                print(f"!! [API ERROR] {e}")
                return jsonify({'ok': False, 'error': str(e)}), 500

        @self.app.post('/api/login')
        def api_login():
            """Valida credenciales y devuelve token."""
            try:
                data = request.get_json(force=True)
                email = data.get('email', '').lower().strip()
                password = data.get('password')
                
                print(f">> [API LOGIN] Acceso: {email}")
                
                if self.asistente.validar_login(email, password):
                    token = self.asistente.crear_sesion(email)
                    if token:
                        return jsonify({'ok': True, 'token': token})
                
                return jsonify({'ok': False, 'error': 'Credenciales inválidas'}), 401
            except Exception as e:
                return jsonify({'ok': False, 'error': str(e)}), 500

        @self.app.get('/api/me')
        def api_me():
            """Verifica si un token guardado sigue siendo válido."""
            token = request.headers.get('X-Auth-Token')
            if not token: return jsonify({'ok': False}), 401
            
            user = self.asistente.obtener_usuario_por_token(token)
            if user: 
                return jsonify({'ok': True, 'user': user})
            return jsonify({'ok': False}), 401

        @self.app.post('/api/guest')
        def api_guest(): 
            token = self.asistente.crear_sesion('guest') # Devuelve el token único 'guest_...'
            print(f">> [API GUEST] Token de invitado generado: {token[:20]}...")
            return jsonify({'ok': True, 'token': token})
        
        @self.app.put('/api/config')
        def api_config():
            token = request.headers.get('X-Auth-Token')
            user_email = self.asistente.obtener_usuario_por_token(token)
            if not user_email: 
                return jsonify({'ok': False}), 401
            data = request.get_json(force=True)
            self.asistente.actualizar_config(user_email, data)
            return jsonify({'ok':True})
        
        @self.app.post('/api/comandos')
        def api_cmds(): 
            return jsonify({'ok':True})
        
    def iniciar(self):
        print(">> Servidor Web iniciado en puerto 5000")
        # Configurar Flask para que acepte conexiones externas
        threading.Thread(
            target=lambda: self.app.run(
                port=5000, 
                use_reloader=False, 
                host='0.0.0.0',
                threaded=True
            ), 
            daemon=True
        ).start()

# =========================================================
# ASISTENTE VIRTUAL (BLINDADO - MODO .EXE COMPATIBLE)
# =========================================================
class AsistenteVirtual:
    def __init__(self):
        # --- CARGA SEGURA DE NUBE ---
        try:
            from archeon_cloud import CloudManager
            self.cloud = CloudManager(FIREBASE_KEY_DICT)
            print(">> [CLOUD] Conectado a Firebase.")
        except Exception as e:
            print(f"!!! Error CloudManager: {e}")
            self.cloud = None 
            
        self.escuchando = False
        
        # --- 🌍 DETECCIÓN AUTOMÁTICA DE IDIOMA DEL PC ---
        try:
            # Obtiene el idioma por defecto del sistema (ej: 'en_US', 'es_MX')
            # Requiere 'import locale' al inicio del archivo
            lang_code, _ = locale.getdefaultlocale()
            if lang_code:
                # Google Speech requiere formato con guión (es-MX), Windows da guión bajo (es_MX)
                self.idioma_sistema = lang_code.replace('_', '-')
            else:
                self.idioma_sistema = "es-ES" # Fallback por si falla
        except Exception as e:
            print(f">> [IDIOMA] Error detectando, usando español por defecto: {e}")
            self.idioma_sistema = "es-ES"
            
        print(f">> [IDIOMA] Configurado automáticamente a: {self.idioma_sistema}")

        # self.config se inicializará en cargar_config()
        self.config = {
            "nombre": "Archeon", 
            "tema": "dark", 
            "voz_id": "", 
            "user_name": "Invitado",
            "mic_threshold": 4000,  # Valor por defecto
            "mic_timeout": 5        # Valor por defecto
        }
        self.usuario = "guest"
        
        self.voz = CapsulaVoz(self.gestionar_interaccion) 

        # --- CARGA DE MÓDULOS ---
        if MusicManager: 
            self.music_manager = MusicManager(self)
            print(">> [MUSIC] Gestor de música activado.")
        else: 
            self.music_manager = None
            print(">> [MUSIC] Música desactivada.")
        
        if SocialCore: 
            self.social_manager = SocialCore(self)
            print(">> [SOCIAL] SocialCore activado.")
        else: 
            self.social_manager = None
            print(">> [SOCIAL] SocialCore desactivado.")
        
        self.neuro = None
        # Verificamos que NeuroCore exista y que tengamos conexión a nube (o modo offline permitido)
        if NeuroCore and self.cloud:
            self.neuro = NeuroCore(self)
            print(">> [NEURO] NeuroCore activado.")
        else:
            print(">> [NEURO] NeuroCore desactivado (Falta Cloud o Módulo).")
        
        self.cola_comandos = queue.Queue()
        self.cola_sugerencias = queue.Queue()
        
        self.inicializar_sistema()
        if PREDICCIONES_ACTIVAS:
            iniciar_hilo_predicciones(self.cola_comandos, self.cola_sugerencias)
            print(">> [PREDICCIONES] Sistema de predicciones activado.")
        
        # Iniciar escucha usando el idioma detectado
        self.iniciar_escucha_background()
        print(">> [SISTEMA] Sistema completamente inicializado.")

    def inicializar_sistema(self):
        self.recognizer = sr.Recognizer()
        # Usar el valor de configuración para el umbral de energía
        self.recognizer.energy_threshold = self.config.get('mic_threshold', 4000)
        try: 
            self.model = genai.GenerativeModel("gemini-2.0-flash")
            print(">> [IA] Gemini 2.0 Flash cargado.")
        except Exception as e: 
            print(f">> [IA] Error cargando Gemini: {e}")
            self.model = None

    def hablar(self, texto): 
        self.voz.decir(texto)
    
    def gestionar_interaccion(self, activo):
        if self.music_manager:
            if activo: 
                self.music_manager.pause(force=True)
            else: 
                self.music_manager.resume(force=True)
    
    def sonar(self):
        try: 
            winsound.Beep(800, 200) 
        except: 
            pass

    # --- WRAPPERS DE CLOUD (MODIFICADOS) ---
    def crear_usuario(self, email, password, user_name):
        """
        Crea un usuario nuevo pasando los datos al CloudManager.
        Ahora acepta el tercer argumento 'user_name'.
        """
        # 🟢 VERIFICACIÓN DE INVITADO
        if email.startswith("guest_"): 
            return {"ok": False, "error": "No disponible en modo invitado."}
            
        if self.cloud: 
            # Aquí pasamos los 3 datos al CloudManager
            # Cloud espera: (email, nombre, password)
            return self.cloud.crear_usuario(email, user_name, password)
            
        return {"ok": False, "error": "Nube inactiva."}
    
    def validar_login(self, email, password):
        if self.cloud: 
            return self.cloud.validar_login(email, password)
        return False
    
    def crear_sesion(self, email):
        # 🟢 FIX: Si es invitado, obtener token único temporal.
        if email == "guest":
            if self.cloud:
                token = self.cloud.crear_sesion(email) # Genera un token guest_f4a7b...
                self.usuario = token  # Usar el token como ID de sesión
                self.cargar_config(self.usuario) # Carga config local
                print(f">> [SESION] Sesión GUEST creada, token: {token[:20]}...")
                return token
            return f"offline_guest_{uuid.uuid4().hex}" # Fallback sin CloudManager
        
        # Lógica de usuario real
        if self.cloud:
            token = self.cloud.crear_sesion(email)
            if token:
                self.usuario = email
                self.cargar_config(email)
                print(f">> [SESION] Sesión creada para {email}, token: {token[:20]}...")
            return token
        return None
    
    def obtener_usuario_por_token(self, token):
        if self.cloud:
            email = self.cloud.obtener_usuario_por_token(token)
            if email:
                self.usuario = email
                self.cargar_config(email) # Carga local o de Firebase
                print(f">> [SESION] Usuario recuperado por token: {email}")
            return email
        
        # FIX: Si no hay cloud, pero el token parece de invitado (que inicia con 'guest_' o 'offline_guest_')
        if token.startswith("guest_") or token.startswith("offline_guest_"):
             self.usuario = token
             self.cargar_config(token)
             return token
        
        return None
    
    def cargar_config(self, email):
        """Carga la configuración desde Firebase (usuario real) o local (invitado)."""
        
        # 🟢 MODO INVITADO: Cargar desde archivo local
        if email.startswith("guest_") or email.startswith("offline_guest_"):
            if os.path.exists(CONFIG_GUEST_PATH):
                try:
                    with open(CONFIG_GUEST_PATH, 'r', encoding='utf-8') as f:
                        self.config = json.load(f)
                        # Asegurar que los nuevos campos existan
                        self.config.setdefault("mic_threshold", 4000)
                        self.config.setdefault("mic_timeout", 5)
                        self.config.setdefault("user_name", "Invitado")
                        self.config.setdefault("nombre", "Archeon")
                        return
                except:
                    pass
            
            # Valores por defecto para invitado
            self.config = {
                "nombre": "Archeon", 
                "tema": "dark", 
                "voz_id": "", 
                "user_name": "Invitado",
                "mic_threshold": 4000,
                "mic_timeout": 5
            }
            return
        
        # 🟢 MODO USUARIO REAL (Firebase)
        if self.cloud:
            datos = self.cloud.obtener_config(email)
            if datos:
                self.config = datos
                # Asegurar que los nuevos campos existan
                self.config.setdefault("mic_threshold", 4000)
                self.config.setdefault("mic_timeout", 5)
                if self.config.get('voz_id'): 
                    self.voz.actualizar_voz(self.config['voz_id'])

    def actualizar_config(self, email, nueva_config):
        """Actualiza la configuración en Firebase (usuario real) o local (invitado)."""
        
        self.config.update(nueva_config)
        
        # 🟢 MODO INVITADO: Guardar en archivo local
        if email.startswith("guest_") or email.startswith("offline_guest_"):
            try:
                with open(CONFIG_GUEST_PATH, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                print(f">> [SESION] Configuración GUEST guardada localmente.")
            except Exception as e:
                print(f"!! [SESION] Error guardando config local GUEST: {e}")
            
            if nueva_config.get('voz_id'): 
                self.voz.actualizar_voz(nueva_config['voz_id'])
            
            # --- NUEVO: APLICAR CAMBIOS DE HARDWARE EN TIEMPO REAL ---
            if 'mic_threshold' in nueva_config:
                new_thresh = int(nueva_config['mic_threshold'])
                print(f">> [AUDIO] Actualizando umbral de ruido a: {new_thresh}")
                # Actualizamos la propiedad de la librería speech_recognition
                self.recognizer.energy_threshold = new_thresh
            
            return

        # 🟢 MODO USUARIO REAL (Firebase)
        if self.cloud:
            if nueva_config.get('voz_id'): 
                self.voz.actualizar_voz(nueva_config['voz_id'])
            
            # --- NUEVO: APLICAR CAMBIOS DE HARDWARE EN TIEMPO REAL ---
            if 'mic_threshold' in nueva_config:
                new_thresh = int(nueva_config['mic_threshold'])
                print(f">> [AUDIO] Actualizando umbral de ruido a: {new_thresh}")
                # Actualizamos la propiedad de la librería speech_recognition
                self.recognizer.energy_threshold = new_thresh
            
            self.cloud.guardar_config(email, self.config)

    # --- ESCUCHA Y RAZONAMIENTO ---
    def iniciar_escucha_background(self):
        def loop():
            with sr.Microphone() as source:
                # Inicializar con el valor guardado o 4000 por defecto
                self.recognizer.energy_threshold = self.config.get('mic_threshold', 4000)
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                
                print(f">> LISTO. Umbral: {self.recognizer.energy_threshold}")

                while True:
                    if self.escuchando: 
                        time.sleep(0.5); 
                        continue
                    try:
                        # Leer timeout de la configuración (default 4 segundos)
                        listen_timeout = self.config.get('mic_timeout', 5)
                        
                        # Usar variable listen_timeout en lugar del numero fijo
                        audio = self.recognizer.listen(source, timeout=None, phrase_time_limit=listen_timeout)
                        
                        texto = self.recognizer.recognize_google(audio, language="es-ES").lower()
                        activador = self.config.get('nombre', 'archeon').lower()
                        
                        if activador in texto:
                            cmd = texto.replace(activador, "").strip()
                            if len(cmd) > 3:
                                self.escuchando = True
                                self.sonar() 
                                self.razonar_ia(cmd)
                                self.escuchando = False
                            else: 
                                self.activar_flujo()
                    except sr.UnknownValueError:
                        pass
                    except sr.RequestError as e:
                        print(f">> Error reconocimiento: {e}")
                    except Exception:
                        pass
        threading.Thread(target=loop, daemon=True).start()

    def activar_flujo(self):
        self.escuchando = True
        self.sonar() 
        try:
            with sr.Microphone() as source:
                # Leer timeout de la configuración (default 8 segundos para flujo activo)
                # Le sumamos un poco más porque aquí el usuario suele hablar más lento
                base_timeout = self.config.get('mic_timeout', 5)
                active_timeout = base_timeout + 3 
                
                print(f">> Escuchando orden ({self.idioma_sistema})... Timeout: {active_timeout}s")
                
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=active_timeout)
                
                cmd = self.recognizer.recognize_google(audio, language=self.idioma_sistema)
                
                print(f">> Orden: {cmd}")
                self.razonar_ia(cmd)
        except sr.UnknownValueError:
            # Nota: Si quisieras que esta respuesta también fuera multilingüe, 
            # deberías mover esta lógica al NeuroCore, pero por ahora está bien así.
            self.hablar("No te entendí, ¿puedes repetir?")
        except sr.RequestError as e:
            print(f">> Error de red: {e}")
            self.hablar("Problema de conexión con el servicio de voz.")
        except Exception:
            pass
        finally: 
            self.escuchando = False

    def razonar_ia(self, comando: str):
        """
        Punto de entrada único.
        Ya no hay if/else gigantes aquí. Todo se delega al NeuroCore.
        """
        cmd = comando.lower().strip()
        if not cmd: return 
        
        # 🔥 DELEGACIÓN TOTAL A NEUROCORE 🔥
        # NeuroCore usará internamente:
        # 1. Reasoner (para música, volumen, hora) -> Respuesta inmediata
        # 2. Knowledge (para preguntas de memoria)
        # 3. LLM (para charla)
        
        if self.neuro:
            accion = self.neuro.generar_respuesta_inteligente(self.usuario, cmd)
            
            if accion:
                tipo = accion.get("tipo", "chat")
                texto = accion.get("respuesta", "")
                
                # Feedback verbal
                if texto: self.hablar(texto)
                
                # Acciones físicas que el NeuroCore no puede hacer solo
                # (Aunque el DialogManager ya maneja la mayoría, esto es un fallback seguro)
                if tipo == "reproducir" and self.music_manager:
                    # En caso de que el Reasoner falle o sea una orden compleja
                    pass 
                
                # Aprendizaje de hábitos (Predicciones)
                if PREDICCIONES_ACTIVAS and tipo != "chat":
                    self.cola_comandos.put("accion_general") # Simplificado
                return

        # Fallback de emergencia (Solo si NeuroCore murió)
        self.hablar("Mi cerebro principal no responde.")

    def iniciar(self):
        servidor = _ServidorWeb(self)
        servidor.iniciar()
        
        # Esperar un momento para que el servidor inicie
        time.sleep(1)
        
        self.ventana_activa = webview.create_window(
            'Archeon AI', 'http://127.0.0.1:5000/login',
            width=450, height=750,
            background_color='#0f1216',
            resizable=True,
            easy_drag=False
        )
        
        print(">> [SISTEMA] Ventana web iniciada")
        print(">> [SISTEMA] URL: http://127.0.0.1:5000/login")
        print(">> [SISTEMA] Esperando interacción...")
        
        webview.start(debug=False, http_server=False)
        
        # Cierre forzoso para evitar procesos zombis
        print(">> [SISTEMA] Cerrando sistema forzosamente...")
        os._exit(0)

if __name__ == "__main__":
    archeon_updater.start_updater_thread() 
    AsistenteVirtual().iniciar()