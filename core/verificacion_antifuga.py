"""Verificación anti-fuga de dos capas (sección 5, punto 4 y sección 8).

Deliberadamente independiente de `core.reglas_anonimizacion`: no reutiliza la
misma construcción de tokens ni el mismo mecanismo de sustitución, para que
un bug en la lógica de reemplazo no pueda "aprobarse a sí mismo". Esta capa
no decide qué dato es seguro copiar — es infraestructura determinística que
solo confirma, de una forma distinta, que no quedó ningún residuo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from core.contratos import RegistroHistoriaClinica

LONGITUD_MINIMA_COMPONENTE_SUELTO = 3


def _normalizar(cadena: str) -> str:
    """Minúsculas, sin tildes, puntuación colapsada a espacio — usado por la
    capa 2 para detectar variantes de puntuación/mayúsculas. Preserva los
    espacios entre palabras (en vez de eliminarlos) para poder exigir luego
    coincidencia por palabra completa y no un substring cruzando palabras."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", cadena) if not unicodedata.combining(c)
    )
    con_espacios = re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower())
    return re.sub(r"\s+", " ", con_espacios).strip()


def _aparece_como_palabra(cadena_normalizada: str, texto_normalizado: str) -> bool:
    if not cadena_normalizada:
        return False
    patron = r"(?<!\w)" + re.escape(cadena_normalizada) + r"(?!\w)"
    return re.search(patron, texto_normalizado) is not None


@dataclass
class ResultadoAntifuga:
    ok: bool
    categorias_filtradas: list[str] = field(default_factory=list)


def _cadenas_por_categoria(fila: RegistroHistoriaClinica) -> dict[str, set[str]]:
    return {
        "nombre": {fila.nombre_completo},
        "cedula": {fila.cedula, fila.cedula.replace(".", "")},
        "direccion": {fila.direccion, fila.direccion.split(",")[0].strip()},
        "telefono": {fila.telefono, fila.telefono.replace("-", "")},
    }


def _componentes_nombre_sueltos(fila: RegistroHistoriaClinica) -> set[str]:
    return {p for p in fila.nombre_completo.split() if len(p) >= LONGITUD_MINIMA_COMPONENTE_SUELTO}


def verificar_texto_anonimizado(fila: RegistroHistoriaClinica, texto_anonimizado: str) -> ResultadoAntifuga:
    """Capa 1 (cadenas exactas) + capa 2 (variantes normalizadas y
    componentes de nombre sueltos). Cualquier residuo detectado por
    cualquiera de las dos capas hace fallar la verificación."""
    categorias_filtradas: list[str] = []
    cadenas_por_categoria = _cadenas_por_categoria(fila)

    # Capa 1: cadenas exactas (tal como están en el registro, con y sin
    # formato) no deben sobrevivir textualmente.
    for categoria, cadenas in cadenas_por_categoria.items():
        if any(cadena and cadena in texto_anonimizado for cadena in cadenas):
            categorias_filtradas.append(categoria)

    # Capa 2: mismas cadenas, comparadas normalizadas (sin tildes, sin
    # puntuación, insensible a mayúsculas), más componentes individuales del
    # nombre que puedan haber quedado sueltos.
    texto_normalizado = _normalizar(texto_anonimizado)

    for categoria, cadenas in cadenas_por_categoria.items():
        if categoria in categorias_filtradas:
            continue
        if any(_aparece_como_palabra(_normalizar(c), texto_normalizado) for c in cadenas):
            categorias_filtradas.append(categoria)

    if "nombre" not in categorias_filtradas:
        componentes = _componentes_nombre_sueltos(fila)
        if any(_aparece_como_palabra(_normalizar(c), texto_normalizado) for c in componentes):
            categorias_filtradas.append("nombre_componente")

    return ResultadoAntifuga(ok=not categorias_filtradas, categorias_filtradas=categorias_filtradas)
