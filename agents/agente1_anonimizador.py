"""Agente 1 — Anonimizador (sección 5 de ARQUITECTURA.md).

Determinístico, sin llamadas a red externa, sin LLM. Es el único punto del
pipeline que toca los 4 identificadores (nombre, cédula, dirección,
teléfono) en crudo — por eso es también el más simple y auditable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

import config
from core.auditoria import guardar_historias_con_codigo
from core.contratos import PayloadAgente2, RegistroHistoriaClinica
from core.reglas_anonimizacion import anonimizar_texto, generar_tokens
from core.verificacion_antifuga import verificar_texto_anonimizado

logger = logging.getLogger("agente1_anonimizador")

# Mapea encabezado real de la hoja -> nombre de campo de RegistroHistoriaClinica.
_COLUMNAS = {
    "ID_Registro": "id_registro",
    "Nombre completo": "nombre_completo",
    "Cédula": "cedula",
    "Dirección": "direccion",
    "Teléfono": "telefono",
    "Fecha de consulta": "fecha_consulta",
    "Nota clínica (texto libre)": "nota_clinica",
}


@dataclass
class RegistroConError:
    """Registro que no avanzó al Agente 2. `motivo` es para logs/depuración
    interna — nunca contiene el dato identificador en sí, solo la categoría
    de fuga o el tipo de fallo estructural."""

    id_registro: str
    codigo_paciente: str
    motivo: str


@dataclass
class ResultadoAgente1:
    payloads: list[PayloadAgente2] = field(default_factory=list)
    registros_con_error: list[RegistroConError] = field(default_factory=list)


def _leer_filas_crudas(ruta_entrada: Path) -> list[dict[str, object]]:
    wb = openpyxl.load_workbook(ruta_entrada, data_only=True)
    ws = wb[config.HOJA_ENTRADA]
    filas = list(ws.iter_rows(min_row=1, values_only=True))
    if not filas:
        return []

    encabezados = filas[0]
    indices = {nombre: idx for idx, nombre in enumerate(encabezados) if nombre is not None}

    faltantes = set(_COLUMNAS) - set(indices)
    if faltantes:
        raise ValueError(f"Faltan columnas esperadas en '{config.HOJA_ENTRADA}': {sorted(faltantes)}")

    crudas = []
    for fila in filas[1:]:
        if fila[indices["ID_Registro"]] is None:
            continue
        crudas.append({col: fila[indices[col]] for col in _COLUMNAS})
    return crudas


def _a_texto(valor: object) -> str:
    return "" if valor is None else str(valor).strip()


def _generar_codigo_paciente(posicion: int) -> str:
    return f"PAC-{posicion:03d}"


def procesar_historias_clinicas(
    ruta_entrada: Path = config.ARCHIVO_ENTRADA,
    ruta_auditoria: Path = config.ARCHIVO_AUDITORIA,
) -> ResultadoAgente1:
    """Procesa `Historias_Clinicas_Entrada` de punta a punta:
    1. asigna codigo_paciente correlativo en orden de ID_Registro,
    2. anonimiza cada nota clínica,
    3. corre la verificación anti-fuga de dos capas,
    4. escribe el archivo interno de trazabilidad (código <-> identidad).

    Un registro que falla en cualquier paso queda marcado
    `requiere_revision_manual` (en `resultado.registros_con_error`) y nunca
    produce un `PayloadAgente2` — el pipeline no se detiene por completo,
    pero ese registro puntual no avanza (sección 5, punto 4).
    """
    resultado = ResultadoAgente1()
    filas_para_auditoria: list[tuple[RegistroHistoriaClinica, str]] = []

    crudas = _leer_filas_crudas(ruta_entrada)

    for posicion, cruda in enumerate(crudas, start=1):
        codigo_paciente = _generar_codigo_paciente(posicion)
        id_registro = _a_texto(cruda["ID_Registro"]) or f"fila-{posicion}"

        try:
            registro = RegistroHistoriaClinica(
                id_registro=id_registro,
                nombre_completo=_a_texto(cruda["Nombre completo"]),
                cedula=_a_texto(cruda["Cédula"]),
                direccion=_a_texto(cruda["Dirección"]),
                telefono=_a_texto(cruda["Teléfono"]),
                fecha_consulta=_a_texto(cruda["Fecha de consulta"]),
                nota_clinica=_a_texto(cruda["Nota clínica (texto libre)"]),
            )
        except Exception:
            logger.error("codigo_paciente=%s: fila cruda inválida -> requiere_revision_manual", codigo_paciente)
            resultado.registros_con_error.append(
                RegistroConError(id_registro=id_registro, codigo_paciente=codigo_paciente, motivo="fila_invalida")
            )
            continue

        filas_para_auditoria.append((registro, codigo_paciente))

        if not registro.nota_clinica:
            logger.error("codigo_paciente=%s: nota clínica vacía -> requiere_revision_manual", codigo_paciente)
            resultado.registros_con_error.append(
                RegistroConError(id_registro=id_registro, codigo_paciente=codigo_paciente, motivo="nota_vacia")
            )
            continue

        tokens = generar_tokens(registro)
        texto_anonimizado = anonimizar_texto(registro.nota_clinica, tokens)

        verificacion = verificar_texto_anonimizado(registro, texto_anonimizado)
        if not verificacion.ok:
            logger.error(
                "codigo_paciente=%s: residuo anti-fuga en categorías=%s -> requiere_revision_manual",
                codigo_paciente,
                verificacion.categorias_filtradas,
            )
            resultado.registros_con_error.append(
                RegistroConError(
                    id_registro=id_registro,
                    codigo_paciente=codigo_paciente,
                    motivo=f"residuo:{','.join(verificacion.categorias_filtradas)}",
                )
            )
            continue

        resultado.payloads.append(
            PayloadAgente2(codigo_paciente=codigo_paciente, texto_anonimizado=texto_anonimizado)
        )

    guardar_historias_con_codigo(filas_para_auditoria, ruta_auditoria)

    return resultado


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    resultado = procesar_historias_clinicas()
    print(f"Payloads generados: {len(resultado.payloads)}")
    print(f"Registros con error: {len(resultado.registros_con_error)}")
    for error in resultado.registros_con_error:
        print(f"  - {error.codigo_paciente} ({error.id_registro}): {error.motivo}")
