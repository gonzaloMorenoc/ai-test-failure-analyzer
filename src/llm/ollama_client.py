"""
Cliente LLM para Ollama (modelos locales).

Ollama permite ejecutar modelos LLM localmente sin necesidad de API keys.
Soporta modelos como llama3, mistral, codellama, deepseek, etc.

Documentación: https://ollama.ai/
"""

import requests
from typing import Optional

from .base import BaseLLMClient, LLMResponse


class OllamaClient(BaseLLMClient):
    """
    Cliente HTTP para Ollama API.
    
    Por defecto se conecta a localhost:11434 donde Ollama escucha.
    
    Modelos populares:
    - llama3, llama3.2 (Meta)
    - mistral, mixtral (Mistral AI)
    - codellama (Meta, optimizado para código)
    - deepseek-r1 (DeepSeek)
    - qwen2.5 (Alibaba)
    """

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
        timeout: int = 300,
        temperature: float = 0.3,
        **kwargs
    ):
        """
        Inicializa el cliente Ollama.
        
        Args:
            model: Nombre del modelo (llama3, mistral, etc.)
            base_url: URL base de Ollama (default: http://localhost:11434)
            timeout: Timeout en segundos
            temperature: Temperatura para generación
        """
        super().__init__(model=model, timeout=timeout, temperature=temperature)
        self.base_url = base_url.rstrip('/')
    
    @property
    def provider_name(self) -> str:
        return "ollama"

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Envía un chat request a Ollama API y retorna la respuesta del modelo.
        
        Args:
            system_prompt: Instrucciones del sistema
            user_prompt: Mensaje del usuario
            
        Returns:
            Respuesta del modelo como string
            
        Raises:
            RuntimeError: Si hay error de conexión, timeout o HTTP
        """
        url = f"{self.base_url}/api/chat"
        
        # Usar el endpoint /api/chat con mensajes estructurados
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature
            }
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            data = response.json()
            
            # El endpoint /api/chat retorna la respuesta en message.content
            message = data.get("message", {})
            return message.get("content", "")
            
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"No se pudo conectar a Ollama en {self.base_url}. "
                "Asegúrate de que Ollama está corriendo (ejecuta: ollama serve)"
            ) from e
        except requests.exceptions.Timeout as e:
            raise RuntimeError(
                f"Timeout después de {self.timeout} segundos esperando respuesta de Ollama."
            ) from e
        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_data = response.json()
                error_detail = error_data.get("error", response.text)
            except:
                error_detail = response.text
            raise RuntimeError(
                f"Error HTTP {response.status_code} de Ollama: {error_detail}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Error inesperado al llamar a Ollama: {str(e)}") from e

    def chat_with_metadata(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """
        Envía chat request y retorna respuesta con metadata.
        
        Ollama proporciona información adicional como tokens y tiempos.
        """
        url = f"{self.base_url}/api/chat"
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature
            }
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            message = data.get("message", {})
            content = message.get("content", "")
            
            # Ollama incluye eval_count (tokens generados)
            tokens = data.get("eval_count")
            
            return LLMResponse(
                content=content,
                model=self.model,
                provider=self.provider_name,
                tokens_used=tokens,
                finish_reason=data.get("done_reason")
            )
            
        except Exception as e:
            # Fallback al método base
            content = self.chat(system_prompt, user_prompt)
            return LLMResponse(
                content=content,
                model=self.model,
                provider=self.provider_name
            )
    
    def list_models(self) -> list:
        """
        Lista los modelos disponibles en Ollama.
        
        Returns:
            Lista de nombres de modelos instalados
        """
        url = f"{self.base_url}/api/tags"
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            models = data.get("models", [])
            return [m.get("name", "") for m in models]
            
        except Exception:
            return []
    
    def health_check(self) -> bool:
        """Verifica que Ollama está corriendo y el modelo está disponible."""
        try:
            # Verificar que Ollama responde
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code != 200:
                return False
            
            # Verificar que el modelo existe
            models = self.list_models()
            # Los modelos pueden tener tags como "llama3:latest"
            model_base = self.model.split(":")[0]
            return any(model_base in m for m in models)
            
        except Exception:
            return False
