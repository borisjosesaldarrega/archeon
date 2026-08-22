import time
from typing import List, Dict, Any

class ContextMemory:
    """
    Memoria de Corto Plazo (RAM Conversacional).
    - Se olvida si pasa X tiempo.
    - Se olvida si se supera el límite de mensajes.
    - NO guarda en base de datos (es efímera).
    """
    def __init__(self, max_messages=15, expiration_seconds=300):
        self.max_messages = max_messages
        self.expiration = expiration_seconds  # 300s = 5 minutos
        self.messages: List[Dict[str, Any]] = []

    def add(self, role: str, message: str, tags: list = None):
        """Agrega un mensaje nuevo y borra los antiguos si se llena."""
        self.messages.append({
            "role": role,        # 'user', 'assistant', 'system'
            "content": message,  # El texto del mensaje
            "tags": tags or [],  # Etiquetas opcionales: ['comando', 'error', etc]
            "timestamp": time.time()
        })

        # Garbage Collector: Si nos pasamos del límite, borramos el más viejo
        if len(self.messages) > self.max_messages:
            self.messages.pop(0)

    def get_recent(self, limit=10) -> List[Dict]:
        """Devuelve los mensajes recientes que NO han expirado (raw data)."""
        now = time.time()
        valid_messages = [
            m for m in self.messages
            if now - m["timestamp"] < self.expiration
        ]
        return valid_messages[-limit:]

    def get_history_for_llm(self) -> List[Dict[str, str]]:
        """
        ⭐ NUEVO: Formatea la memoria para enviarla DIRECTO a la API de IA.
        Limpia timestamps y tags que la IA no necesita para ahorrar tokens.
        """
        clean_history = []
        # Obtenemos todo el historial válido
        for m in self.get_recent(self.max_messages):
            clean_history.append({
                "role": m["role"],
                "content": m["content"]
            })
        return clean_history

    def find_reference(self, keyword: str):
        """Busca si se habló de algo recientemente (ej: 'abre *ese* archivo')."""
        keyword = keyword.lower()
        # Buscamos de atrás hacia adelante (del más reciente al más viejo)
        for m in reversed(self.messages):
            if keyword in m["content"].lower():
                return m
        return None

    def clear_topic(self, keep_last=2):
        """Borrado parcial (cuando cambia el tema drásticamente)."""
        if len(self.messages) > keep_last:
            self.messages = self.messages[-keep_last:]