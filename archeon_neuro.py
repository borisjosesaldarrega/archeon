# En archeon_neuro.py

# 1. Importar el nuevo módulo
try:
    from archeon_dialog_manager import DialogManager
except ImportError:
    DialogManager = None

# =======================================================================
# ARCHIVO: archeon_neuro.py v9.5 (OPTIMIZADO - SIN CARGA SOCIAL)
# =======================================================================
import json
import wikipedia
import pyautogui
import pyperclip
import os 
import gc
import re
from datetime import datetime
from archeon_reasoner import ArcheonReasoner
from archeon_context_memory import ContextMemory
try:
    from archeon_openrouter import OpenRouterAdapter 
except ImportError:
    OpenRouterAdapter = None

try:
    from archeon_system import SystemCore
    from archeon_vision import VisionCore       
except ImportError:
    print("!! [NEURO] Faltan módulos satélite. Iniciando modo seguro.")
    SystemCore = None
    VisionCore = None

wikipedia.set_lang("es")

class NeuroCore:
    def __init__(self, asistente_principal):
        self.main = asistente_principal
        self.router_client = OpenRouterAdapter() if OpenRouterAdapter else None
        self.MODELO_LOGICA = "meta-llama/llama-3-8b-instruct"  # Modelo validado
        
        self.system = SystemCore() if SystemCore else None
        self.vision = VisionCore(self.main) if VisionCore else None
        
        self.security = None
        self.iot = None        
        self.chat_history = []
        self.contexto_actual = {
            'ultimo_tema': None,
            'modo_actual': 'normal',
            'ubicacion_inferida': 'casa'
        }
        
        self.CACHE_RESPUESTAS = {
            "hola": {"tipo": "chat", "respuesta": "¡Hola! ¿En qué puedo ayudarte?"},
            "gracias": {"tipo": "chat", "respuesta": "¡De nada! Estoy para ayudar."},
            "como estas": {"tipo": "chat", "respuesta": "¡Funcionando al máximo! Listo para ayudarte."}
        }
        
        # Inicializar módulos de inteligencia
        self.knowledge = KnowledgeCore(self.main) if 'KnowledgeCore' in globals() else None
        self.reasoner = ArcheonReasoner(self.knowledge) if 'ArcheonReasoner' in globals() else None
        self.memory = ContextMemory(max_messages=15, expiration_seconds=300)

        # 🔥 EL CEREBRO CENTRAL 🔥
        if DialogManager and self.reasoner:
            self.dialog = DialogManager(self.main, self.reasoner, self.knowledge)
        else:
            self.dialog = None

    def recordar(self, categoria, contenido, importancia=5):
        if not contenido: 
            return
        try:
            if hasattr(self.main, 'cloud') and self.main.cloud:
                self.main.cloud.guardar_recuerdo(
                    email=self.main.usuario,
                    categoria=categoria,
                    contenido=contenido,
                    importancia=importancia
                )
                print(f">> [NEURO CLOUD] Recuerdo guardado: [{categoria}] {contenido}")
        except Exception as e:
            print(f"!! Error guardando recuerdo: {e}")

    def recuperar_contexto(self):
        try:
            if hasattr(self.main, 'cloud') and self.main.cloud:
                recuerdos = self.main.cloud.obtener_recuerdos(
                    email=self.main.usuario,
                    min_importancia=5
                )
                if recuerdos:
                    memoria_vital = [f"- {r.get('contenido', '')}" for r in recuerdos[:6]]
                    return "\n".join(memoria_vital)
                return "Sin datos previos en la nube."
            return "Modo Invitado / Sin Nube."
        except Exception as e:
            print(f"!! Error recuperando contexto: {e}")
            return "Error de memoria cloud."

    def guardar_chat_reciente(self, role, content):
        self.chat_history.append({"role": role, "parts": [content]})
        if len(self.chat_history) > 15:
            self.chat_history.pop(0)

    def obtener_historial_chat(self):
        return self.chat_history

    def analizar_pantalla(self):
        return pyautogui.screenshot()

    def check_salud_subsistemas(self):
        salud = {
            'vision': self.vision is not None,
            'sistema': self.system is not None,
            'memoria': hasattr(self.main, 'cloud') and self.main.cloud is not None,
            'modelo': hasattr(self.main, 'model') and self.main.model is not None,
            'router': self.router_client is not None and hasattr(self.router_client, 'ready')
        }
        
        if self.router_client and hasattr(self.router_client, 'ready'):
            salud['router'] = self.router_client.ready
        
        return salud

    def _analizar_intencion(self, texto):
        text_lower = texto.lower()
        intencion = {
            'tipo': 'desconocido',
            'urgencia': 1,
            'confianza': 0.5
        }

        # --- 1. INTENCIÓN VISUAL ---
        if any(x in text_lower for x in ["mira", "ver", "pantalla", "analiza", "qué hay", "leé", "fíjate", "observa"]):
            intencion['tipo'] = 'vision'
            intencion['confianza'] = 0.95
            return intencion # Retornamos directo para ganar velocidad
        
        # --- 2. URGENCIA ---
        if any(x in text_lower for x in ["urgente", "rápido", "ahora", "inmediato", "pronto"]):
            intencion['urgencia'] = 9
        
        # --- 3. SISTEMA ---
        if any(x in text_lower for x in ["abre", "ejecuta", "inicia", "lanza", "corre", "cierra"]):
            intencion['tipo'] = 'sistema'
            intencion['confianza'] = 0.8
            return intencion
            
        # --- 4. MÚSICA ---
        if any(x in text_lower for x in ["pon", "reproduce", "play", "toca", "música"]):
            intencion['tipo'] = 'reproducir'
            intencion['confianza'] = 0.7
            return intencion
            
        # --- 5. INVESTIGACIÓN ---
        if any(x in text_lower for x in ["busca", "investiga", "qué es", "quién es"]):
            intencion['tipo'] = 'investigar'
            intencion['confianza'] = 0.6
            
        return intencion

    def _crear_prompt_inteligente(self, memoria_usuario, historial_ram):
        fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M")
        salud = self.check_salud_subsistemas()
        subsistemas_disponibles = [k for k, v in salud.items() if v]
        
        bloque_memoria_cloud = ""
        if memoria_usuario and len(str(memoria_usuario)) > 5:
            bloque_memoria_cloud = f"\n[DATOS CLAVE DEL USUARIO (CLOUD)]\n{memoria_usuario}\n"

        # Formatear memoria a corto plazo (RAM - Chat reciente)
        bloque_chat_reciente = ""
        if historial_ram:
            bloque_chat_reciente = "\n[CONVERSACIÓN RECIENTE (RAM)]\n"
            for msg in historial_ram:
                bloque_chat_reciente += f"{msg['role'].upper()}: {msg['content']}\n"

        return f"""[[SISTEMA ARCHEON v9.6 - NÚCLEO GLOBAL]]
FECHA: {fecha_hoy}
DESARROLLADOR: DZKnightCompany
IDENTIDAD: Archeon AI.
SUBSISTEMAS: {', '.join(subsistemas_disponibles)}
{bloque_memoria_cloud}

[🌐 PROTOCOLO DE IDIOMA UNIVERSAL - PRIORIDAD MÁXIMA]
Tu misión es actuar como un ESPEJO DE IDIOMA.
1. DETECTA el idioma exacto en el que escribe el usuario.
2. RESPONDE EXCLUSIVAMENTE EN ESE MISMO IDIOMA.
   - Si es Alemán -> Responde en Alemán.
   - Si es Chino/Mandarín -> Responde en Chino.
   - Si es Ruso -> Responde en Ruso.
   - Si es Inglés -> Responde en Inglés.
   - Si es Español -> Responde en Español.
   - Detecta cualquier otro idioma y responde en ese idioma.
3. ADAPTACIÓN CULTURAL: Usa expresiones naturales de ese idioma, no traducciones literales robóticas.
4. IMPORTANTE: NO escribas "Detectando idioma..." ni explicaciones tipo "Respuesta en inglés:". Solo da la respuesta final.

[🎙️ MODO OPTIMIZACIÓN DE VOZ]
Eres un Asistente de Voz, NO un lector de libros.
1. SÉ CONCISO: Máximo 2 o 3 oraciones por respuesta.
2. CERO LISTAS: No digas "1... 2... 3...". Habla fluido.
   - MAL: "Pasos: 1. Abrir. 2. Cerrar."
   - BIEN: "Primero abres la aplicación y luego la cierras."
3. AL GRANO: Ve directo a la respuesta.

[DUALIDAD DE INTELIGENCIA]
A. MODO EJECUTOR (Comandos):
   - Música, Apps, Visión -> Genera JSON exacto.
B. MODO CONVERSACIONAL (Charla):
   - Preguntas, Datos, Ayuda -> Genera respuesta verbal EXPERTA pero CORTA.

[GUÍA DE CAPACIDADES]
- Música: "pon X", "play X".
- Visión: "mira pantalla", "analiza esto".
- Sistema: "abre/cierra X", "open/close X".
- Chat: Todo lo demás.

[FORMATO DE SALIDA JSON]:
{{
    "tipo": "chat" | "reproducir" | "vision" | "sistema",
    "dato": "argumento_tecnico_o_vacio",
    "respuesta": "Respuesta verbal corta (EN EL IDIOMA DETECTADO)",
    "confianza": 1.0
}}
"""

    def _procesar_cascada(self, input_text, sys_prompt, historial):
        if input_text.lower() in self.CACHE_RESPUESTAS:
            return {"text": json.dumps(self.CACHE_RESPUESTAS[input_text.lower()])}
        
        if self.router_client and hasattr(self.router_client, 'ready') and self.router_client.ready:
            try:
                print(f">> [NEURO] Pensando con OpenRouter ({self.MODELO_LOGICA})...")
                response = self.router_client.send_message(
                    prompt=f"{sys_prompt}\n\nUSER INPUT: {input_text}",
                    modelo=self.MODELO_LOGICA
                )
                return {"text": response.text}
            except Exception as e:
                print(f"!! [OPENROUTER ERROR]: {e}")
                # Caer a Gemini
                pass
        
        if hasattr(self.main, 'model') and self.main.model:
            try:
                chat = self.main.model.start_chat(history=historial)
                response = chat.send_message(f"{sys_prompt}\n\nUSER INPUT: {input_text}")
                return {"text": response.text.strip()}
            except Exception as e:
                print(f"!! [GEMINI ERROR]: {e}")
        
        return {"text": '{"tipo": "chat", "respuesta": "Error de conexión con los modelos.", "confianza": 0.1}'}

    def _limpiar_markdown(self, texto):
        """Elimina asteriscos, guiones bajos y formatos de markdown para que la voz sea limpia."""
        if not texto: return ""
        # Eliminar negritas y cursivas (**texto**, *texto*)
        limpio = re.sub(r'\*\*|__|\*', '', texto)
        # Eliminar encabezados (### Texto)
        limpio = re.sub(r'^#+\s+', '', limpio)
        # Eliminar bloques de código (```)
        limpio = limpio.replace("```", "")
        return limpio.strip()

    def generar_respuesta_inteligente(self, usuario_email, input_text):
        text_lower = input_text.lower()

        # ✅ 1. MEMORIA RAM: Guardar lo que dijo el usuario
        if self.memory:
            self.memory.add("user", input_text)

        # ✅ 2. ANALIZAR INTENCIÓN
        intencion = self._analizar_intencion(input_text)

        # --- 3. TRIGGERS RÁPIDOS ---
        if any(x in text_lower for x in ["creador", "quien te creo", "quien te hizo", "tu dueño"]):
            resp = "Fui creado por Boris, de DZKnightCompany."
            if self.memory: self.memory.add("assistant", resp)
            return {"tipo": "chat", "respuesta": resp, "confianza": 1.0}
        
        # --- 4. DIALOG MANAGER ---
        if self.dialog:
            ctx_sys = {"music_playing": False, "volume": 50}
            if self.main.music_manager:
                ctx_sys["music_playing"] = (self.main.music_manager.stream_out is not None)
                ctx_sys["volume"] = int(self.main.music_manager.internal_volume * 100)
            
            respuesta_manager = self.dialog.process(input_text, ctx_sys)
            if respuesta_manager:
                resp_clean = self._limpiar_markdown(respuesta_manager)
                if self.memory: self.memory.add("assistant", resp_clean)
                return {"tipo": "chat", "respuesta": resp_clean, "confianza": 1.0}
        
        # --- 5. VISIÓN Y UTILIDADES ---
        triggers_vision = ["mira esto", "mira la pantalla", "qué ves", "analiza esto", "analiza la pantalla"]
        if (intencion['tipo'] == 'vision' or any(x in text_lower for x in triggers_vision)) and self.vision:
            if self.memory: self.memory.add("assistant", "[Análisis visual realizado]")
            return {"tipo": "chat", "respuesta": self.vision.ver_y_analizar(input_text), "confianza": 0.9}
            
        if "wikipedia" in text_lower:
            try:
                q = text_lower.replace("wikipedia", "").replace("busca", "").strip()
                if q: 
                    resp = f"📚 {wikipedia.summary(q, sentences=2)}"
                    if self.memory: self.memory.add("assistant", resp)
                    return {"tipo": "chat", "respuesta": resp, "confianza": 0.8}
            except: pass
            
        if "resume lo copiado" in text_lower:
            try:
                txt = pyperclip.paste()
                if txt: input_text = f"Resume esto: {txt[:1500]}"
            except: pass

        # --- 6. RAZONADOR LÓGICO ---
        if hasattr(self, 'reasoner') and self.reasoner:
            ctx_sys = {"music_playing": False, "volume": 50}
            if self.main.music_manager:
                ctx_sys["music_playing"] = (self.main.music_manager.stream_out is not None)
                ctx_sys["volume"] = int(self.main.music_manager.internal_volume * 100)
            
            decision_logica = self.reasoner.evaluate(input_text, ctx_sys)
            
            if not decision_logica["approved"]:
                resp = self._limpiar_markdown(decision_logica["feedback"])
                if self.memory: self.memory.add("assistant", resp)
                return {"tipo": "chat", "respuesta": resp, "confianza": 1.0}
            
            if decision_logica["intent"] == "volume":
                vol = decision_logica["params"].get("value")
                if self.main.music_manager: self.main.music_manager.set_music_volume(vol)
                msg = decision_logica["feedback"] if decision_logica["feedback"] else f"Volumen al {vol}%."
                if self.memory: self.memory.add("assistant", msg)
                return {"tipo": "chat", "respuesta": msg, "confianza": 1.0}

        # --- 7. FALLBACK A IA GENERATIVA (Con Contexto) ---
        memoria_usuario = self.recuperar_contexto() # Nube
        historial_ram = self.memory.get_history_for_llm() if self.memory else []
        
        sys_prompt = self._crear_prompt_inteligente(memoria_usuario, historial_ram)
        sys_prompt += "\n[FORMATO DE VOZ]: Usa TEXTO PLANO. NO uses Markdown. Escribe como se habla."

        try:
            # Enviamos a la IA (Pasamos historial vacío porque ya va en el prompt manual)
            resultado = self._procesar_cascada(input_text, sys_prompt, []) 
            clean_resp = resultado["text"].replace("```json", "").replace("```", "").strip()
            
            decision = {"tipo": "chat", "respuesta": clean_resp, "confianza": 0.5}
            
            # Intentar parsear JSON si es comando
            match = re.search(r'\{[\s\S]*\}', clean_resp)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    decision.update(parsed)
                    if 'confianza' not in decision: decision['confianza'] = intencion['confianza']
                except: pass
            
            # Limpieza Markdown
            if "respuesta" in decision:
                decision["respuesta"] = self._limpiar_markdown(decision["respuesta"])
            
            # ✅ MEMORIA RAM: Guardar la respuesta final de la IA
            if self.memory and "respuesta" in decision:
                self.memory.add("assistant", decision["respuesta"])

            # --- EJECUCIÓN DE ACCIONES RESTANTES ---
            tipo = decision.get("tipo")
            dato = decision.get("dato", "")
            
            # Sistema
            if tipo == "sistema" and self.system:
                if decision.get("confianza", 0) > 0.7 or "abre" in text_lower:
                    res = self.system.ejecutar_accion_sistema(dato or input_text)
                    return {"tipo": "chat", "respuesta": self._limpiar_markdown(res), "confianza": 0.9}
                return {"tipo": "chat", "respuesta": f"¿Ejecuto '{dato}'?", "confianza": 0.4}

            # Música
            if tipo == "reproducir" and self.system:
                if any(x in text_lower for x in ["video", "youtube", "película"]):
                    return {"tipo": "chat", "respuesta": self.system.poner_video_web(dato), "confianza": 0.8}
                return decision

            # Seguridad
            if tipo == "seguridad" and self.security:
                res = self.security.activar_centinela() if "activ" in str(dato) else self.security.desactivar_centinela()
                return {"tipo": "chat", "respuesta": self._limpiar_markdown(res), "confianza": 0.9}
            
            # Optimización de memoria
            gc.collect()

            return decision

        except Exception as e:
            print(f"!! [NEURO ERROR]: {e}")
            return {"tipo": "chat", "respuesta": "Tuve un error interno.", "confianza": 0.1}

# =======================================================================
# FIN DEL ARCHIVO: archeon_neuro.py