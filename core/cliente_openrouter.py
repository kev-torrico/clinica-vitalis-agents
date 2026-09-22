"""Cliente HTTP hacia OpenRouter (sección 6 y 11 de ARQUITECTURA.md).

Transporte puro: construye la petición, reintenta ante fallos de red o una
salida que no se puede convertir en el objeto esperado, y devuelve ese
objeto ya parseado. No conoce reglas de negocio clínicas — esas viven en
`agents/agente2_clasificador.py`. Este módulo tampoco recibe nunca datos
identificables: el único payload posible hacia acá es el contrato 4.1
(codigo_paciente + texto_anonimizado, ya anonimizado).
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable, TypeVar

import httpx
from pydantic import ValidationError

import config

logger = logging.getLogger("cliente_openrouter")

T = TypeVar("T")

_TIMEOUT_SEGUNDOS = 30.0
_BACKOFF_BASE_SEGUNDOS = 1.0
# La respuesta esperada es un JSON corto (7 campos clínicos); sin este
# límite algunos proveedores piden por defecto hasta decenas de miles de
# tokens de salida, lo que puede exceder la cuota disponible de la API key.
_MAX_TOKENS_RESPUESTA = 1024


class ErrorClienteOpenRouter(Exception):
    """Error base del cliente OpenRouter."""


class ErrorConfiguracion(ErrorClienteOpenRouter):
    """Falta OPENROUTER_API_KEY u OPENROUTER_MODEL en el entorno."""


class ErrorClasificacionAgotada(ErrorClienteOpenRouter):
    """Se agotaron los reintentos sin obtener una respuesta válida.

    El llamador debe marcar el registro como `error_clasificacion` y
    reportarlo como pendiente — nunca inventar una fila para rellenar
    (sección 6, "Reintentos")."""


def _encabezados() -> dict[str, str]:
    if not config.OPENROUTER_API_KEY:
        raise ErrorConfiguracion("OPENROUTER_API_KEY no está definida en el entorno")
    if not config.OPENROUTER_MODEL:
        raise ErrorConfiguracion("OPENROUTER_MODEL no está definida en el entorno")
    return {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }


def _llamar_chat_completion(mensajes: list[dict[str, str]]) -> dict:
    """Una única llamada HTTP a /chat/completions. Propaga httpx.HTTPError
    ante fallo de red o status >= 400 — la política de reintentos vive en
    `solicitar_json_con_reintentos`, no aquí."""
    cuerpo = {
        "model": config.OPENROUTER_MODEL,
        "messages": mensajes,
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": _MAX_TOKENS_RESPUESTA,
    }
    respuesta = httpx.post(
        f"{config.OPENROUTER_BASE_URL}/chat/completions",
        headers=_encabezados(),
        json=cuerpo,
        timeout=_TIMEOUT_SEGUNDOS,
    )
    respuesta.raise_for_status()
    return respuesta.json()


def _contenido_del_mensaje(respuesta_api: dict) -> str:
    try:
        return respuesta_api["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ErrorClienteOpenRouter(f"Respuesta de OpenRouter con forma inesperada: {error}") from error


_PATRON_BLOQUE_MARKDOWN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _limpiar_bloque_markdown(contenido: str) -> str:
    """Algunos modelos envuelven el JSON en un bloque ```json ... ``` pese a
    pedirles explícitamente que no lo hagan (`response_format=json_object`
    no está garantizado por todos los proveedores detrás de OpenRouter).
    Se quita el envoltorio antes de intentar parsear -- si no hay bloque,
    el contenido se devuelve tal cual."""
    coincidencia = _PATRON_BLOQUE_MARKDOWN.match(contenido.strip())
    return coincidencia.group(1) if coincidencia else contenido.strip()


def solicitar_json_con_reintentos(
    mensajes: list[dict[str, str]],
    *,
    parsear: Callable[[dict], T],
    max_reintentos: int = 2,
) -> T:
    """Llama al modelo y convierte su salida en `T` usando `parsear`.

    Reintenta, con backoff exponencial, ante:
    - error de red / HTTP (httpx.HTTPError),
    - JSON malformado en el contenido del mensaje (json.JSONDecodeError),
    - una salida que no cumple el contrato/regla de negocio esperado por
      `parsear` (pydantic.ValidationError) — por ejemplo, un valor fuera de
      las categorías permitidas o la combinación indeterminado/confianza
      inválida.

    Hasta `max_reintentos` veces (2 por defecto → 3 intentos en total,
    sección 6). Si se agotan, levanta `ErrorClasificacionAgotada`: nunca se
    devuelve una fila inventada para "rellenar".
    """
    ultimo_error: Exception | None = None

    for intento in range(max_reintentos + 1):
        try:
            respuesta_api = _llamar_chat_completion(mensajes)
            contenido = _limpiar_bloque_markdown(_contenido_del_mensaje(respuesta_api))
            datos = json.loads(contenido)
            return parsear(datos)
        except (httpx.HTTPError, json.JSONDecodeError, ValidationError, ErrorClienteOpenRouter) as error:
            ultimo_error = error
            logger.warning(
                "intento %s/%s fallido (%s)", intento + 1, max_reintentos + 1, type(error).__name__
            )
            if intento < max_reintentos:
                time.sleep(_BACKOFF_BASE_SEGUNDOS * (2**intento))
                continue

    raise ErrorClasificacionAgotada(
        f"Se agotaron {max_reintentos + 1} intentos contra OpenRouter"
    ) from ultimo_error
