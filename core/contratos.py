"""Modelos pydantic de los contratos de datos entre agentes (sección 4 de ARQUITECTURA.md).

Cada contrato usa `extra="forbid"`: cualquier campo fuera del esquema hace que
la validación falle en tiempo de ejecución. La exclusión de identificadores
(nombre, cédula, dirección, teléfono) entre el Agente 1 y el Agente 2 es
estructural — no depende de que el código "recuerde" no incluirlos.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CODIGO_PACIENTE_PATTERN = r"^PAC-\d{3}$"

NivelRiesgo = Literal["bajo", "medio", "alto"]
Confianza = Literal["alta", "media", "baja"]
RespuestaSiNo = Literal["Sí", "No", "No registrado"]


class PayloadAgente2(BaseModel):
    """Contrato 4.1 — salida del Agente 1 / única entrada permitida al Agente 2.

    Exactamente estas dos claves. Ninguna otra puede cruzar hacia el
    clasificador: ni identificadores, ni el registro original, "por si acaso".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    codigo_paciente: str = Field(pattern=CODIGO_PACIENTE_PATTERN)
    texto_anonimizado: str


class ClasificacionClinica(BaseModel):
    """Contrato 4.2 — salida del Agente 2 / entrada del Agente 3."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codigo_paciente: str = Field(pattern=CODIGO_PACIENTE_PATTERN)
    enfermedad_probable: str
    nivel_riesgo: NivelRiesgo
    comportamiento_observado: str
    confianza: Confianza
    antecedentes: str
    fuma: RespuestaSiNo
    consumo_sustancias: RespuestaSiNo

    @model_validator(mode="after")
    def _indeterminado_exige_confianza_baja(self) -> "ClasificacionClinica":
        """Regla de negocio explícita (sección 4.2): 'indeterminado' nunca es
        un fallback silencioso — si se usa, la confianza declarada debe ser baja."""
        if self.enfermedad_probable.strip().lower() == "indeterminado" and self.confianza != "baja":
            raise ValueError(
                "enfermedad_probable='indeterminado' exige confianza='baja' "
                "(regla de negocio, sección 4.2 de ARQUITECTURA.md)"
            )
        return self


# Encabezados y orden exactos del archivo de referencia (contrato 4.3).
# El Agente 3 escribe estas columnas, en este orden, a partir de los campos
# de ClasificacionClinica (nótese el acento en "código_paciente": es el
# encabezado de la hoja de salida, no el nombre del campo del contrato 4.2).
ENCABEZADOS_SALIDA = [
    "código_paciente",
    "enfermedad_probable",
    "nivel_riesgo",
    "comportamiento_observado",
    "confianza",
    "antecedentes",
    "fuma",
    "consumo_sustancias",
]


class RegistroHistoriaClinica(BaseModel):
    """Fila cruda de la hoja `Historias_Clinicas_Entrada` (no es uno de los 3
    contratos anti-fuga de la sección 4 — es el modelo de entrada que usa el
    Agente 1, internamente, antes de anonimizar).

    Vive en el mismo archivo por conveniencia de importación, pero conserva
    los 4 identificadores: solo el Agente 1 y `core.auditoria` deben manejar
    instancias de esta clase.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id_registro: str
    nombre_completo: str
    cedula: str
    direccion: str
    telefono: str
    fecha_consulta: str
    nota_clinica: str
