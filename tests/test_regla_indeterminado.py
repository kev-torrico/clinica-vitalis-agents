"""Fase 2 — gate: la regla de negocio 'indeterminado + confianza baja' se
cumple de punta a punta, y los reintentos (sección 6) se comportan como
especifica ARQUITECTURA.md: máximo 2 reintentos ante error de red o JSON
malformado, con backoff, y al tercer fallo se marca error_clasificacion (se
propaga `ErrorClasificacionAgotada`), nunca se inventa una fila.
"""
from __future__ import annotations

import json
import os

import httpx
import pytest

import config
import core.cliente_openrouter as cliente_openrouter
from agents.agente1_anonimizador import procesar_historias_clinicas
from agents.agente2_clasificador import clasificar_paciente
from core.cliente_openrouter import ErrorClasificacionAgotada
from core.contratos import PayloadAgente2


@pytest.fixture(autouse=True)
def _sin_espera_real(monkeypatch):
    """Los reintentos usan backoff exponencial real (sección 6) — en las
    pruebas no queremos que eso haga lenta la suite."""
    monkeypatch.setattr(cliente_openrouter.time, "sleep", lambda segundos: None)


def _respuesta_openrouter(**campos) -> dict:
    return {"choices": [{"message": {"content": json.dumps(campos, ensure_ascii=False)}}]}


_PAYLOAD_DEMO = PayloadAgente2(
    codigo_paciente="PAC-003",
    texto_anonimizado="Paciente [ANON], 27 años. Refiere insomnio y tristeza persistente.",
)


def test_indeterminado_con_confianza_baja_se_acepta(monkeypatch):
    respuesta_valida = _respuesta_openrouter(
        enfermedad_probable="indeterminado",
        nivel_riesgo="bajo",
        comportamiento_observado="Síntomas depresivos leves, sin criterios suficientes para un diagnóstico específico.",
        confianza="baja",
        antecedentes="ninguno registrado",
        fuma="No",
        consumo_sustancias="No",
    )

    monkeypatch.setattr(cliente_openrouter, "_llamar_chat_completion", lambda mensajes: respuesta_valida)

    clasificacion = clasificar_paciente(_PAYLOAD_DEMO)

    assert clasificacion.enfermedad_probable == "indeterminado"
    assert clasificacion.confianza == "baja"


def test_indeterminado_con_confianza_alta_nunca_se_acepta_y_se_reintenta(monkeypatch):
    """Una respuesta que viola la regla de negocio (indeterminado + no-baja)
    es tratada como salida inválida: dispara reintento, igual que un JSON
    malformado. Si el modelo insiste en la combinación inválida en los 3
    intentos, el sistema se rinde -- nunca la deja pasar."""
    llamadas = {"conteo": 0}

    def _siempre_invalida(mensajes):
        llamadas["conteo"] += 1
        return _respuesta_openrouter(
            enfermedad_probable="indeterminado",
            nivel_riesgo="bajo",
            comportamiento_observado="texto",
            confianza="alta",  # inválido junto con 'indeterminado'
            antecedentes="ninguno registrado",
            fuma="No",
            consumo_sustancias="No",
        )

    monkeypatch.setattr(cliente_openrouter, "_llamar_chat_completion", _siempre_invalida)

    with pytest.raises(ErrorClasificacionAgotada):
        clasificar_paciente(_PAYLOAD_DEMO)

    assert llamadas["conteo"] == 3  # intento inicial + 2 reintentos (sección 6)


def test_se_recupera_tras_json_malformado_en_el_primer_intento(monkeypatch):
    llamadas = {"conteo": 0}

    def _primera_mal_luego_bien(mensajes):
        llamadas["conteo"] += 1
        if llamadas["conteo"] == 1:
            return {"choices": [{"message": {"content": "esto no es JSON"}}]}
        return _respuesta_openrouter(
            enfermedad_probable="migraña",
            nivel_riesgo="bajo",
            comportamiento_observado="cefalea pulsátil recurrente",
            confianza="alta",
            antecedentes="antecedente de migraña en la madre",
            fuma="No",
            consumo_sustancias="Sí",
        )

    monkeypatch.setattr(cliente_openrouter, "_llamar_chat_completion", _primera_mal_luego_bien)

    clasificacion = clasificar_paciente(_PAYLOAD_DEMO)

    assert llamadas["conteo"] == 2
    assert clasificacion.enfermedad_probable == "migraña"


def test_fallo_de_red_agota_reintentos_y_nunca_inventa_una_fila(monkeypatch):
    llamadas = {"conteo": 0}

    def _siempre_falla_red(mensajes):
        llamadas["conteo"] += 1
        raise httpx.ConnectError("simulación de caída de red", request=httpx.Request("POST", "https://openrouter.ai"))

    monkeypatch.setattr(cliente_openrouter, "_llamar_chat_completion", _siempre_falla_red)

    with pytest.raises(ErrorClasificacionAgotada):
        clasificar_paciente(_PAYLOAD_DEMO)

    assert llamadas["conteo"] == 3


# --- Gate de Fase 2 (sección 13): los 5 casos de referencia deben salir
# como 'indeterminado' contra el modelo real. Es una llamada real a
# OpenRouter (gasta cuota) -- deliberadamente NO se ejecuta en un `pytest`
# normal. Actívala con VITALIS_RUN_INTEGRACION_OPENROUTER=1 cuando quieras
# validar el modelo elegido contra el oráculo de la sección 10.1.

_EJECUTAR_INTEGRACION = os.environ.get("VITALIS_RUN_INTEGRACION_OPENROUTER") == "1"
_CODIGOS_INDETERMINADOS_ESPERADOS = {"PAC-003", "PAC-004", "PAC-008", "PAC-010", "PAC-012"}


@pytest.mark.skipif(
    not _EJECUTAR_INTEGRACION,
    reason=(
        "Integración real contra OpenRouter (gasta cuota de API). "
        "Actívala con VITALIS_RUN_INTEGRACION_OPENROUTER=1 y OPENROUTER_API_KEY/OPENROUTER_MODEL configurados."
    ),
)
def test_los_5_casos_de_referencia_salen_indeterminado_contra_el_modelo_real():
    resultado_agente1 = procesar_historias_clinicas(ruta_auditoria=config.DATA_INTERNAL_DIR / "_integracion.xlsx")
    payloads_de_interes = [
        p for p in resultado_agente1.payloads if p.codigo_paciente in _CODIGOS_INDETERMINADOS_ESPERADOS
    ]
    assert len(payloads_de_interes) == 5

    for payload in payloads_de_interes:
        clasificacion = clasificar_paciente(payload)
        assert clasificacion.enfermedad_probable == "indeterminado", (
            f"{payload.codigo_paciente} debía salir 'indeterminado' según el oráculo de la sección 10.1"
        )
        assert clasificacion.confianza == "baja"
