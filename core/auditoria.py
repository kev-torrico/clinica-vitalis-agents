"""Único módulo con acceso de escritura al mapa código_paciente <-> identidad
real (sección 9). Ningún otro módulo del pipeline debe importar esta ruta ni
volver a leer el archivo que produce — el acceso para seguimiento clínico es
un proceso manual, fuera del pipeline automatizado.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

from core.contratos import RegistroHistoriaClinica

ENCABEZADOS = [
    "ID_Registro",
    "Nombre completo",
    "Cédula",
    "Dirección",
    "Teléfono",
    "Fecha de consulta",
    "Nota clínica (texto libre)",
    "codigo_paciente",
]


def guardar_historias_con_codigo(
    filas: list[tuple[RegistroHistoriaClinica, str]],
    ruta_destino: Path,
) -> None:
    """Escribe `Historias_Clinicas_Entrada` original + `codigo_paciente` como
    columna nueva, en vez de mantener una tabla de auditoría duplicada.

    `filas` es (registro, codigo_paciente) para TODAS las filas de entrada,
    incluidas las marcadas `requiere_revision_manual` — el seguimiento por
    código debe funcionar también para esas.
    """
    ruta_destino = Path(ruta_destino)
    ruta_destino.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Historias_Clinicas_Entrada"
    ws.append(ENCABEZADOS)

    for registro, codigo_paciente in filas:
        ws.append(
            [
                registro.id_registro,
                registro.nombre_completo,
                registro.cedula,
                registro.direccion,
                registro.telefono,
                registro.fecha_consulta,
                registro.nota_clinica,
                codigo_paciente,
            ]
        )

    wb.save(ruta_destino)
