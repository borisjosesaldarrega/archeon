# ========================================================================
# ARCHIVO: archeon_dialog_manager.py (FINAL VERSION)
# Enrutador central de inteligencia para Archeon
# ========================================================================

from threading import Thread
import time

class DialogManager:
    def __init__(self, main_assistant, reasoner, memory=None):
        self.main = main_assistant     # Acceso al núcleo (Archeo32n)
        self.reasoner = reasoner       # ArcheonReasoner
        self.memory = memory           # KnowledgeCore
        
        # Puente de tareas: Conecta el DialogManager con los sistemas reales
        self.tasks = TaskBridge(main_assistant)

    def process(self, text, context):
        """
        Cerebro central: Recibe texto -> Decide quién actúa -> Devuelve respuesta
        """
        # 1. Evaluación Lógica Rápida
        decision = self.reasoner.evaluate(text, context)
        intent = decision["intent"]
        params = decision["params"]
        
        # Si el razonador tiene una respuesta directa (ej: error lógico), la retornamos
        if not decision["approved"]:
            return decision["feedback"]

        # -----------------------------------------
        # 2️⃣ EL USUARIO ESTÁ ENSEÑANDO AL SISTEMA
        # -----------------------------------------
        if text.lower().startswith("aprende que") or text.lower().startswith("recuerda que"):
            content = text.replace("aprende que", "").replace("recuerda que", "").strip()
            if self.memory:
                self.memory.aprender(content)
                return "🧠 Comprendido. He guardado ese dato en mi memoria lógica."
        
        # -----------------------------------------
        # 3️⃣ CONSULTAS A LA MEMORIA
        # -----------------------------------------
        if "qué sabes de" in text.lower() or "qué recuerdas de" in text.lower():
            if self.memory:
                query = text.lower().replace("qué sabes de", "").replace("qué recuerdas de", "").strip()
                hechos = self.memory.recuperar_hechos_relevantes(query)
                if hechos:
                    respuesta = "Esto es lo que tengo registrado:\n"
                    for h in hechos:
                        respuesta += f"- {h['sujeto']} {h['predicado']}: {h['objeto']}\n"
                    return respuesta
            return "No tengo información registrada sobre eso."

        # -----------------------------------------
        # 4️⃣ EJECUCIÓN DE TAREAS (Música, Sistema, IoT)
        # -----------------------------------------
        # Usamos .value o .name dependiendo de cómo definiste el Enum en Reasoner
        intent_name = getattr(intent, 'name', str(intent))

        if intent_name == "PLAY_MUSIC":
            self._run_thread(self.tasks.play_music, params.get("query"))
            return f"Reproduciendo {params.get('query')}..."

        if intent_name == "STOP_MUSIC":
            self._run_thread(self.tasks.stop_music)
            return "Música detenida."

        if intent_name == "VOLUME":
            vol = params.get("value")
            self._run_thread(self.tasks.set_volume, vol)
            return f"Volumen ajustado al {vol}%."

        if intent_name == "SYSTEM":
            action = params.get("action")
            target = params.get("target", "")
            # Aquí podrías expandir con self.tasks.open_app(target)
            return f"Comando de sistema recibido: {action} {target} (Aún no implementado completamente)"

        # -----------------------------------------
        # 5️⃣ CONSULTA COMÚN → FALLBACK A IA GENERATIVA
        # -----------------------------------------
        # Si llegamos aquí, es una charla normal. Devolvemos None para que
        # NeuroCore use su LLM habitual.
        return None

    def _run_thread(self, function, *args):
        """Ejecuta tareas sin congelar al asistente"""
        t = Thread(target=function, args=args)
        t.daemon = True
        t.start()

# --- PUENTE DE TAREAS (Adaptador para tu código existente) ---
class TaskBridge:
    def __init__(self, main_assistant):
        self.main = main_assistant

    def play_music(self, query):
        if self.main.music_manager:
            self.main.music_manager.play_audio_threaded(query)

    def stop_music(self):
        if self.main.music_manager:
            self.main.music_manager.stop_audio()

    def set_volume(self, value):
        if self.main.music_manager:
            self.main.music_manager.set_music_volume(value)