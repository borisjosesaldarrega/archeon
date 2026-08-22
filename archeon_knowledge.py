# =======================================================================
# ARCHIVO: archeon_knowledge.py v1.0 (MOTOR DE RAZONAMIENTO LÓGICO)
# =======================================================================
import json
import os
import time
from difflib import SequenceMatcher

# Definimos rutas (compatibles con tu sistema de archivos actual)
KNOWLEDGE_DB_PATH = "archeon_knowledge_graph.json"

class KnowledgeCore:
    def __init__(self, main_assistant):
        self.ai = main_assistant
        self.knowledge_base = {
            "hechos": [],  # Ej: {"sujeto": "usuario", "predicado": "pago", "objeto": "efectivo"}
            "reglas": [],  # Ej: {"si": "pago_efectivo", "entonces": "no_tarjeta"}
            "perfil": {}
        }
        self.cargar_conocimiento()

    # =========================================================
    # 💾 PERSISTENCIA
    # =========================================================
    def cargar_conocimiento(self):
        if os.path.exists(KNOWLEDGE_DB_PATH):
            try:
                with open(KNOWLEDGE_DB_PATH, 'r', encoding='utf-8') as f:
                    self.knowledge_base = json.load(f)
                print(f">> [KNOWLEDGE] Base de conocimientos cargada: {len(self.knowledge_base['hechos'])} hechos.")
            except Exception as e:
                print(f"!! Error cargando conocimientos: {e}")
                self._init_db()
        else:
            self._init_db()

    def _init_db(self):
        # Datos semilla iniciales (ejemplos)
        self.knowledge_base["hechos"] = []
        self.guardar_conocimiento()

    def guardar_conocimiento(self):
        try:
            with open(KNOWLEDGE_DB_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.knowledge_base, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"!! Error guardando conocimientos: {e}")

    # =========================================================
    # 🧠 APRENDIZAJE ESTRUCTURADO (EXTRACTION ENGINE)
    # =========================================================
    def aprender(self, texto_usuario):
        """
        Convierte texto natural en hechos estructurados usando la LLM del sistema.
        No guarda el texto, guarda la LÓGICA.
        """
        # 1. Usar la IA existente para extraer la estructura
        prompt_extract = f"""
        [TAREA: ESTRUCTURAR CONOCIMIENTO]
        Analiza el texto y extrae hechos lógicos.
        FORMATO JSON: {{"sujeto": "...", "predicado": "...", "objeto": "..."}}
        
        Ejemplo: "Solo acepto pagos en efectivo" -> {{"sujeto": "usuario", "predicado": "metodo_pago", "objeto": "solo_efectivo"}}
        Ejemplo: "Me llamo Boris" -> {{"sujeto": "usuario", "predicado": "nombre", "objeto": "Boris"}}
        
        TEXTO: "{texto_usuario}"
        Responde SOLO el JSON.
        """
        
        try:
            # Usamos el modelo ya cargado en Archeon
            if hasattr(self.ai, 'model') and self.ai.model:
                response = self.ai.model.generate_content(prompt_extract)
                hecho_str = response.text.replace("```json", "").replace("```", "").strip()
                nuevo_hecho = json.loads(hecho_str)
                
                # 2. VALIDAR CONTRADICCIONES ANTES DE GUARDAR
                conflicto = self._detectar_contradiccion(nuevo_hecho)
                if conflicto:
                    print(f">> [LOGIC] Contradicción detectada con: {conflicto}")
                    # Aquí decidimos: ¿Sobrescribimos o avisamos?
                    # Por defecto, actualizamos el hecho (evolución del conocimiento)
                    self._eliminar_hecho(conflicto)
                
                self.knowledge_base["hechos"].append(nuevo_hecho)
                self.guardar_conocimiento()
                print(f">> [APRENDIZAJE] Hecho guardado: {nuevo_hecho}")
                return True
                
        except Exception as e:
            print(f"!! Error en aprendizaje estructurado: {e}")
        return False

    def _detectar_contradiccion(self, nuevo_hecho):
        """Busca si ya existe un hecho con el mismo sujeto y predicado pero diferente objeto"""
        for hecho in self.knowledge_base["hechos"]:
            if (hecho["sujeto"] == nuevo_hecho["sujeto"] and 
                hecho["predicado"] == nuevo_hecho["predicado"]):
                if hecho["objeto"] != nuevo_hecho["objeto"]:
                    return hecho # Retorna el hecho antiguo conflictivo
        return None

    def _eliminar_hecho(self, hecho_a_borrar):
        if hecho_a_borrar in self.knowledge_base["hechos"]:
            self.knowledge_base["hechos"].remove(hecho_a_borrar)

    # =========================================================
    # 🔍 BUSCADOR SEMÁNTICO (SEARCH ENGINE)
    # =========================================================
    def recuperar_hechos_relevantes(self, query):
        """Recupera hechos relacionados con la consulta actual"""
        relevantes = []
        tokens = query.lower().split()
        
        for hecho in self.knowledge_base["hechos"]:
            # Búsqueda simple por coincidencia de palabras clave en los valores del hecho
            contenido_hecho = f"{hecho['sujeto']} {hecho['predicado']} {hecho['objeto']}".lower()
            
            # Algoritmo de similitud simple (para no usar librerías pesadas en .exe)
            matches = sum(1 for t in tokens if t in contenido_hecho)
            if matches > 0:
                relevantes.append(hecho)
                
        return relevantes

    # =========================================================
    # ⚙️ RAZONADOR (INFERENCE ENGINE)
    # =========================================================
    def razonar(self, query):
        """
        El núcleo del sistema.
        1. Busca hechos.
        2. Aplica lógica.
        3. Genera premisa para la respuesta.
        """
        hechos = self.recuperar_hechos_relevantes(query)
        
        if not hechos:
            return None # No hay base lógica para intervenir
            
        # Construir contexto lógico
        contexto_logico = "DATOS VERIFICADOS:\n"
        for h in hechos:
            contexto_logico += f"- {h['sujeto']} tiene {h['predicado']}: {h['objeto']}\n"
            
        return contexto_logico

    # =========================================================
    # ✅ VALIDADOR (SANITY CHECK)
    # =========================================================
    def validar_respuesta(self, respuesta_candidata, contexto_logico):
        """
        Verifica si la respuesta que la IA iba a dar contradice los hechos.
        Esto se usa como un filtro final.
        """
        if not contexto_logico: return True, ""
        
        prompt_check = f"""
        [AUDITORÍA DE LÓGICA]
        HECHOS REALES:
        {contexto_logico}
        
        RESPUESTA PROPUESTA:
        "{respuesta_candidata}"
        
        TAREA:
        ¿La respuesta contradice los hechos?
        Si NO contradice, responde "OK".
        Si SÍ contradice, responde "CONTRADICCIÓN: [Explica por qué y corrige la respuesta]".
        """
        
        try:
            if hasattr(self.ai, 'model') and self.ai.model:
                validacion = self.ai.model.generate_content(prompt_check).text
                if "CONTRADICCIÓN" in validacion:
                    return False, validacion.replace("CONTRADICCIÓN:", "").strip()
        except:
            pass
            
        return True, ""