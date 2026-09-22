"""Orquestador end-to-end (sección 13, Fase 4).

Coordina Agente 1 -> Agente 2 -> Agente 3 -> verificación anti-fuga final.

Ningún registro problemático tumba la ejecución completa:
- si falla en el Agente 1 (anti-fuga o fila corrupta), queda
  `requiere_revision_manual` y nunca produce un `PayloadAgente2`;
- si se agotan los reintentos del Agente 2 contra OpenRouter, queda
  `error_clasificacion` y nunca produce una `ClasificacionClinica`.
En ningún caso se inventa una fila para rellenar (sección 6).

Solo el Agente 1 (vía `core.auditoria`) toca el mapa código<->identidad.
El Agente 2 y el Agente 3 nunca reciben esa ruta: los identificadores que
el Agente 3 necesita para su verificación anti-fuga final llegan desde
`agents.agente1_anonimizador.cargar_registros_entrada`, que lee el archivo
de ENTRADA original, no el mapa de auditoría (sección 9).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from agents.agente1_anonimizador import RegistroConError, cargar_registros_entrada, procesar_historias_clinicas
from agents.agente2_clasificador import clasificar_paciente
from agents.agente3_generador_salida import generar_archivo_salida
from core.cliente_openrouter import ErrorClasificacionAgotada
from core.contratos import ClasificacionClinica
from core.verificacion_antifuga import ResultadoAntifuga

logger = logging.getLogger("orquestador")


@dataclass
class ResultadoPipeline:
    clasificaciones: list[ClasificacionClinica] = field(default_factory=list)
    requieren_revision_manual: list[RegistroConError] = field(default_factory=list)
    errores_clasificacion: list[str] = field(default_factory=list)  # codigo_paciente
    verificacion_final: ResultadoAntifuga | None = None
    ruta_salida: Path | None = None


def ejecutar_pipeline(
    ruta_entrada: Path = config.ARCHIVO_ENTRADA,
    ruta_auditoria: Path = config.ARCHIVO_AUDITORIA,
    ruta_salida: Path = config.ARCHIVO_SALIDA,
) -> ResultadoPipeline:
    resultado = ResultadoPipeline()

    # --- Agente 1 ---
    resultado_agente1 = procesar_historias_clinicas(ruta_entrada=ruta_entrada, ruta_auditoria=ruta_auditoria)
    resultado.requieren_revision_manual = resultado_agente1.registros_con_error

    # --- Agente 2 (uno por payload; un fallo puntual no detiene a los demás) ---
    for payload in resultado_agente1.payloads:
        try:
            clasificacion = clasificar_paciente(payload)
        except ErrorClasificacionAgotada:
            logger.error("codigo_paciente=%s: error_clasificacion (reintentos agotados)", payload.codigo_paciente)
            resultado.errores_clasificacion.append(payload.codigo_paciente)
            continue
        resultado.clasificaciones.append(clasificacion)

    # --- Agente 3 + verificación anti-fuga final ---
    # Los identificadores para la verificación final vienen del archivo de
    # ENTRADA original -- nunca del mapa de auditoría (sección 9).
    registros_entrada = cargar_registros_entrada(ruta_entrada)
    resultado.verificacion_final = generar_archivo_salida(
        resultado.clasificaciones, registros_entrada, ruta_destino=ruta_salida
    )
    resultado.ruta_salida = ruta_salida

    return resultado


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    resultado = ejecutar_pipeline()

    print(f"Clasificaciones generadas: {len(resultado.clasificaciones)}")
    print(f"Requieren revisión manual (Agente 1): {len(resultado.requieren_revision_manual)}")
    for error in resultado.requieren_revision_manual:
        print(f"  - {error.codigo_paciente} ({error.id_registro}): {error.motivo}")
    print(f"Error de clasificación (Agente 2): {len(resultado.errores_clasificacion)}")
    for codigo in resultado.errores_clasificacion:
        print(f"  - {codigo}")
    print(f"Verificación anti-fuga final: {'OK' if resultado.verificacion_final.ok else 'FALLÓ'}")
    print(f"Archivo de salida: {resultado.ruta_salida}")
