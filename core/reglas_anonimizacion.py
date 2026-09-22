"""Generación de tokens identificadores y sustitución por [ANON] (sección 5).

Determinístico, sin red externa, sin LLM: es el control de seguridad
principal del sistema — el único paso que toca los 4 identificadores en
crudo debe ser el más simple y más fácil de auditar de todo el pipeline.
"""
from __future__ import annotations

import re

from core.contratos import RegistroHistoriaClinica

MARCADOR = "[ANON]"
LONGITUD_MINIMA_COMPONENTE = 3


def _componentes_nombre(nombre_completo: str) -> list[str]:
    return [parte for parte in nombre_completo.split() if len(parte) >= LONGITUD_MINIMA_COMPONENTE]


def _variantes_cedula(cedula: str) -> set[str]:
    return {cedula, cedula.replace(".", "")}


def _variantes_telefono(telefono: str) -> set[str]:
    return {telefono, telefono.replace("-", "")}


def _variantes_direccion(direccion: str) -> set[str]:
    """Dirección completa y el fragmento reconocible (número de
    carrera/calle + complemento) que precede a la ciudad — la parte que de
    verdad ubica a una persona concreta."""
    variantes = {direccion}
    fragmento = direccion.split(",")[0].strip()
    if fragmento:
        variantes.add(fragmento)
    return variantes


def generar_tokens(fila: RegistroHistoriaClinica) -> list[str]:
    """Construye, a partir de las columnas estructuradas de la fila, la lista
    de cadenas a eliminar del texto libre. Nunca inventados: siempre
    derivados del propio registro.

    Se ordenan de más larga a más corta para que una aparición completa de
    un identificador (ej. el nombre completo) se sustituya como un único
    [ANON], y solo se generen [ANON] adicionales para fragmentos sueltos que
    aparezcan aparte (sección 5, punto 2)."""
    tokens: set[str] = set()

    tokens.add(fila.nombre_completo)
    tokens.update(_componentes_nombre(fila.nombre_completo))
    tokens.update(_variantes_cedula(fila.cedula))
    tokens.update(_variantes_direccion(fila.direccion))
    tokens.update(_variantes_telefono(fila.telefono))

    return sorted((t for t in tokens if t), key=len, reverse=True)


def anonimizar_texto(texto: str, tokens: list[str]) -> str:
    """Reemplaza cada ocurrencia de cada token por [ANON] — nunca por el
    codigo_paciente (sección 5, punto 3: el código identifica la fila en el
    sistema, no es parte de la narrativa clínica)."""
    resultado = texto
    for token in tokens:
        patron = re.compile(re.escape(token), flags=re.IGNORECASE)
        resultado = patron.sub(MARCADOR, resultado)
    return resultado
