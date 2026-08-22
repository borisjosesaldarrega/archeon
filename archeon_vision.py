# =======================================================================
# ARCHIVO: archeon_vision.py v2.0 (OPTIMIZADO - SNAPSHOT ON DEMAND)
# =======================================================================
import os
import time
import pyautogui
from PIL import Image
import io

# Intentamos importar librerías ligeras para contexto de ventana
try:
    import pygetwindow as gw
    WINDOW_AWARE = True
except ImportError:
    WINDOW_AWARE = False

class VisionCore:
    def __init__(self, asistente_principal):
        self.ai = asistente_principal
        # NO iniciamos ningún proceso pesado aquí.
        # El sistema está "dormido" hasta que se le llama.
        print(">> [VISIÓN] Módulo óptico en espera (Modo: Bajo Consumo).")

    def _obtener_contexto_ventana(self):
        """Obtiene el título de la ventana activa (muy ligero)."""
        if WINDOW_AWARE:
            try:
                ventana = gw.getActiveWindow()
                if ventana:
                    return f"Aplicación en primer plano: {ventana.title}"
            except: pass
        return "Ventana desconocida"

    def ver_y_analizar(self, pregunta_usuario):
        """
        ESTRATEGIA SNAPSHOT (Cero consumo en reposo):
        1. Captura instantánea (se guarda en RAM, no disco, para velocidad).
        2. Envío a Gemini.
        3. Liberación inmediata de memoria.
        """
        print(">> [VISIÓN] Abriendo obturador... Capturando momento.")
        self.ai.hablar("Déjame ver...")

        try:
            # 1. FOTO INSTANTÁNEA (En memoria RAM para no gastar Disco)
            screenshot = pyautogui.screenshot()
            
            # 2. Contexto rápido
            contexto_app = self._obtener_contexto_ventana()
            
            # 3. Preparar Prompt para la IA
            prompt_visual = f"""
            [SISTEMA VISUAL ARCHEON]
            Contexto técnico: El usuario está en la aplicación "{contexto_app}".
            
            [SOLICITUD DEL USUARIO]
            "{pregunta_usuario}"
            
            [INSTRUCCIONES]
            - Analiza la captura de pantalla adjunta.
            - Responde DIRECTAMENTE a la solicitud del usuario.
            - Si ves un error, da la solución técnica.
            - Si ves código o texto, analízalo.
            - Si piden recomendación, sé crítico y profesional.
            - Sé breve (máximo 3 frases), directo y útil.
            """

            # 4. Enviar a Gemini (Usando el modelo multimodal del Main)
            if self.ai.model:
                response = self.ai.model.generate_content([prompt_visual, screenshot])
                analisis = response.text
                
                # 5. LIMPIEZA (Liberar memoria explícitamente)
                del screenshot
                
                print(f">> [VISIÓN] Análisis completado: {analisis[:50]}...")
                return analisis
            else:
                return "No tengo conexión con mi cerebro visual."

        except Exception as e:
            print(f"!! Error en proceso visual: {e}")
            return "Tuve un problema al intentar ver la pantalla."