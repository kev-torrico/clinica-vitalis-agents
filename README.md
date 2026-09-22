# Pipeline Clínica Vitalis

Pipeline de 3 agentes que anonimiza historias clínicas y clasifica la condición del paciente sin que el proveedor de LLM externo (OpenRouter) llegue a ver nunca un dato identificable. La especificación completa (contratos, reglas de negocio, criterios de aceptación) vive en [ARQUITECTURA.md](ARQUITECTURA.md) — este README es la guía práctica para levantarlo y entenderlo rápido.

```
Historia clínica (texto libre + 4 identificadores)
        │
        ▼
┌─────────────────────┐
│ Agente 1             │  Determinístico, sin LLM, sin red externa.
│ Anonimizador         │  Sustituye los 4 identificadores por [ANON].
└─────────┬────────────┘
          │  SOLO { codigo_paciente, texto_anonimizado }
          ▼
┌─────────────────────┐
│ Agente 2             │  Único agente que llama a un LLM externo
│ Clasificador clínico │  (OpenRouter). Nunca ve nombre, cédula,
│                       │  dirección ni teléfono.
└─────────┬────────────┘  { codigo_paciente, 7 campos clínicos }
          ▼
┌─────────────────────┐
│ Agente 3             │  Determinístico. Escribe el Excel final y
│ Generador de salida  │  vuelve a auditar el archivo ya en disco.
└─────────┬────────────┘
          ▼
   Formulario_Salida (xlsx) — cero datos identificables
```

## Qué hace cada agente

### Agente 1 — Anonimizador (`agents/agente1_anonimizador.py`)
- Determinístico, sin llamadas a red ni LLM: es el único punto del sistema que toca los 4 identificadores (nombre, cédula, dirección, teléfono) en crudo.
- Lee `Historias_Clinicas_Entrada`, asigna un `codigo_paciente` correlativo (`PAC-NNN`) por orden de `ID_Registro`, y reemplaza cada identificador (y sus variantes de formato) por `[ANON]` en el texto libre (`core/reglas_anonimizacion.py`).
- Corre una verificación anti-fuga de dos capas (`core/verificacion_antifuga.py`) sobre cada texto anonimizado: cadenas exactas + variantes normalizadas/componentes sueltos del nombre. Si algo sobrevive, ese registro queda `requiere_revision_manual` y **nunca** avanza al Agente 2 — el resto del lote sigue su curso.
- Escribe el mapa `codigo_paciente ↔ identidad real` en `data/internal/` (`core/auditoria.py`) para trazabilidad/seguimiento clínico manual. Este archivo **nunca** se lee de vuelta en el resto del pipeline y **nunca** se sube a git.

### Agente 2 — Clasificador clínico (`agents/agente2_clasificador.py`)
- Único agente no determinístico y único punto autorizado a llamar a un LLM externo, vía OpenRouter (`core/cliente_openrouter.py`).
- Su firma solo acepta una instancia de `PayloadAgente2` (`codigo_paciente` + `texto_anonimizado`); cualquier otro objeto es rechazado con `TypeError` antes de construir la petición.
- El prompt exige salida JSON estricta con los 7 campos clínicos del contrato (`enfermedad_probable`, `nivel_riesgo`, `comportamiento_observado`, `confianza`, `antecedentes`, `fuma`, `consumo_sustancias`), e instruye explícitamente distinguir evidencia objetiva (labs, examen físico, patrón clínico clásico) de un relato narrativo único sin confirmación — en el segundo caso debe preferir `enfermedad_probable="indeterminado"` + `confianza="baja"`, nunca inventar un diagnóstico.
- Reintenta hasta 2 veces (backoff exponencial) ante error de red, JSON malformado o una respuesta que viola el contrato/regla de negocio. Al tercer fallo, levanta `ErrorClasificacionAgotada` — el orquestador marca ese registro como `error_clasificacion` y sigue con los demás, nunca "rellena" una fila.

### Agente 3 — Generador de salida (`agents/agente3_generador_salida.py`)
- Determinístico, sin LLM. Escribe `Formulario_Salida` (mismos 8 encabezados y orden que el archivo de referencia, fuente Arial) a partir de las `ClasificacionClinica` recibidas.
- Corre la verificación anti-fuga **final** sobre el `.xlsx` ya escrito en disco (releído, no sobre los datos en memoria). Si detecta cualquier residuo, borra el archivo y lanza `ErrorAntifugaSalida`: nunca queda en `data/output/` un entregable contaminado.
- No recibe nunca la ruta del mapa de auditoría de `data/internal/`; los identificadores que necesita para su propia verificación se cargan directamente desde el archivo de **entrada** original (`agents/agente1_anonimizador.cargar_registros_entrada`).

### Orquestador (`orquestador.py`)
Coordina Agente 1 → Agente 2 → Agente 3 → verificación final. Un registro problemático en cualquiera de las dos primeras etapas no tumba la ejecución global: queda marcado (`requiere_revision_manual` o `error_clasificacion`) y el resto del lote se procesa con normalidad.

## Estructura del proyecto

```
vitalis_pipeline/
├── agents/
│   ├── agente1_anonimizador.py   # Agente 1
│   ├── agente2_clasificador.py   # Agente 2
│   └── agente3_generador_salida.py  # Agente 3
├── core/
│   ├── contratos.py              # modelos pydantic de los contratos entre agentes
│   ├── reglas_anonimizacion.py   # generación de tokens + sustitución por [ANON]
│   ├── verificacion_antifuga.py  # verificación de 2 capas (por registro) + verificación final (archivo)
│   ├── cliente_openrouter.py     # transporte HTTP + reintentos hacia OpenRouter
│   └── auditoria.py              # único módulo con acceso de escritura al mapa código↔identidad
├── orquestador.py                # coordina las 3 etapas y los gates de validación
├── config.py                     # rutas + credenciales, siempre desde el entorno (.env)
├── data/
│   ├── input/                    # Formulario_Salida_Vitalis.xlsx (hoja de entrada real)
│   ├── internal/                 # mapa código↔identidad — NUNCA en outputs, NUNCA en git
│   └── output/                   # Formulario_Salida_Vitalis_resultado.xlsx (entregable)
├── tests/                        # pytest — ver "Cómo correr las pruebas"
├── .env                          # credenciales locales (NUNCA se sube a git)
├── .gitignore
├── requirements.txt
├── ARQUITECTURA.md               # especificación completa del caso y los contratos
└── README.md                     # este archivo
```

## Cómo levantarlo

Requiere Python 3.11+.

```powershell
# 1. Crear y activar un entorno virtual (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
# .venv\Scripts\activate.bat   # cmd.exe
# source .venv/bin/activate    # Linux/Mac

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar credenciales (ver abajo)
copy .env.example .env         # si no existe .env todavía, y completar los valores
```

## Variables de entorno

Se leen desde el entorno real o desde un archivo `.env` en la raíz del proyecto (vía `python-dotenv`, cargado en `config.py`). **`.env` nunca se sube a git** — ya está en `.gitignore`.

| Variable | Obligatoria | Descripción |
|---|---|---|
| `OPENROUTER_API_KEY` | Sí (Agente 2) | API key de [OpenRouter](https://openrouter.ai/). Nunca se hardcodea ni se loguea. |
| `OPENROUTER_MODEL` | Sí (Agente 2) | Id del modelo a usar (ej. `anthropic/claude-sonnet-4.5`). Verifica en [openrouter.ai/models](https://openrouter.ai/models) que el id siga vigente — los proveedores retiran modelos con el tiempo. |
| `VITALIS_DATA_DIR` | No | Sobreescribe la carpeta `data/` por defecto (útil para pruebas o entornos separados). |
| `VITALIS_RUN_INTEGRACION_OPENROUTER` | No | Poner en `1` para habilitar el test de integración real contra OpenRouter (`tests/test_regla_indeterminado.py`) — gasta cuota de la API, por eso está desactivado por defecto. |

La cuenta de OpenRouter necesita crédito disponible: revisa el saldo en `https://openrouter.ai/settings/credits` si el pipeline devuelve errores `402`.

## Cómo ejecutar el pipeline completo

```bash
python -m orquestador
```

Esto corre las 3 etapas sobre `data/input/Formulario_Salida_Vitalis.xlsx` y deja:
- el entregable final en `data/output/Formulario_Salida_Vitalis_resultado.xlsx`,
- el mapa de auditoría interno en `data/internal/historias_clinicas_con_codigo.xlsx` (no se sube a git),
- un resumen en consola de registros `requiere_revision_manual` y `error_clasificacion`, si los hay.

Para correr solo el Agente 1 (sin llamar a OpenRouter, útil para verificar la anonimización):

```bash
python -m agents.agente1_anonimizador
```

## Cómo correr las pruebas

```bash
pytest
```

Corre toda la suite (contratos, anonimización, reglas de negocio del Agente 2, anti-fuga final, orquestador) usando mocks para las llamadas a OpenRouter — no gasta cuota de API ni requiere credenciales reales.

Para incluir además el test de integración real contra OpenRouter (gasta cuota; requiere `OPENROUTER_API_KEY`/`OPENROUTER_MODEL` configurados):

```bash
# PowerShell
$env:VITALIS_RUN_INTEGRACION_OPENROUTER = "1"; pytest tests/test_regla_indeterminado.py -v

# bash
VITALIS_RUN_INTEGRACION_OPENROUTER=1 pytest tests/test_regla_indeterminado.py -v
```

## Garantías de seguridad (resumen)

- El Agente 2 estructuralmente no puede recibir nombre, cédula, dirección ni teléfono: su único parámetro válido es `PayloadAgente2`, validado por pydantic con `extra="forbid"`.
- Toda anonimización pasa por una verificación de dos capas antes de avanzar; toda salida final se vuelve a auditar ya escrita en disco.
- El mapa código↔identidad vive solo en `data/internal/`, está en `.gitignore`, y ni el Agente 2 ni el Agente 3 lo importan ni reciben su ruta en ningún punto del código (verificado con una prueba estática en `tests/test_antifuga_final.py`).

El detalle completo de cada contrato, regla de negocio y criterio de aceptación está en [ARQUITECTURA.md](ARQUITECTURA.md).
