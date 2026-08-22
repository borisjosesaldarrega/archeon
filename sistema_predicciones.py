# =======================================================================
# ARCHIVO: sistema_predicciones.py v3.2 (COMPLETO Y CORREGIDO)
# =======================================================================
import os
import json
import threading
import shutil
import queue
import time
from datetime import datetime
from collections import defaultdict, Counter

try:
    import psutil
    HARDWARE_AWARE = True
except ImportError:
    HARDWARE_AWARE = False

HISTORIAL_PATH = "memoria_predicciones.json"
BACKUP_PATH = "memoria_predicciones.bak"

class CerebroPredictivo:
    def __init__(self):
        # Estructuras de datos
        self.transiciones = defaultdict(lambda: defaultdict(float))
        self.contexto_hora = defaultdict(lambda: defaultdict(float))
        self.contexto_hardware = defaultdict(lambda: defaultdict(float))
        
        self.ultima_accion = None
        self.ultima_sugerencia = None
        self.contador_acciones = 0  # Para guardado periódico
        
        # Configuración
        self.DECAY_RATE = 0.995
        self.UMBRAL_CONFIANZA = 0.7
        self.GUARDAR_CADA = 3  # Guardar cada 3 interacciones
        
        # CONCEPTOS (ORDEN CRÍTICO: feedback primero)
        self.conceptos = {
            # Feedback NEGATIVO primero (prioridad máxima)
            'feedback_negativo': ['no', 'error', 'equivocado', 'incorrecto', 
                                  'cancela', 'para', 'detente', 'basta', 'callate', 
                                  'mal', 'tonto', 'inútil', 'equivocaste'],
            # Feedback POSITIVO segundo
            'feedback_positivo': ['sí', 'correcto', 'bien', 'exacto', 'perfecto',
                                 'bueno', 'genial', 'excelente', 'gracias'],
            # Luego el resto
            'vision': ['mira', 'ver', 'pantalla', 'analiza', 'qué ves', 
                      'observa', 'fíjate', 'revisa', 'echa un vistazo'],
            'media': ['pon', 'reproduce', 'música', 'video', 'youtube', 
                     'spotify', 'canción', 'película', 'escucha', 'toca'],
            'social_mensaje': ['envía', 'mensaje', 'whatsapp', 'escribe', 
                              'manda', 'texto', 'avisa'],
            'social_leer': ['lee', 'revisa', 'mensajes', 'nuevo', 'chat'],
            'app_abrir': ['abre', 'ejecuta', 'inicia', 'lanza', 'corre'],
            'app_cerrar': ['cierra', 'termina', 'mata', 'finaliza'],
            'mantenimiento': ['limpia', 'basura', 'papelera', 'lento', 
                             'optimiza', 'arregla', 'repara'],
            'busqueda': ['busca', 'investiga', 'encuentra', 'qué es', 
                        'quién es', 'dónde está'],
            'sistema': ['apaga', 'reinicia', 'duerme', 'enciende', 'configura']
        }
        
        # Comandos ejecutables
        self.comandos_ejecutables = {
            'vision': "analiza la pantalla",
            'media': "reproduce música",
            'social_mensaje': "envía un mensaje",
            'social_leer': "lee mensajes de WhatsApp",
            'app_abrir': "abre el navegador",
            'app_cerrar': "cierra aplicaciones",
            'mantenimiento': "limpia archivos temporales",
            'busqueda': "busca en internet",
            'sistema': "¿quieres apagar el sistema?",
            'feedback_negativo': "",  # No se convierte a comando
            'feedback_positivo': ""   # No se convierte a comando
        }
        
        self.cargar_memoria()
    
    # ========== PERSISTENCIA (COMPLETO) ==========
    def cargar_memoria(self):
        """Carga la memoria desde disco con robustez"""
        archivos = [HISTORIAL_PATH, BACKUP_PATH]
        cargado = False
        
        for archivo in archivos:
            if os.path.exists(archivo):
                try:
                    with open(archivo, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Reconstruir defaultdicts anidados
                    self.transiciones = defaultdict(
                        lambda: defaultdict(float), 
                        {k: defaultdict(float, v) for k, v in data.get('transiciones', {}).items()}
                    )
                    self.contexto_hora = defaultdict(
                        lambda: defaultdict(float), 
                        {k: defaultdict(float, v) for k, v in data.get('contexto_hora', {}).items()}
                    )
                    self.contexto_hardware = defaultdict(
                        lambda: defaultdict(float), 
                        {k: defaultdict(float, v) for k, v in data.get('contexto_hardware', {}).items()}
                    )
                    
                    self.ultima_accion = data.get('ultima_accion')
                    self.contador_acciones = data.get('contador_acciones', 0)
                    
                    print(f"[PREDICCIONES] Memoria cargada desde {archivo} ({self.contador_acciones} acciones)")
                    cargado = True
                    break
                    
                except json.JSONDecodeError:
                    print(f"[PREDICCIONES] Error en {archivo}, intentando backup...")
                except Exception as e:
                    print(f"[PREDICCIONES] Error cargando {archivo}: {e}")
        
        if not cargado:
            print("[PREDICCIONES] Iniciando memoria nueva")
    
    def guardar_memoria(self):
        """Guarda la memoria en disco con backup"""
        try:
            # Crear backup si existe
            if os.path.exists(HISTORIAL_PATH):
                shutil.copy2(HISTORIAL_PATH, BACKUP_PATH)
            
            # Preparar datos
            data = {
                'transiciones': dict(self.transiciones),
                'contexto_hora': dict(self.contexto_hora),
                'contexto_hardware': dict(self.contexto_hardware),
                'ultima_accion': self.ultima_accion,
                'contador_acciones': self.contador_acciones,
                'timestamp': datetime.now().isoformat()
            }
            
            # Convertir defaultdicts anidados
            for key in ['transiciones', 'contexto_hora', 'contexto_hardware']:
                if key in data:
                    data[key] = {k: dict(v) for k, v in data[key].items()}
            
            # Guardar
            with open(HISTORIAL_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # print(f"[PREDICCIONES] Memoria guardada ({self.contador_acciones} acciones)")
            
        except Exception as e:
            print(f"[PREDICCIONES] Error guardando memoria: {e}")
    
    # ========== ANÁLISIS DE TEXTO ==========
    def extraer_concepto(self, texto):
        """Extrae el concepto principal con prioridad inteligente"""
        texto = texto.lower().strip()
        
        # 1. PRIORIDAD ABSOLUTA: Feedback negativo
        for palabra in self.conceptos['feedback_negativo']:
            if palabra in texto:
                return 'feedback_negativo'
        
        # 2. PRIORIDAD ALTA: Feedback positivo
        for palabra in self.conceptos['feedback_positivo']:
            if palabra in texto:
                return 'feedback_positivo'
        
        # 3. Buscar otros conceptos (excluyendo feedback)
        for concepto, palabras in self.conceptos.items():
            if concepto not in ['feedback_negativo', 'feedback_positivo']:
                for palabra in palabras:
                    if palabra in texto:
                        return concepto
        
        # 4. Si no encuentra, extraer verbo principal
        palabras = texto.split()
        if palabras:
            primer_palabra = palabras[0]
            # Solo usar raw_ si es un verbo conocido
            verbos_conocidos = ['calcula', 'resume', 'traduce', 'explica', 
                               'dibuja', 'programa', 'crea', 'escribe']
            if primer_palabra in verbos_conocidos:
                return f"raw_{primer_palabra}"
        
        return "desconocido"
    
    # ========== CONTEXTO ==========
    def obtener_contexto_temporal(self):
        ahora = datetime.now()
        dias = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
        hora = ahora.hour
        
        if 6 <= hora < 12:
            momento = "Mañana"
        elif 12 <= hora < 14:
            momento = "Mediodia"
        elif 14 <= hora < 19:
            momento = "Tarde"
        elif 19 <= hora <= 23:
            momento = "Noche"
        else:
            momento = "Madrugada"
        
        return f"{dias[ahora.weekday()]}_{momento}"
    
    def obtener_estado_hardware(self):
        if not HARDWARE_AWARE:
            return "normal"
        
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            battery = psutil.sensors_battery()
            
            if cpu > 85:
                return "cpu_alta"
            if battery:
                if battery.percent < 15 and not battery.power_plugged:
                    return "bateria_baja"
                if battery.power_plugged:
                    return "cargando"
            return "normal"
        except:
            return "normal"
    
    # ========== APRENDIZAJE ==========
    def procesar_feedback(self, texto):
        """Procesa feedback con castigo global"""
        concepto = self.extraer_concepto(texto)
        
        if concepto == "feedback_negativo" and self.ultima_sugerencia:
            print(f"[PREDICCIONES] Feedback negativo recibido para: {self.ultima_sugerencia}")
            
            # CASTIGO GLOBAL (aplica a todos los contextos)
            t_ctx = self.obtener_contexto_temporal()
            h_ctx = self.obtener_estado_hardware()
            
            # 1. Penalizar contexto temporal
            if self.ultima_sugerencia in self.contexto_hora[t_ctx]:
                self.contexto_hora[t_ctx][self.ultima_sugerencia] *= 0.1  # -90%
            
            # 2. Penalizar contexto hardware
            if self.ultima_sugerencia in self.contexto_hardware[h_ctx]:
                self.contexto_hardware[h_ctx][self.ultima_sugerencia] *= 0.1
            
            # 3. Penalizar transiciones (secuencias)
            if self.ultima_accion and self.ultima_sugerencia in self.transiciones[self.ultima_accion]:
                self.transiciones[self.ultima_accion][self.ultima_sugerencia] *= 0.1
            
            return True
        
        elif concepto == "feedback_positivo" and self.ultima_sugerencia:
            print(f"[PREDICCIONES] Feedback positivo recibido para: {self.ultima_sugerencia}")
            
            # REFUERZO GLOBAL
            t_ctx = self.obtener_contexto_temporal()
            h_ctx = self.obtener_estado_hardware()
            
            # 1. Reforzar contexto temporal
            if self.ultima_sugerencia in self.contexto_hora[t_ctx]:
                self.contexto_hora[t_ctx][self.ultima_sugerencia] *= 1.5  # +50%
            
            # 2. Reforzar contexto hardware
            if self.ultima_sugerencia in self.contexto_hardware[h_ctx]:
                self.contexto_hardware[h_ctx][self.ultima_sugerencia] *= 1.5
            
            # 3. Reforzar transiciones
            if self.ultima_accion and self.ultima_sugerencia in self.transiciones[self.ultima_accion]:
                self.transiciones[self.ultima_accion][self.ultima_sugerencia] *= 1.5
            
            return True
        
        return False
    
    def _aplicar_olvido(self, diccionario):
        """Olvido gradual de asociaciones débiles"""
        claves_a_eliminar = []
        for clave, valor in diccionario.items():
            diccionario[clave] = valor * self.DECAY_RATE
            if diccionario[clave] < 0.05:
                claves_a_eliminar.append(clave)
        
        for clave in claves_a_eliminar:
            del diccionario[clave]
    
    def aprender(self, texto_usuario):
        """Aprende de forma eficiente con guardado periódico"""
        self.contador_acciones += 1
        
        # 1. Procesar feedback primero
        if self.procesar_feedback(texto_usuario):
            # Guardar solo periódicamente después de feedback
            if self.contador_acciones % self.GUARDAR_CADA == 0:
                self.guardar_memoria()
            return
        
        # 2. Extraer concepto
        concepto = self.extraer_concepto(texto_usuario)
        
        # Ignorar feedback como concepto regular
        if concepto in ['feedback_negativo', 'feedback_positivo']:
            return
        
        # 3. Obtener contextos
        contexto_temporal = self.obtener_contexto_temporal()
        contexto_hardware = self.obtener_estado_hardware()
        
        # 4. Aprender asociaciones
        self.contexto_hora[contexto_temporal][concepto] += 1.0
        self.contexto_hardware[contexto_hardware][concepto] += 1.2
        
        # 5. Aprender secuencias
        if self.ultima_accion and self.ultima_accion != concepto:
            self.transiciones[self.ultima_accion][concepto] += 1.5
        
        # 6. Aplicar olvido
        self._aplicar_olvido(self.contexto_hora[contexto_temporal])
        if self.ultima_accion:
            self._aplicar_olvido(self.transiciones[self.ultima_accion])
        
        # 7. Actualizar estado
        self.ultima_accion = concepto
        
        # 8. Guardar periódicamente (no siempre)
        if self.contador_acciones % self.GUARDAR_CADA == 0:
            self.guardar_memoria()
    
    # ========== PREDICCIÓN ==========
    def predecir(self):
        """Predicción inteligente con filtros"""
        scores = Counter()
        
        contexto_temporal = self.obtener_contexto_temporal()
        contexto_hardware = self.obtener_estado_hardware()
        
        # Ponderaciones
        PESO_SECUENCIA = 0.6
        PESO_TEMPORAL = 0.3
        PESO_HARDWARE = 0.1
        
        # 1. Basado en secuencia
        if self.ultima_accion in self.transiciones:
            total = sum(self.transiciones[self.ultima_accion].values()) or 1
            for concepto, peso in self.transiciones[self.ultima_accion].items():
                # Filtrar conceptos no ejecutables
                if concepto in self.comandos_ejecutables and self.comandos_ejecutables[concepto]:
                    scores[concepto] += (peso / total) * PESO_SECUENCIA
        
        # 2. Basado en hora del día
        if contexto_temporal in self.contexto_hora:
            total = sum(self.contexto_hora[contexto_temporal].values()) or 1
            for concepto, peso in self.contexto_hora[contexto_temporal].items():
                if concepto in self.comandos_ejecutables and self.comandos_ejecutables[concepto]:
                    scores[concepto] += (peso / total) * PESO_TEMPORAL
        
        # 3. Basado en hardware
        if contexto_hardware in self.contexto_hardware:
            total = sum(self.contexto_hardware[contexto_hardware].values()) or 1
            for concepto, peso in self.contexto_hardware[contexto_hardware].items():
                if concepto in self.comandos_ejecutables and self.comandos_ejecutables[concepto]:
                    scores[concepto] += (peso / total) * PESO_HARDWARE
        
        if not scores:
            return None, 0.0, False
        
        # Mejor predicción
        mejor_concepto, puntaje = scores.most_common(1)[0]
        
        # Convertir a comando
        comando = self._convertir_a_comando(mejor_concepto)
        
        # Guardar para posible feedback
        self.ultima_sugerencia = mejor_concepto
        
        # ¿Suficiente confianza?
        sugerir_auto = puntaje > self.UMBRAL_CONFIANZA and comando is not None
        
        return comando, puntaje, sugerir_auto
    
    def _convertir_a_comando(self, concepto):
        """Convierte concepto a comando ejecutable"""
        # Si es raw_, verificar si es válido
        if concepto.startswith('raw_'):
            verbo = concepto.replace('raw_', '')
            # Solo permitir verbos que Archeon pueda manejar
            if verbo in ['calcula', 'resume', 'traduce', 'explica']:
                return verbo
            return None
        
        # Conceptos normales
        comando = self.comandos_ejecutables.get(concepto)
        
        # Si es desconocido o feedback, no sugerir
        if not comando or concepto == 'desconocido':
            return None
        
        return comando

# ========== THREAD WORKER ==========
def worker_predicciones(cola_comandos, cola_sugerencias):
    cerebro = CerebroPredictivo()
    print("[PREDICCIONES] Sistema predictivo v3.2 iniciado")
    
    while True:
        try:
            item = cola_comandos.get(timeout=1)
            
            if isinstance(item, tuple):
                cmd, _ = item
            else:
                cmd = item
            
            # Aprender del comando
            cerebro.aprender(cmd)
            
            # Predecir siguiente acción
            prediccion, certeza, es_automatica = cerebro.predecir()
            
            if prediccion:
                etiqueta = "AUTO" if es_automatica else "SUGERENCIA"
                mensaje = f"{etiqueta}|{prediccion}|{int(certeza*100)}"
                cola_sugerencias.put(mensaje)
                
                if es_automatica:
                    print(f">> [SUGERENCIA AUTOMÁTICA] {prediccion} ({int(certeza*100)}% confianza)")
        
        except queue.Empty:
            time.sleep(0.1)  # Espera no bloqueante
        except Exception as e:
            print(f"[PREDICCIONES] Error: {e}")
            time.sleep(1)

def iniciar_hilo_predicciones(cola_comandos, cola_sugerencias):
    t = threading.Thread(
        target=worker_predicciones,
        args=(cola_comandos, cola_sugerencias),
        daemon=True
    )
    t.start()
    return t