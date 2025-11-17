import requests
from typing import Optional


class OllamaClient:
    """Cliente HTTP para Ollama API en localhost:11434"""

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
        timeout: int = 300,
    ):
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Envía un chat request a Ollama API y retorna la respuesta del modelo.
        
        Formato del prompt compatible con Ollama:
        - System prompt como contexto inicial
        - User prompt como mensaje del usuario
        """
        url = f"{self.base_url}/api/generate"
        
        # Construir el prompt completo
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            data = response.json()
            return data.get("response", "")
            
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
            raise RuntimeError(
                f"Error HTTP {response.status_code} al llamar a Ollama: {response.text}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Error inesperado al llamar a Ollama: {str(e)}") from e
