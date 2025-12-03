"""
Cliente LLM para OpenAI API.

Soporta modelos GPT-4, GPT-4o, GPT-3.5-turbo y variantes.
Requiere una API key de OpenAI.

Documentación: https://platform.openai.com/docs/api-reference
"""

import requests
from typing import Optional

from .base import BaseLLMClient, LLMResponse


class OpenAIClient(BaseLLMClient):
    """
    Cliente HTTP para OpenAI API.
    
    Modelos disponibles:
    - gpt-4o, gpt-4o-mini (más recientes y eficientes)
    - gpt-4-turbo, gpt-4 (alta capacidad)
    - gpt-3.5-turbo (más económico)
    
    Precios aproximados (por 1M tokens, entrada/salida):
    - gpt-4o-mini: $0.15 / $0.60
    - gpt-4o: $2.50 / $10.00
    - gpt-4-turbo: $10.00 / $30.00
    """

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 300,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        **kwargs
    ):
        """
        Inicializa el cliente OpenAI.
        
        Args:
            model: Nombre del modelo (gpt-4o-mini, gpt-4o, gpt-4-turbo, gpt-3.5-turbo)
            api_key: API key de OpenAI (requerido)
            base_url: URL base (útil para Azure OpenAI o proxies)
            timeout: Timeout en segundos
            temperature: Temperatura para generación (0.0 - 2.0)
            max_tokens: Máximo de tokens en la respuesta
            
        Raises:
            ValueError: Si no se proporciona api_key
        """
        super().__init__(model=model, timeout=timeout, temperature=temperature)
        
        if not api_key:
            raise ValueError(
                "Se requiere API key de OpenAI. "
                "Configura ANALYZER_API_KEY o usa --api-key"
            )
        
        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip('/')
        self.max_tokens = max_tokens
    
    @property
    def provider_name(self) -> str:
        return "openai"
    
    def _get_headers(self) -> dict:
        """Retorna headers para la API de OpenAI."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Envía un chat request a OpenAI API.
        
        Args:
            system_prompt: Instrucciones del sistema
            user_prompt: Mensaje del usuario
            
        Returns:
            Respuesta del modelo como string
            
        Raises:
            RuntimeError: Si hay error de API, autenticación o límites
        """
        url = f"{self.base_url}/chat/completions"
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout,
            )
            
            # Manejar errores específicos de OpenAI
            if response.status_code == 401:
                raise RuntimeError(
                    "API key de OpenAI inválida o expirada. "
                    "Verifica tu ANALYZER_API_KEY"
                )
            elif response.status_code == 429:
                error_data = response.json().get("error", {})
                raise RuntimeError(
                    f"Límite de rate excedido en OpenAI: {error_data.get('message', 'Rate limit')}"
                )
            elif response.status_code == 400:
                error_data = response.json().get("error", {})
                raise RuntimeError(
                    f"Request inválido a OpenAI: {error_data.get('message', 'Bad request')}"
                )
            
            response.raise_for_status()
            
            data = response.json()
            choices = data.get("choices", [])
            
            if not choices:
                raise RuntimeError("OpenAI no retornó ninguna respuesta")
            
            message = choices[0].get("message", {})
            return message.get("content", "")
            
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"No se pudo conectar a OpenAI API ({self.base_url}). "
                "Verifica tu conexión a internet."
            ) from e
        except requests.exceptions.Timeout as e:
            raise RuntimeError(
                f"Timeout después de {self.timeout} segundos esperando respuesta de OpenAI."
            ) from e
        except requests.exceptions.HTTPError as e:
            try:
                error_data = response.json().get("error", {})
                error_msg = error_data.get("message", response.text)
            except:
                error_msg = response.text
            raise RuntimeError(
                f"Error HTTP {response.status_code} de OpenAI: {error_msg}"
            ) from e
        except RuntimeError:
            raise  # Re-raise nuestros errores
        except Exception as e:
            raise RuntimeError(f"Error inesperado al llamar a OpenAI: {str(e)}") from e

    def chat_with_metadata(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """
        Envía chat request y retorna respuesta con metadata completa.
        
        OpenAI proporciona información detallada de uso de tokens.
        """
        url = f"{self.base_url}/chat/completions"
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("OpenAI no retornó ninguna respuesta")
            
            choice = choices[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            
            # Información de uso
            usage = data.get("usage", {})
            total_tokens = usage.get("total_tokens")
            
            return LLMResponse(
                content=content,
                model=data.get("model", self.model),
                provider=self.provider_name,
                tokens_used=total_tokens,
                finish_reason=choice.get("finish_reason")
            )
            
        except Exception as e:
            # Fallback
            content = self.chat(system_prompt, user_prompt)
            return LLMResponse(
                content=content,
                model=self.model,
                provider=self.provider_name
            )
    
    def list_models(self) -> list:
        """
        Lista los modelos disponibles en la cuenta.
        
        Returns:
            Lista de IDs de modelos
        """
        url = f"{self.base_url}/models"
        
        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            models = data.get("data", [])
            # Filtrar solo modelos GPT
            gpt_models = [
                m.get("id") for m in models 
                if m.get("id", "").startswith(("gpt-", "o1-"))
            ]
            return sorted(gpt_models)
            
        except Exception:
            return []
    
    def health_check(self) -> bool:
        """Verifica que la API key es válida y el servicio responde."""
        try:
            # Intentar listar modelos es más rápido que hacer un chat
            url = f"{self.base_url}/models"
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=10
            )
            return response.status_code == 200
        except Exception:
            return False


class AzureOpenAIClient(OpenAIClient):
    """
    Cliente para Azure OpenAI Service.
    
    Azure OpenAI tiene una estructura de URL diferente y requiere
    deployment names en lugar de model names.
    """
    
    def __init__(
        self,
        deployment_name: str,
        api_key: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        api_version: str = "2024-02-15-preview",
        timeout: int = 300,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        **kwargs
    ):
        """
        Inicializa el cliente Azure OpenAI.
        
        Args:
            deployment_name: Nombre del deployment en Azure
            api_key: API key de Azure OpenAI
            azure_endpoint: Endpoint de Azure (ej: https://myresource.openai.azure.com)
            api_version: Versión de la API
            timeout: Timeout en segundos
            temperature: Temperatura para generación
            max_tokens: Máximo de tokens en la respuesta
        """
        if not azure_endpoint:
            raise ValueError(
                "Se requiere azure_endpoint para Azure OpenAI. "
                "Configura ANALYZER_LLM_URL con tu endpoint de Azure."
            )
        
        # Azure usa el deployment_name como "model" en las requests
        super().__init__(
            model=deployment_name,
            api_key=api_key,
            base_url=azure_endpoint,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        self.deployment_name = deployment_name
        self.api_version = api_version
    
    @property
    def provider_name(self) -> str:
        return "azure_openai"
    
    def _get_headers(self) -> dict:
        """Headers para Azure OpenAI (usa api-key header diferente)."""
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json"
        }
    
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Envía chat request a Azure OpenAI.
        
        La URL de Azure tiene formato diferente incluyendo deployment y api-version.
        """
        url = (
            f"{self.base_url}/openai/deployments/{self.deployment_name}"
            f"/chat/completions?api-version={self.api_version}"
        )
        
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout,
            )
            
            if response.status_code == 401:
                raise RuntimeError(
                    "API key de Azure OpenAI inválida. "
                    "Verifica tu ANALYZER_API_KEY"
                )
            
            response.raise_for_status()
            
            data = response.json()
            choices = data.get("choices", [])
            
            if not choices:
                raise RuntimeError("Azure OpenAI no retornó ninguna respuesta")
            
            message = choices[0].get("message", {})
            return message.get("content", "")
            
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"No se pudo conectar a Azure OpenAI ({self.base_url}). "
                "Verifica tu endpoint y conexión."
            ) from e
        except requests.exceptions.Timeout as e:
            raise RuntimeError(
                f"Timeout después de {self.timeout} segundos esperando respuesta de Azure."
            ) from e
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Error al llamar a Azure OpenAI: {str(e)}") from e
