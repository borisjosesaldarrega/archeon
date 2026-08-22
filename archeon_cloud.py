# archeon_cloud.py (VERSIÓN DEFINITIVA PARA .EXE Y DESARROLLO) - OPTIMIZADA v9.6
import uuid
import hashlib
import os
import hmac
import base64
import time
import threading
import tempfile
import json
from datetime import datetime, timezone, timedelta

# Importamos las librerías de Firebase de forma segura
try:
    from firebase_admin import credentials, firestore, initialize_app
    import firebase_admin
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("!! [CLOUD] Librería firebase_admin no instalada. Ejecutando en MODO OFFLINE.")

class CloudManager:
    """
    Gestor de la nube (Firebase Firestore) BLINDADO Y AUTOMATIZADO.
    Versión optimizada v9.6 con Caché + Async + Inicialización en Memoria
    """
    
    # ==========================================================
    # 🔧 INICIALIZACIÓN Y CONFIGURACIÓN (OPTIMIZADO v9.6)
    # ==========================================================
    def __init__(self, firebase_config=None, secret_key=None):
        """Inicializa Firebase con múltiples métodos de autenticación"""
        self.cloud_ready = False 
        self.db = None
        self.firebase_app = None
        
        # ✅ MEJORA v9.6: SISTEMA DE CACHÉ INTELIGENTE (RAM)
        self._config_cache = {}  # {'email': {'data': {...}, 'timestamp': 12345678}}
        self._gustos_cache = {}
        self.CACHE_TTL = 300  # 5 minutos de vida para la caché

        if FIREBASE_AVAILABLE:
            self._initialize_firebase(firebase_config)

        key_source = secret_key or os.getenv("AR_SECRET_KEY", "AR_Default_Development_Key_2025")
        self.secret_key = key_source.encode()
        
    def _initialize_firebase(self, firebase_config):
        """✅ MEJORA v9.6: Inicialización en memoria sin archivos temporales"""
        try:
            cred = None
            
            # Método 1: Diccionario de credenciales (MODO .EXE) - INYECCIÓN DIRECTA
            if isinstance(firebase_config, dict):
                print(">> [CLOUD] Inyectando credenciales en memoria (Modo seguro)...")
                # ✅ MEJORA: Uso directo del diccionario, sin archivos temporales
                cred = credentials.Certificate(firebase_config)
                
            # Método 2: Ruta de archivo (MODO DESARROLLO)
            elif isinstance(firebase_config, str) and os.path.exists(firebase_config):
                print(f">> [CLOUD] Inicializando Firebase desde archivo: {firebase_config}")
                cred = credentials.Certificate(firebase_config)
                
            # Método 3: Sin configuración (usar credenciales por defecto)
            elif firebase_config is None:
                print(">> [CLOUD] Intentando inicializar sin credenciales explícitas...")
                # Firebase intentará buscar credenciales automáticamente
                if not firebase_admin._apps:
                    firebase_admin.initialize_app()
                self.db = firestore.client()
                self.cloud_ready = True
                self.firebase_app = firebase_admin.get_app()
                print("🔥 [CLOUD] Firebase inicializado sin credenciales explícitas")
                return
            
            # Si tenemos credenciales, inicializar
            if cred:
                if not firebase_admin._apps:
                    self.firebase_app = firebase_admin.initialize_app(cred)
                else:
                    self.firebase_app = firebase_admin.get_app()
                
                self.db = firestore.client()
                self.cloud_ready = True
                print("🔥 [CLOUD] Base de datos CONECTADA correctamente (Async Ready)")
                self._iniciar_mantenimiento()
                
        except Exception as e:
            print(f"❌ [CLOUD] Error inicializando Firebase: {e}")
            # Modo offline
            self.cloud_ready = False
    
    def _run_async(self, target_func, *args):
        """✅ MEJORA v9.6: Ejecuta una función en segundo plano para no bloquear"""
        if not self.cloud_ready: return
        t = threading.Thread(target=target_func, args=args, daemon=True)
        t.start()
            
    def _get_user_doc_id(self, email: str) -> str:
        """ID único e irreversible por usuario."""
        return hashlib.sha256(email.encode()).hexdigest()

    # ==========================================================
    # 🧹 MANTENIMIENTO AUTOMÁTICO (LIMPIEZA DE TOKENS)
    # ==========================================================
    def _iniciar_mantenimiento(self):
        """Lanza un hilo que limpia la base de datos cada 12 horas."""
        def tarea_limpieza():
            while True:
                time.sleep(60) # Espera inicial
                try:
                    if self.cloud_ready:
                        self.limpiar_sesiones_expiradas()
                except: 
                    pass
                time.sleep(43200) # Esperar 12 horas (12 * 60 * 60)

        t = threading.Thread(target=tarea_limpieza, daemon=True)
        t.start()

    def limpiar_sesiones_expiradas(self):
        """Borra de la base de datos los tokens que ya no sirven."""
        if not self.cloud_ready: 
            return
            
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            # Consulta eficiente (Requiere índice en 'expira')
            docs = self.db.collection("sessions").where("expira", "<", now_iso).stream()
            
            batch = self.db.batch()
            count = 0
            for doc in docs:
                batch.delete(doc.reference)
                count += 1
                if count >= 400: # Límite por batch de Firebase
                    batch.commit()
                    batch = self.db.batch()
                    count = 0
            
            if count > 0: 
                batch.commit()
                
            if count > 0: 
                print(f"🧹 [MANTENIMIENTO] Se eliminaron {count} sesiones expiradas.")
        except Exception as e:
            print(f"!! Error en limpieza: {e}")

    # ==========================================================
    # 🔐 HASH DE PASSWORD
    # ==========================================================
    def hash_password(self, password, salt=None):
        if not salt: 
            salt = os.urandom(16)
        else:
            try: 
                salt = bytes.fromhex(salt)
            except: 
                salt = os.urandom(16)
                
        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 300000)
        return hashed.hex(), salt.hex()

    # ==========================================================
    # 🔐 GESTIÓN DE USUARIOS
    # ==========================================================
    def crear_usuario(self, email, username, password):
        if not self.cloud_ready: 
            return {"ok": False, "error": "Modo offline. No se puede crear usuario."}
            
        try:
            doc_id = self._get_user_doc_id(email)
            user_ref = self.db.collection("users").document(doc_id)

            if user_ref.get().exists:
                return {"ok": False, "error": "El usuario ya existe."}

            hashed, salt = self.hash_password(password)

            user_ref.set({
                "email": email,
                "password_hash": hashed,
                "salt": salt,
                "creado": datetime.now(timezone.utc).isoformat(),
                "ultimo_login": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "nombre": "Archeon", 
                    "tema": "dark",
                    "voz_id": "",
                    "user_name": username 
                }
            })
            
            print(f">> [CLOUD] Usuario creado: {email} | Nombre: {username}")
            return {"ok": True, "msg": "Usuario creado exitosamente."}
            
        except Exception as e:
            print(f"!! [CLOUD] Error creando usuario: {e}")
            return {"ok": False, "error": str(e)}
        
    def validar_login(self, email, password):
        """Valida credenciales de usuario"""
        if not self.cloud_ready: 
            return False
            
        try:
            doc_id = self._get_user_doc_id(email)
            user_doc = self.db.collection("users").document(doc_id).get()
            
            if not user_doc.exists: 
                return False
                
            data = user_doc.to_dict()
            
            # Verificar que tenemos los datos necesarios
            if not data or "salt" not in data or "password_hash" not in data: 
                return False 
                
            # Calcular hash con la sal almacenada
            hashed_calculado, _ = self.hash_password(password, data["salt"])
            
            # Comparar de forma segura
            if hmac.compare_digest(hashed_calculado, data["password_hash"]):
                # ✅ MEJORA v9.6: Actualizar último login en segundo plano
                self._run_async(self._update_login_time, doc_id)
                return True
                
            return False
            
        except Exception as e:
            print(f"!! [CLOUD] Error validando login: {e}")
            return False
    
    def _update_login_time(self, doc_id):
        """✅ MEJORA v9.6: Actualiza el login en segundo plano"""
        try:
            self.db.collection("users").document(doc_id).update({
                "ultimo_login": datetime.now(timezone.utc).isoformat()
            })
        except Exception as e:
            print(f"!! Error actualizando login time: {e}")

    def actualizar_password(self, email, nueva_password):
        if not self.cloud_ready: 
            return False
            
        try:
            doc_id = self._get_user_doc_id(email)
            hashed, salt = self.hash_password(nueva_password)
            
            self.db.collection("users").document(doc_id).update({
                "password_hash": hashed, 
                "salt": salt,
                "actualizado": datetime.now(timezone.utc).isoformat()
            })
            
            print(f">> [CLOUD] Contraseña actualizada para: {email}")
            return True
            
        except Exception as e:
            print(f"!! [CLOUD] Error actualizando contraseña: {e}")
            return False

    # ==========================================================
    # 🔐 SESIONES
    # ==========================================================
    def firmar_token(self, token):
        firma = hmac.new(self.secret_key, token.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(firma).decode().rstrip("=")

    def crear_sesion(self, email):
        """Crea una sesión/token para el usuario"""
        if email == "guest":
            # 🟢 FIX: Genera un ID de sesión único y temporal para el modo invitado.
            return f"guest_{uuid.uuid4().hex}"
            
        if not self.cloud_ready:
            # Modo offline - token temporal
            return f"offline_{uuid.uuid4().hex}"
            
        try:
            token = uuid.uuid4().hex
            firma = self.firmar_token(token)
            exp = datetime.now(timezone.utc) + timedelta(hours=24)

            # Guardar sesión en Firestore
            self.db.collection("sessions").document(token).set({
                "email": email,
                "firma_almacenada": firma,
                "creado": datetime.now(timezone.utc).isoformat(),
                "expira": exp.isoformat()
            })
            
            print(f">> [CLOUD] Sesión creada para: {email}")
            return f"{token}:{firma}"
            
        except Exception as e:
            print(f"!! [CLOUD] Error creando sesión: {e}")
            # Fallback a token offline
            return f"fallback_{uuid.uuid4().hex}"

    def obtener_usuario_por_token(self, full_token):
        """Obtiene el email del usuario a partir del token"""
        if not full_token: 
            return None
            
        # 🟢 FIX CRÍTICO: Devolver el ID ÚNICO completo para que el sistema
        # pueda usarlo para cargar/guardar la configuración local temporal.
        if full_token.startswith("guest_"):
            return full_token 
            
        # Token offline/fallback
        if full_token.startswith("offline_") or full_token.startswith("fallback_"):
            return "offline_user"
            
        # Token de Firebase
        if ":" not in full_token: 
            return None

        try:
            token, firma_cliente = full_token.split(":", 1)
            
            # Validación criptográfica local (RÁPIDA) antes de ir a la nube
            firma_real = hmac.new(self.secret_key, token.encode(), hashlib.sha256).digest()
            firma_real_b64 = base64.urlsafe_b64encode(firma_real).decode().rstrip("=")
            
            if not hmac.compare_digest(firma_real_b64, firma_cliente):
                return None
            
            # Obtener documento de sesión
            doc = self.db.collection("sessions").document(token).get()
            if not doc.exists: 
                return None
                
            data = doc.to_dict()
            
            # Verificar expiración
            exp = datetime.fromisoformat(data["expira"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                # Token expirado - eliminar en segundo plano
                self._run_async(lambda: self.db.collection("sessions").document(token).delete())
                return None

            return data["email"]
            
        except Exception as e:
            print(f"!! [CLOUD] Error obteniendo usuario por token: {e}")
            return None

    # ==========================================================
    # 🗑️ ELIMINACIÓN DE DATOS (GDPR / DERECHO AL OLVIDO)
    # ==========================================================
    def eliminar_usuario_total(self, email):
        """Borra ABSOLUTAMENTE TODO de un usuario. Irreversible."""
        if not self.cloud_ready: 
            return False
            
        try:
            doc_id = self._get_user_doc_id(email)
            user_ref = self.db.collection("users").document(doc_id)
            
            # 1. Borrar subcolecciones
            subcolecciones = ["memoria", "gustos", "comandos", "chats", "config"]
            for subcoleccion in subcolecciones:
                try:
                    docs = user_ref.collection(subcoleccion).limit(500).stream()
                    batch = self.db.batch()
                    count = 0
                    for doc in docs:
                        batch.delete(doc.reference)
                        count += 1
                        if count >= 400:
                            batch.commit()
                            batch = self.db.batch()
                            count = 0
                    if count > 0: 
                        batch.commit()
                except:
                    pass
            
            # 2. Borrar documento principal
            user_ref.delete()
            
            # 3. Borrar sesiones activas
            sessions = self.db.collection("sessions").where("email", "==", email).stream()
            for session in sessions: 
                session.reference.delete()
            
            print(f"☠️ [CLOUD] Usuario {email} eliminado permanentemente.")
            return True
            
        except Exception as e:
            print(f"!! [CLOUD] Error eliminando usuario: {e}")
            return False

    # ==========================================================
    # ⚡ MEMORIA Y CONFIGURACIÓN OPTIMIZADA (CACHE + ASYNC)
    # ==========================================================
    def obtener_config(self, email):
        """✅ MEJORA v9.6: Obtiene configuración usando Caché para velocidad extrema"""
        if not self.cloud_ready: 
            return self._default_config(email)

        # 1. Revisar Caché RAM
        cached = self._config_cache.get(email)
        if cached:
            age = time.time() - cached['timestamp']
            if age < self.CACHE_TTL:  # Si tiene menos de 5 minutos
                return cached['data']

        # 2. Si no hay caché o expiró, buscar en Nube
        try:
            doc = self.db.collection("users").document(self._get_user_doc_id(email)).get()
            if doc.exists:
                data = doc.to_dict()
                config = data.get("config", {})
                # Asegurar que tenemos valores por defecto
                full_config = {**self._default_config(email), **config}
                
                # ✅ MEJORA: Actualizar Caché
                self._config_cache[email] = {
                    'data': full_config,
                    'timestamp': time.time()
                }
                return full_config
            return self._default_config(email)
            
        except Exception as e:
            print(f"!! [CLOUD] Error obteniendo config: {e}")
            return self._default_config(email)
    
    def _default_config(self, email):
        """Configuración por defecto"""
        name = email.split('@')[0] if '@' in email else "Usuario"
        return {
            "nombre": "Archeon",
            "tema": "dark",
            "voz_id": "",
            "user_name": name
        }

    def guardar_config(self, email, config):
        """✅ MEJORA v9.6: Guarda y actualiza la caché inmediatamente"""
        if not self.cloud_ready: 
            return
            
        # 1. Actualizar caché local (para que la UI se sienta instantánea)
        if email in self._config_cache:
            current = self._config_cache[email]['data']
            self._config_cache[email]['data'] = {**current, **config}
            self._config_cache[email]['timestamp'] = time.time()  # Refrescar TTL
        else:
            # Si no hay caché, crear una nueva
            self._config_cache[email] = {
                'data': {**self._default_config(email), **config},
                'timestamp': time.time()
            }

        # ✅ MEJORA v9.6: Guardar en Nube en Segundo Plano (Fire & Forget)
        self._run_async(self._guardar_config_cloud, email, config)
    
    def _guardar_config_cloud(self, email, config):
        """✅ MEJORA v9.6: Guarda la configuración en la nube en segundo plano"""
        try:
            doc_id = self._get_user_doc_id(email)
            user_ref = self.db.collection("users").document(doc_id)
            
            # Obtener configuración actual y actualizar
            current_doc = user_ref.get()
            if current_doc.exists:
                current_data = current_doc.to_dict()
                current_config = current_data.get("config", {})
                
                # Fusionar configuraciones
                merged_config = {**current_config, **config}
                
                # Guardar actualizado
                user_ref.set({
                    "config": merged_config,
                    "actualizado": datetime.now(timezone.utc).isoformat()
                }, merge=True)
            else:
                # Crear nuevo usuario con configuración
                user_ref.set({
                    "email": email,
                    "config": config,
                    "creado": datetime.now(timezone.utc).isoformat()
                })
                
            print(f">> [CLOUD] Configuración sincronizada: {email}")
            
        except Exception as e:
            print(f"!! [CLOUD] Error guardando config async: {e}")

    def guardar_recuerdo(self, email, categoria, contenido, importancia=1):
        """✅ MEJORA v9.6: Fire & Forget - No espera a que termine"""
        self._run_async(self._guardar_recuerdo_cloud, email, categoria, contenido, importancia)
    
    def _guardar_recuerdo_cloud(self, email, categoria, contenido, importancia):
        """✅ MEJORA v9.6: Guarda recuerdos en la nube en segundo plano"""
        if not self.cloud_ready: 
            return
            
        try:
            doc_id = self._get_user_doc_id(email)
            recuerdos_ref = self.db.collection("users").document(doc_id).collection("memoria")
            
            recuerdos_ref.add({
                "categoria": categoria,
                "contenido": contenido,
                "importancia": importancia,
                "fecha": datetime.now(timezone.utc).isoformat()
            })
            
        except Exception as e:
            print(f"!! [CLOUD] Error guardando recuerdo async: {e}")

    def obtener_recuerdos(self, email, min_importancia=1, limit=10):
        # ✅ MEJORA: Lectura directa (no cacheamos recuerdos dinámicos para ahorrar RAM)
        if not self.cloud_ready: 
            return []
            
        try:
            doc_id = self._get_user_doc_id(email)
            query = self.db.collection("users").document(doc_id)\
                .collection("memoria")\
                .where("importancia", ">=", min_importancia)\
                .order_by("fecha", direction=firestore.Query.DESCENDING)\
                .limit(limit)
                
            recuerdos = []
            for doc in query.stream():
                data = doc.to_dict()
                data["id"] = doc.id
                recuerdos.append(data)
                
            return recuerdos
            
        except Exception as e:
            print(f"!! [CLOUD] Error obteniendo recuerdos: {e}")
            return []

    # ==========================================================
    # ❤️ GUSTOS Y COMANDOS CON CACHÉ
    # ==========================================================
    def guardar_gusto(self, email, gusto, valor=True):
        """✅ MEJORA v9.6: Actualiza caché y guarda en segundo plano"""
        if not self.cloud_ready: 
            return
            
        # Update Cache
        if email not in self._gustos_cache:
            self._gustos_cache[email] = {}
        self._gustos_cache[email][gusto] = valor
        
        # ✅ MEJORA: Async Cloud
        self._run_async(self._guardar_gusto_cloud, email, gusto, valor)
    
    def _guardar_gusto_cloud(self, email, gusto, valor):
        """✅ MEJORA v9.6: Guarda gustos en la nube en segundo plano"""
        try:
            doc_id = self._get_user_doc_id(email)
            gustos_ref = self.db.collection("users").document(doc_id).collection("gustos")
            
            gustos_ref.document(gusto).set({
                "activo": valor,
                "fecha": datetime.now(timezone.utc).isoformat()
            }, merge=True)
            
        except Exception as e:
            print(f"!! [CLOUD] Error guardando gusto async: {e}")

    def obtener_gustos(self, email):
        """✅ MEJORA v9.6: Obtiene gustos usando caché"""
        # Check Cache
        if email in self._gustos_cache:
            return self._gustos_cache[email]
        
        if not self.cloud_ready: 
            return {}
            
        try:
            doc_id = self._get_user_doc_id(email)
            gustos_ref = self.db.collection("users").document(doc_id).collection("gustos")
            
            gustos = {}
            for doc in gustos_ref.stream():
                data = doc.to_dict()
                gustos[doc.id] = data.get("activo", False)
            
            # ✅ MEJORA: Fill Cache
            self._gustos_cache[email] = gustos
            return gustos
            
        except Exception as e:
            print(f"!! [CLOUD] Error obteniendo gustos: {e}")
            return {}

    def guardar_comando(self, email, comando, accion):
        """✅ MEJORA v9.6: Guarda comandos en segundo plano"""
        if not self.cloud_ready: 
            return
            
        # ✅ MEJORA: Ejecutar en segundo plano
        self._run_async(self._guardar_comando_cloud, email, comando, accion)
    
    def _guardar_comando_cloud(self, email, comando, accion):
        """✅ MEJORA v9.6: Guarda comando en la nube en segundo plano"""
        try:
            doc_id = self._get_user_doc_id(email)
            comandos_ref = self.db.collection("users").document(doc_id).collection("comandos")
            
            comandos_ref.document(comando).set({
                "accion": accion,
                "fecha": datetime.now(timezone.utc).isoformat(),
                "usos": firestore.Increment(1)
            }, merge=True)
            
        except Exception as e:
            print(f"!! [CLOUD] Error guardando comando async: {e}")

    def obtener_comandos(self, email):
        if not self.cloud_ready: 
            return {}
            
        try:
            doc_id = self._get_user_doc_id(email)
            comandos_ref = self.db.collection("users").document(doc_id).collection("comandos")
            
            comandos = {}
            for doc in comandos_ref.stream():
                data = doc.to_dict()
                comandos[doc.id] = data.get("accion", "")
                
            return comandos
            
        except Exception as e:
            print(f"!! [CLOUD] Error obteniendo comandos: {e}")
            return {}

    # ==========================================================
    # 💬 CHAT (ASÍNCRONO)
    # ==========================================================
    def guardar_mensaje_chat(self, email, contacto, texto, autor, leido=False):
        """✅ MEJORA v9.6: Guarda mensajes en segundo plano"""
        if not self.cloud_ready: 
            return
            
        # ✅ MEJORA: Ejecutar en segundo plano
        self._run_async(self._guardar_mensaje_chat_cloud, email, contacto, texto, autor, leido)
    
    def _guardar_mensaje_chat_cloud(self, email, contacto, texto, autor, leido):
        """✅ MEJORA v9.6: Guarda mensaje en la nube en segundo plano"""
        try:
            doc_id = self._get_user_doc_id(email)
            mensajes_ref = self.db.collection("users").document(doc_id)\
                .collection("chats").document(contacto).collection("mensajes")
            
            mensajes_ref.add({
                "texto": texto,
                "autor": autor,
                "leido": leido,
                "fecha": datetime.now(timezone.utc).isoformat()
            })
            
        except Exception as e:
            print(f"!! [CLOUD] Error guardando mensaje async: {e}")

    def obtener_chat(self, email, contacto, limit=50):
        if not self.cloud_ready: 
            return []
            
        try:
            doc_id = self._get_user_doc_id(email)
            mensajes_ref = self.db.collection("users").document(doc_id)\
                .collection("chats").document(contacto).collection("mensajes")
            
            # IMPORTANTE: Esto requiere un índice en Firebase (fecha DESC)
            query = mensajes_ref.order_by("fecha", direction=firestore.Query.DESCENDING).limit(limit)
            
            mensajes = []
            for doc in query.stream():
                data = doc.to_dict()
                mensajes.append(data)
                
            # Ordenar cronológicamente
            mensajes.reverse()
            return mensajes
            
        except Exception as e:
            print(f"!! [CLOUD] Error obteniendo chat: {e}")
            return []

    def mensajes_sin_leer(self, email):
        if not self.cloud_ready: 
            return []
            
        try:
            doc_id = self._get_user_doc_id(email)
            chats = self.db.collection("users").document(doc_id).collection("chats").stream()
            
            sin_leer = []
            for chat in chats:
                contacto = chat.id
                # Consulta rápida de no leídos
                unread_query = self.db.collection("users").document(doc_id)\
                    .collection("chats").document(contacto).collection("mensajes")\
                    .where("autor", "!=", "yo").where("leido", "==", False).limit(1).get()
                    
                if len(unread_query) > 0: 
                    sin_leer.append(contacto)
                    
            return sin_leer
            
        except Exception as e:
            print(f"!! [CLOUD] Error obteniendo mensajes sin leer: {e}")
            return []
        
# ==========================================================
    # 🔐 GESTIÓN DE CÓDIGOS (ESTRICTO BASE DE DATOS)
    # ==========================================================
    def guardar_codigo_verificacion(self, email, codigo):
        """Guarda en Firebase y CONFIRMA que se escribió correctamente."""
        if not self.cloud_ready: 
            print("!! [CLOUD] Error: Nube no disponible para guardar código.")
            return False

        try:
            # 1. Normalización
            email_clean = str(email).lower().strip()
            doc_id = hashlib.sha256(f"code_{email_clean}".encode()).hexdigest()
            
            print(f">> [CLOUD] Intentando escribir en DB | ID: {doc_id[:8]}...")

            datos = {
                "email": email_clean,
                "codigo": str(codigo).strip(),
                "expira": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                "creado": datetime.now(timezone.utc).isoformat()
            }

            # 2. ESCRITURA SINCRÓNICA (Bloqueante)
            # Usamos .set() directamente. Si falla la red, esto lanzará error aquí mismo.
            self.db.collection("verification_codes").document(doc_id).set(datos)
            
            # 3. AUTO-VERIFICACIÓN DE INTEGRIDAD (La prueba de fuego)
            # Intentamos leerlo inmediatamente para asegurar que la DB responde.
            check = self.db.collection("verification_codes").document(doc_id).get()
            
            if check.exists:
                print(f"✅ [CLOUD] Escritura CONFIRMADA en base de datos. El documento existe.")
                return True
            else:
                print(f"❌ [CLOUD CRÍTICO] Se ejecutó .set() pero el documento NO aparece. Error de persistencia.")
                return False

        except Exception as e:
            print(f"!! [CLOUD ERROR] La base de datos rechazó la escritura: {e}")
            return False

    def validar_codigo_verificacion(self, email, codigo_usuario):
        """Verifica directamente contra la base de datos."""
        if not self.cloud_ready: 
            return {"ok": False, "error": "Nube desconectada"}

        try:
            email_clean = str(email).lower().strip()
            doc_id = hashlib.sha256(f"code_{email_clean}".encode()).hexdigest()
            code_user = str(codigo_usuario).strip()
            
            print(f">> [CLOUD] Consultando DB para ID: {doc_id[:8]}...")
            
            # Forzamos lectura fresca del servidor
            doc_ref = self.db.collection("verification_codes").document(doc_id)
            doc = doc_ref.get()

            if not doc.exists:
                print(f"!! [CLOUD] Documento {doc_id[:8]} NO ENCONTRADO en la consulta de validación.")
                return {"ok": False, "error": "Código no encontrado (Error de DB)."}

            data = doc.to_dict()
            print(f">> [CLOUD] Datos recuperados: {data.get('codigo')} vs Ingresado: {code_user}")
            
            # Verificar expiración
            try:
                expira = datetime.fromisoformat(data["expira"])
                if datetime.now(timezone.utc) > expira:
                    return {"ok": False, "error": "El código ha expirado."}
            except: pass

            # Comparar
            if str(data["codigo"]).strip() == code_user:
                # Borrar tras uso
                try:
                    doc_ref.delete()
                except: pass
                return {"ok": True}
            else:
                return {"ok": False, "error": "Código incorrecto."}

        except Exception as e:
            print(f"!! [CLOUD] Error validando: {e}")
            return {"ok": False, "error": f"Error técnico: {e}"}