"""
Clase base abstracta para clientes LLM.

Define la interfaz común que todos los proveedores deben implementar.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """Respuesta estructurada de un LLM."""
    content: str
    model: str
    provider: str
    tokens_used: Optional[int] = None
    finish_reason: Optional[str] = None


class BaseLLMClient(ABC):
    """
    Clase base abstracta para clientes LLM.
    
    Todos los proveedores (Ollama, OpenAI, Anthropic) deben implementar
    esta interfaz para garantizar compatibilidad.
    """
    
    def __init__(
        self,
        model: str,
        timeout: int = 300,
        temperature: float = 0.3,
        **kwargs
    ):
        """
        Inicializa el cliente LLM.
        
        Args:
            model: Nombre del modelo a usar
            timeout: Timeout en segundos para las requests
            temperature: Temperatura para la generación (0.0 - 1.0)
            **kwargs: Argumentos adicionales específicos del provider
        """
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Retorna el nombre del provider (ollama, openai, anthropic)."""
        pass
    
    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Envía un chat request al LLM y retorna la respuesta.
        
        Args:
            system_prompt: Prompt del sistema (instrucciones, contexto)
            user_prompt: Prompt del usuario (la pregunta/tarea)
            
        Returns:
            String con la respuesta del modelo
            
        Raises:
            RuntimeError: Si hay un error en la comunicación con el LLM
        """
        pass
    
    def chat_with_metadata(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """
        Envía un chat request y retorna respuesta con metadata.
        
        Por defecto llama a chat() y envuelve el resultado.
        Los providers pueden override para incluir más metadata.
        
        Args:
            system_prompt: Prompt del sistema
            user_prompt: Prompt del usuario
            
        Returns:
            LLMResponse con el contenido y metadata
        """
        content = self.chat(system_prompt, user_prompt)
        return LLMResponse(
            content=content,
            model=self.model,
            provider=self.provider_name
        )
    
    def health_check(self) -> bool:
        """
        Verifica que el servicio LLM está disponible.
        
        Returns:
            True si el servicio responde, False en caso contrario
        """
        try:
            # Intenta un request mínimo
            self.chat("Responde solo 'OK'", "¿Estás disponible?")
            return True
        except Exception:
            return False
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model='{self.model}', provider='{self.provider_name}')"
