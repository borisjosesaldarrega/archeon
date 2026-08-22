import requests
import json
import os
from dotenv import load_dotenv

# Cargar variables de entorno AL INICIO
load_dotenv()

class OpenRouterAdapter:
    def __init__(self):
        """Adaptador robusto para OpenRouter API"""
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        
        if not self.api_key:
            print("⚠️  [OPENROUTER] API Key no encontrada. Usa .env con OPENROUTER_API_KEY")
            self.ready = False
            return
            
        print(f"🔑 [OPENROUTER] API Key detectada ({self.api_key[:15]}...)")
        
        self.ready = True
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        
        # Headers MINIMALISTAS y SEGUROS (sin URLs problemáticas)
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "Archeon AI Assistant v8.1",
            "HTTP-Referer": "http://localhost:5000",
             "User-Agent": "Archeon-AI-Assistant/8.1"
        }
        
        # Verificación inicial de conexión
        try:
            # Solo ping a la raíz para ver si hay internet
            test_response = requests.get("https://openrouter.ai", timeout=5)
            print("✅ [OPENROUTER] Conexión a OpenRouter establecida")
        except Exception as e:
            print(f"❌ [OPENROUTER] Error de conexión: {e}")
            self.ready = False

    class FakeGeminiResponse:
        """Simula respuesta de Gemini para compatibilidad total"""
        def __init__(self, text_content):
            self.text = text_content.strip() if text_content else ""
            
        def replace(self, old, new):
            """Simula el método replace para compatibilidad"""
            return self.text.replace(old, new)

    def generate_content(self, prompt: str, modelo: str = "meta-llama/llama-3-8b-instruct"):
        """
        Genera contenido con OpenRouter.
        MODELO CORRECTO: 'mistralai/mixtral-8x7b-instruct' (sin -v0.1)
        """
        if not self.ready:
            return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "OpenRouter no disponible", "confianza": 0.1}')
        
        # SEPARAR SYSTEM PROMPT Y USER INPUT (ESTO ES CLAVE)
        system_prompt = ""
        user_input = prompt
        
        # Buscar el formato típico de NeuroCore
        if "[[SISTEMA ARCHEON" in prompt and "USER INPUT:" in prompt:
            parts = prompt.split("USER INPUT:", 1)
            system_prompt = parts[0].strip()
            user_input = parts[1].strip()
        
        # FORMATO CORRECTO para OpenRouter con roles separados
        messages = []
        
        # Agregar system prompt si existe
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # Agregar user input
        messages.append({"role": "user", "content": user_input})
        
        # Si no hay system prompt, usar todo como user
        if not messages:
            messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": modelo,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 800,
            "top_p": 0.9
        }
        
        try:
            # DEBUG: Mostrar lo que se envía
            print(f"📤 [OPENROUTER] Enviando a modelo '{modelo}'...")
            print(f"   System prompt: {'Sí' if system_prompt else 'No'}")
            print(f"   User input: {user_input[:50]}...")
            
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=20
            )
            
            print(f"📥 [OPENROUTER] Respuesta HTTP: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                
                if 'choices' in result and result['choices']:
                    content = result['choices'][0]['message']['content']
                    print(f"✅ [OPENROUTER] Respuesta obtenida ({len(content)} chars)")
                    return self.FakeGeminiResponse(content)
                else:
                    print("⚠️  [OPENROUTER] Respuesta sin 'choices'")
                    return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "Formato de respuesta inválido", "confianza": 0.1}')
            
            # MANEJO DE ERRORES DETALLADO
            elif response.status_code == 400:
                try:
                    error_info = response.json()
                    error_msg = error_info.get('error', {}).get('message', 'Bad Request')
                except:
                    error_msg = response.text[:100]
                
                print(f"❌ [OPENROUTER] Error 400: {error_msg}")
                print(f"   Modelo: {modelo}")
                
                # Probar con modelo más simple si falla
                if modelo == "meta-llama/llama-3-8b-instruct":
                    print("🔄 [OPENROUTER] Probando con modelo más simple...")
                    simple_payload = {
                        "model": "mistralai/mistral-7b-instruct",
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 600
                    }
                    
                    simple_response = requests.post(
                        self.base_url,
                        headers=self.headers,
                        json=simple_payload,
                        timeout=15
                    )
                    
                    if simple_response.status_code == 200:
                        simple_result = simple_response.json()
                        if 'choices' in simple_result and simple_result['choices']:
                            content = simple_result['choices'][0]['message']['content']
                            return self.FakeGeminiResponse(content)
                
                return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "Error de formato en la solicitud", "confianza": 0.1}')
            
            elif response.status_code == 401:
                print("❌ [OPENROUTER] Error 401: API Key inválida o expirada")
                return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "Error de autenticación con OpenRouter", "confianza": 0.1}')
            
            elif response.status_code == 404:
                print(f"❌ [OPENROUTER] Error 404: URL no encontrada")
                return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "Endpoint de OpenRouter no disponible", "confianza": 0.1}')
            
            elif response.status_code == 429:
                print("⚠️  [OPENROUTER] Error 429: Límite de tasa excedido")
                return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "Límite de peticiones excedido. Espera un momento.", "confianza": 0.1}')
            
            else:
                print(f"⚠️  [OPENROUTER] Error HTTP {response.status_code}")
                return self.FakeGeminiResponse(f'{{"tipo": "chat", "respuesta": "Error HTTP {response.status_code}", "confianza": 0.1}}')
                
        except requests.exceptions.Timeout:
            print("⏰ [OPENROUTER] Timeout después de 20 segundos")
            return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "Timeout al conectar con OpenRouter", "confianza": 0.1}')
            
        except requests.exceptions.ConnectionError:
            print("🌐 [OPENROUTER] Error de conexión (sin internet/VPN)")
            return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "Error de conexión. Revisa tu internet.", "confianza": 0.1}')
            
        except json.JSONDecodeError:
            print("📄 [OPENROUTER] Error parseando JSON de respuesta")
            return self.FakeGeminiResponse('{"tipo": "chat", "respuesta": "Error procesando respuesta del servidor", "confianza": 0.1}')
            
        except Exception as e:
            print(f"💥 [OPENROUTER] Error inesperado: {type(e).__name__}: {str(e)}")
            return self.FakeGeminiResponse(f'{{"tipo": "chat", "respuesta": "Error interno del adaptador", "confianza": 0.1}}')

    # Métodos de compatibilidad
    def start_chat(self, history=None):
        """Para compatibilidad con interfaz de Gemini"""
        return self

    def send_message(self, prompt, modelo="mistralai/mixtral-8x7b-instruct"):
        """
        Interfaz principal para NeuroCore.
        
        Args:
            prompt: Texto completo del prompt (sys_prompt + user_input)
            modelo: Modelo a usar (por defecto: Mixtral 8x7B Instruct)
            
        Returns:
            FakeGeminiResponse con la respuesta del modelo
        """
        return self.generate_content(prompt, modelo)