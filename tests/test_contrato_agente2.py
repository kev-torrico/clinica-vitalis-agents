"""Fase 0 — gate: los esquemas de contratos excluyen identificadores por
estructura (extra='forbid'), no por convención.

Fase 2 añade aquí la prueba sobre el payload real serializado hacia la
llamada al LLM (sección 10.2: "el payload real ... contiene exactamente
las claves codigo_paciente y texto_anonimizado") y sobre el rechazo
programático de cualquier objeto que no sea un PayloadAgente2 (sección 6).
"""
import json

import pytest
from pydantic import ValidationError

import core.cliente_openrouter as cliente_openrouter
from agents.agente2_clasificador import clasificar_paciente
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


# --- Fase 2: payload real enviado al LLM y rechazo de objetos ajenos al contrato ---


def _respuesta_openrouter_valida(**overrides) -> dict:
    campos = dict(
        enfermedad_probable="diabetes tipo 2",
        nivel_riesgo="medio",
        comportamiento_observado="fatiga persistente y sed excesiva",
        confianza="alta",
        antecedentes="antecedente familiar de diabetes tipo 2",
        fuma="No",
        consumo_sustancias="No registrado",
    )
    campos.update(overrides)
    return {"choices": [{"message": {"content": json.dumps(campos, ensure_ascii=False)}}]}


def test_payload_real_enviado_al_llm_contiene_exactamente_las_2_claves(monkeypatch):
    """Sección 10.2: 'el payload real que se serializa hacia la llamada al
    LLM contiene exactamente las claves codigo_paciente y texto_anonimizado
    — cualquier clave adicional falla la prueba'."""
    mensajes_capturados: list[dict] = []

    def _llamada_falsa(mensajes):
        mensajes_capturados.extend(mensajes)
        return _respuesta_openrouter_valida()

    monkeypatch.setattr(cliente_openrouter, "_llamar_chat_completion", _llamada_falsa)

    payload = PayloadAgente2(codigo_paciente="PAC-001", texto_anonimizado="Paciente [ANON], 54 años.")
    clasificar_paciente(payload)

    mensaje_usuario = next(m for m in mensajes_capturados if m["role"] == "user")
    payload_enviado = json.loads(mensaje_usuario["content"])

    assert set(payload_enviado.keys()) == {"codigo_paciente", "texto_anonimizado"}
    assert payload_enviado["codigo_paciente"] == "PAC-001"


@pytest.mark.parametrize(
    "objeto_invalido",
    [
        {"codigo_paciente": "PAC-001", "texto_anonimizado": "texto"},
        "PAC-001",
        None,
    ],
)
def test_clasificar_paciente_rechaza_cualquier_objeto_que_no_sea_payloadagente2(objeto_invalido, monkeypatch):
    """Sección 6: 'el código que invoca este agente debe rechazar
    programáticamente cualquier intento de pasarle un objeto con más
    campos' — incluye rechazar directamente cualquier tipo que no sea el
    contrato, no solo objetos con campos de más."""

    def _llamada_que_no_deberia_ejecutarse(mensajes):
        raise AssertionError("no debería llamarse a OpenRouter con un payload inválido")

    monkeypatch.setattr(cliente_openrouter, "_llamar_chat_completion", _llamada_que_no_deberia_ejecutarse)

    with pytest.raises(TypeError):
        clasificar_paciente(objeto_invalido)


def test_clasificar_paciente_devuelve_clasificacion_valida_en_camino_feliz(monkeypatch):
    monkeypatch.setattr(
        cliente_openrouter, "_llamar_chat_completion", lambda mensajes: _respuesta_openrouter_valida()
    )

    payload = PayloadAgente2(codigo_paciente="PAC-001", texto_anonimizado="Paciente [ANON], 54 años.")
    clasificacion = clasificar_paciente(payload)

    assert isinstance(clasificacion, ClasificacionClinica)
    assert clasificacion.codigo_paciente == "PAC-001"
    assert clasificacion.enfermedad_probable == "diabetes tipo 2"


def test_clasificar_paciente_ignora_codigo_paciente_inventado_por_el_modelo(monkeypatch):
    """Si el LLM emite su propio 'codigo_paciente' (no se le pide en el
    prompt, pero un modelo podría alucinarlo), el sistema debe usar el
    código real del payload, nunca el que 'recuerde' el modelo."""
    monkeypatch.setattr(
        cliente_openrouter,
        "_llamar_chat_completion",
        lambda mensajes: _respuesta_openrouter_valida(codigo_paciente="PAC-999"),
    )

    payload = PayloadAgente2(codigo_paciente="PAC-001", texto_anonimizado="Paciente [ANON], 54 años.")
    clasificacion = clasificar_paciente(payload)

    assert clasificacion.codigo_paciente == "PAC-001"
