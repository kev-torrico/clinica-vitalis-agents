"""Fase 1 — gate: anti-fuga en 15/15 registros reales (sección 10.2 y los 3
registros sintéticos agregados en la Fase 3/4 como PAC-013..015)."""
from __future__ import annotations

import openpyxl
import pytest

import config
from agents.agente1_anonimizador import procesar_historias_clinicas
from core.contratos import RegistroHistoriaClinica
from core.reglas_anonimizacion import anonimizar_texto, generar_tokens
from core.verificacion_antifuga import verificar_texto_anonimizado


def _cargar_registros_reales() -> list[RegistroHistoriaClinica]:
    wb = openpyxl.load_workbook(config.ARCHIVO_ENTRADA, data_only=True)
    ws = wb[config.HOJA_ENTRADA]
    filas = list(ws.iter_rows(min_row=1, values_only=True))
    encabezados = filas[0]
    indices = {nombre: idx for idx, nombre in enumerate(encabezados)}

    registros = []
    for fila in filas[1:]:
        if fila[indices["ID_Registro"]] is None:
            continue
        registros.append(
            RegistroHistoriaClinica(
                id_registro=str(fila[indices["ID_Registro"]]),
                nombre_completo=str(fila[indices["Nombre completo"]]),
                cedula=str(fila[indices["Cédula"]]),
                direccion=str(fila[indices["Dirección"]]),
                telefono=str(fila[indices["Teléfono"]]),
                fecha_consulta=str(fila[indices["Fecha de consulta"]]),
                nota_clinica=str(fila[indices["Nota clínica (texto libre)"]]),
            )
        )
    return registros


@pytest.fixture(scope="module")
def registros_reales() -> list[RegistroHistoriaClinica]:
    return _cargar_registros_reales()


def test_hay_quince_registros_reales(registros_reales):
    assert len(registros_reales) == 15


def test_anonimizacion_elimina_los_4_identificadores_en_todos_los_registros(registros_reales):
    """Sección 10.2: ninguna de las cadenas identificadoras (N x 4)
    sobrevive en el texto_anonimizado correspondiente — probado
    programáticamente, no a ojo."""
    fallos = []
    for registro in registros_reales:
        tokens = generar_tokens(registro)
        texto_anonimizado = anonimizar_texto(registro.nota_clinica, tokens)
        verificacion = verificar_texto_anonimizado(registro, texto_anonimizado)
        if not verificacion.ok:
            fallos.append((registro.id_registro, verificacion.categorias_filtradas))

    assert not fallos, f"Residuos detectados: {fallos}"


def test_anonimizacion_no_usa_codigo_paciente_como_reemplazo(registros_reales):
    """El marcador debe ser siempre [ANON], nunca el codigo_paciente
    (sección 5, punto 3)."""
    registro = registros_reales[0]
    tokens = generar_tokens(registro)
    texto_anonimizado = anonimizar_texto(registro.nota_clinica, tokens)
    assert "PAC-" not in texto_anonimizado
    assert "[ANON]" in texto_anonimizado


def test_anonimizacion_conserva_datos_clinicos_no_identificadores(registros_reales):
    """Edad, peso y valores de laboratorio no son identificadores bajo el
    contrato 4.1 y deben conservarse (Marcela Suárez Rincón, REG-01)."""
    registro = registros_reales[0]
    tokens = generar_tokens(registro)
    texto_anonimizado = anonimizar_texto(registro.nota_clinica, tokens)
    assert "54 años" in texto_anonimizado
    assert "78 kg" in texto_anonimizado
    assert "182 mg/dL" in texto_anonimizado


def test_procesar_historias_clinicas_end_to_end(tmp_path):
    """Gate de Fase 1: el pipeline del Agente 1 produce 15 payloads válidos y
    cero registros con error para el archivo de referencia."""
    ruta_auditoria = tmp_path / "historias_clinicas_con_codigo.xlsx"

    resultado = procesar_historias_clinicas(
        ruta_entrada=config.ARCHIVO_ENTRADA,
        ruta_auditoria=ruta_auditoria,
    )

    assert len(resultado.payloads) == 15
    assert resultado.registros_con_error == []
    assert [p.codigo_paciente for p in resultado.payloads] == [f"PAC-{i:03d}" for i in range(1, 16)]
    assert ruta_auditoria.exists()


def test_payloads_reales_no_contienen_identificadores_crudos(registros_reales, tmp_path):
    ruta_auditoria = tmp_path / "historias_clinicas_con_codigo.xlsx"
    resultado = procesar_historias_clinicas(
        ruta_entrada=config.ARCHIVO_ENTRADA,
        ruta_auditoria=ruta_auditoria,
    )

    for payload, registro in zip(resultado.payloads, registros_reales):
        assert registro.nombre_completo not in payload.texto_anonimizado
        assert registro.cedula not in payload.texto_anonimizado
        assert registro.direccion not in payload.texto_anonimizado
        assert registro.telefono not in payload.texto_anonimizado


def test_auditoria_incluye_codigo_paciente_para_todas_las_filas(tmp_path):
    """La hoja interna debe permitir seguimiento por codigo_paciente para
    TODAS las filas de entrada, sin duplicar una tabla aparte (sección 9)."""
    ruta_auditoria = tmp_path / "historias_clinicas_con_codigo.xlsx"
    procesar_historias_clinicas(ruta_entrada=config.ARCHIVO_ENTRADA, ruta_auditoria=ruta_auditoria)

    wb = openpyxl.load_workbook(ruta_auditoria)
    ws = wb["Historias_Clinicas_Entrada"]
    filas = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(filas) == 15
    assert filas[0][-1] == "PAC-001"
    assert filas[0][1] == "Marcela Suárez Rincón"  # el mapa SÍ conserva identidad real


def _escribir_xlsx_entrada(ruta, filas: list[tuple]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = config.HOJA_ENTRADA
    ws.append(
        [
            "ID_Registro",
            "Nombre completo",
            "Cédula",
            "Dirección",
            "Teléfono",
            "Fecha de consulta",
            "Nota clínica (texto libre)",
        ]
    )
    for fila in filas:
        ws.append(fila)
    wb.save(ruta)


def test_nota_clinica_vacia_no_tumba_el_pipeline_y_queda_marcada(tmp_path):
    """Caso límite (sección 10.2): una nota vacía no debe tumbar el pipeline
    completo — se marca y se continúa con los demás registros."""
    ruta_entrada = tmp_path / "entrada_con_nota_vacia.xlsx"
    ruta_auditoria = tmp_path / "auditoria.xlsx"
    _escribir_xlsx_entrada(
        ruta_entrada,
        [
            ("REG-01", "Ana Pérez Gómez", "1.111.111", "Calle 1 #1-01, Bogotá", "300-000-0001", "2026-01-01", ""),
            (
                "REG-02",
                "Luis Torres Ruiz",
                "2.222.222",
                "Calle 2 #2-02, Cali",
                "300-000-0002",
                "2026-01-02",
                "Paciente Luis Torres Ruiz, CC 2.222.222, consulta por dolor de cabeza leve.",
            ),
        ],
    )

    resultado = procesar_historias_clinicas(ruta_entrada=ruta_entrada, ruta_auditoria=ruta_auditoria)

    assert len(resultado.payloads) == 1
    assert resultado.payloads[0].codigo_paciente == "PAC-002"
    assert len(resultado.registros_con_error) == 1
    assert resultado.registros_con_error[0].codigo_paciente == "PAC-001"
    assert resultado.registros_con_error[0].motivo == "nota_vacia"
