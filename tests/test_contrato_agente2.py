"""Fase 0 — gate: los esquemas de contratos excluyen identificadores por
estructura (extra='forbid'), no por convención.

Fase 2 añadirá aquí la prueba sobre el payload real serializado hacia la
llamada al LLM (sección 10.2: "el payload real ... contiene exactamente
las claves codigo_paciente y texto_anonimizado").
"""
import pytest
from pydantic import ValidationError

from core.contratos import ClasificacionClinica, PayloadAgente2


def test_payload_agente2_acepta_solo_las_dos_claves_del_contrato():
    payload = PayloadAgente2(codigo_paciente="PAC-001", texto_anonimizado="texto sin identificadores")
    assert payload.model_dump() == {
        "codigo_paciente": "PAC-001",
        "texto_anonimizado": "texto sin identificadores",
    }


@pytest.mark.parametrize(
    "campo_extra",
    ["nombre_completo", "cedula", "direccion", "telefono", "cualquier_otro_campo"],
)
def test_payload_agente2_rechaza_cualquier_campo_fuera_del_contrato(campo_extra):
    with pytest.raises(ValidationError):
        PayloadAgente2(
            codigo_paciente="PAC-001",
            texto_anonimizado="texto sin identificadores",
            **{campo_extra: "valor que no debería poder colarse"},
        )


@pytest.mark.parametrize("codigo_invalido", ["PAC-1", "paciente-001", "PAC-0001", "001"])
def test_payload_agente2_exige_formato_pac_nnn(codigo_invalido):
    with pytest.raises(ValidationError):
        PayloadAgente2(codigo_paciente=codigo_invalido, texto_anonimizado="texto")


def _clasificacion_base(**overrides):
    base = dict(
        codigo_paciente="PAC-001",
        enfermedad_probable="diabetes tipo 2",
        nivel_riesgo="medio",
        comportamiento_observado="fatiga persistente y sed excesiva",
        confianza="alta",
        antecedentes="antecedente familiar de diabetes tipo 2",
        fuma="No",
        consumo_sustancias="No registrado",
    )
    base.update(overrides)
    return base


def test_clasificacion_clinica_acepta_instancia_valida():
    clasificacion = ClasificacionClinica(**_clasificacion_base())
    assert clasificacion.codigo_paciente == "PAC-001"


def test_clasificacion_clinica_rechaza_campos_fuera_del_contrato():
    with pytest.raises(ValidationError):
        ClasificacionClinica(**_clasificacion_base(nombre_completo="Marcela Suárez Rincón"))


@pytest.mark.parametrize(
    "campo,valor_invalido",
    [
        ("nivel_riesgo", "critico"),
        ("confianza", "muy_alta"),
        ("fuma", "tal_vez"),
        ("consumo_sustancias", "desconocido"),
    ],
)
def test_clasificacion_clinica_rechaza_valores_fuera_de_las_categorias_permitidas(campo, valor_invalido):
    with pytest.raises(ValidationError):
        ClasificacionClinica(**_clasificacion_base(**{campo: valor_invalido}))


def test_indeterminado_exige_confianza_baja():
    with pytest.raises(ValidationError):
        ClasificacionClinica(
            **_clasificacion_base(
                enfermedad_probable="indeterminado",
                confianza="alta",
            )
        )


def test_indeterminado_con_confianza_baja_es_valido():
    clasificacion = ClasificacionClinica(
        **_clasificacion_base(
            enfermedad_probable="indeterminado",
            confianza="baja",
            comportamiento_observado="evidencia insuficiente para un diagnóstico razonable",
        )
    )
    assert clasificacion.enfermedad_probable == "indeterminado"
    assert clasificacion.confianza == "baja"
