import re
from enum import Enum

class Intent(Enum):
    PLAY_MUSIC = "play_music"
    STOP_MUSIC = "stop_music"
    VOLUME = "volume"
    SYSTEM = "system"
    SOCIAL = "social"
    UNKNOWN = "unknown"

class ArcheonReasoner:
    def __init__(self, memory_module=None):
        self.memory = memory_module  # Conexión con archeon_knowledge.py
        
    # 1. DETECCIÓN (Más robusta con Regex)
    def detect_intent(self, text):
        text = text.lower()
        
        # Música
        if any(w in text for w in ["reproduce", "pon ", "toca ", "play", "escuchar"]):
            return Intent.PLAY_MUSIC
        if any(w in text for w in ["detén", "para", "stop", "silencio", "pausa"]):
            return Intent.STOP_MUSIC
            
        # Sistema / Volumen
        if any(w in text for w in ["volumen", "baja", "sube", "sonido"]):
            return Intent.VOLUME
        if any(w in text for w in ["abre", "cierra", "ejecuta", "minimiza", "apaga"]):
            return Intent.SYSTEM
            
        # Social
        if any(w in text for w in ["mensaje", "whatsapp", "escribe a", "lee"]):
            return Intent.SOCIAL
            
        return Intent.UNKNOWN

    # 2. EXTRACCIÓN DE DATOS (Sacar el "qué" y el "cuánto")
    def extract_parameters(self, intent, text):
        params = {}
        text = text.lower()
        
        if intent == Intent.VOLUME:
            # Buscar números directos
            match = re.search(r"(\d+)", text)
            if match:
                params['value'] = int(match.group(1))
                params['mode'] = 'absolute'
            # Buscar comandos relativos
            elif "sube" in text:
                params['mode'] = 'up'
            elif "baja" in text:
                params['mode'] = 'down'
            elif "maximo" in text or "máximo" in text:
                params['value'] = 100
                params['mode'] = 'absolute'
            elif "mudo" in text or "silencio" in text:
                params['value'] = 0
                params['mode'] = 'absolute'
                
        elif intent == Intent.PLAY_MUSIC:
            # Limpiar el comando para dejar solo la canción
            clean = re.sub(r"(reproduce|pon|toca|play|quiero escuchar|escuchar)", "", text).strip()
            params['query'] = clean
            
        elif intent == Intent.SYSTEM:
            # Detectar si es abrir o cerrar
            if "abre" in text: params['action'] = "open"
            elif "cierra" in text: params['action'] = "close"
            # Extraer nombre app (simple)
            clean = re.sub(r"(abre|cierra|ejecuta|el|la|app|programa)", "", text).strip()
            params['target'] = clean
            
        return params

    # 3. EVALUACIÓN LÓGICA (El cerebro real)
    def evaluate(self, text, context):
        """
        Input: Texto usuario + Contexto actual (estado música, volumen, etc)
        Output: Dict con decisión final
        """
        intent = self.detect_intent(text)
        params = self.extract_parameters(intent, text)
        
        result = {
            "approved": True,       # ¿Se ejecuta?
            "intent": intent,       # Qué hacer
            "params": params,       # Con qué datos
            "feedback": None,       # Qué responder al usuario (si hay error/aviso)
            "override": False       # Si fuerza una acción sobre otra
        }

        # --- REGLAS DE MÚSICA ---
        if intent == Intent.PLAY_MUSIC:
            if not params.get('query'):
                result["approved"] = False
                result["feedback"] = "¿Qué canción quieres que ponga?"
                return result
                
            # Regla: Si ya suena música, avisar pero permitir cambio (Override)
            if context.get("music_playing"):
                result["override"] = True
                # Opcional: Podrías preguntar confirmación, pero para fluidez asumimos cambio.
                # result["feedback"] = f"Cambiando a {params['query']}..."

        elif intent == Intent.STOP_MUSIC:
            if not context.get("music_playing"):
                result["approved"] = False
                result["feedback"] = "No hay nada reproduciéndose ahora mismo."
                return result

        # --- REGLAS DE VOLUMEN ---
        elif intent == Intent.VOLUME:
            current_vol = context.get("volume", 50)
            
            if params.get('mode') == 'absolute':
                val = params.get('value')
                if val > 100:
                    result["params"]["value"] = 100
                    result["feedback"] = "El volumen máximo es 100. Lo pondré al máximo."
                elif val < 0:
                    result["approved"] = False
                    result["feedback"] = "El volumen no puede ser negativo."
            
            # Cálculo relativo inteligente
            elif params.get('mode') == 'up':
                result["params"]["value"] = min(current_vol + 10, 100)
                result["params"]["mode"] = "absolute" # Convertimos a absoluto para el sistema
            elif params.get('mode') == 'down':
                result["params"]["value"] = max(current_vol - 10, 0)
                result["params"]["mode"] = "absolute"

        # --- REGLAS DE CONOCIMIENTO (Integración opcional) ---
        # Si tienes memoria conectada, úsala aquí
        if self.memory and intent == Intent.PLAY_MUSIC:
            # Ejemplo: Verificar si el usuario odia un género (Ficticio por ahora)
            # if self.memory.check_dislike(params['query']):
            #    result["feedback"] = "Recuerda que dijiste que no te gusta ese artista. ¿Lo pongo igual?"
            pass

        return result