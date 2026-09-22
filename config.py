"""Configuración del pipeline: rutas y credenciales, siempre desde el entorno.

Ningún valor sensible (API keys) ni ninguna ruta se hardcodea en la lógica
de negocio — todo pasa por este módulo (sección 11 y 14 de ARQUITECTURA.md).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Carga .env si existe (nunca se sube a git — ver .gitignore). No sobreescribe
# variables ya presentes en el entorno real (ej. las de CI).
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("VITALIS_DATA_DIR", BASE_DIR / "data"))
DATA_INPUT_DIR = DATA_DIR / "input"
DATA_INTERNAL_DIR = DATA_DIR / "internal"
DATA_OUTPUT_DIR = DATA_DIR / "output"

ARCHIVO_ENTRADA = DATA_INPUT_DIR / "Formulario_Salida_Vitalis.xlsx"
ARCHIVO_AUDITORIA = DATA_INTERNAL_DIR / "historias_clinicas_con_codigo.xlsx"
ARCHIVO_SALIDA = DATA_OUTPUT_DIR / "Formulario_Salida_Vitalis_resultado.xlsx"

HOJA_ENTRADA = "Historias_Clinicas_Entrada"
HOJA_SALIDA = "Formulario_Salida"

# Agente 2 (OpenRouter) — usado a partir de la Fase 2, definido aquí para que
# nunca exista un literal de modelo/credencial enterrado en agents/agente2_*.py.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
