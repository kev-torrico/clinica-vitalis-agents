# Arquitectura — Pipeline Clínica Vitalis
### Anonimización + Clasificación clínica en 3 agentes, sin fuga de identidad

**Rol de este documento:** especificación de arquitectura para que **Claude Code** implemente el pipeline. No contiene código — contiene contratos, reglas, estructura de carpetas y criterios de aceptación con el nivel de detalle suficiente para que la implementación no requiera reinterpretar el caso de negocio.

**Caso base:** Caso 10 · Clínica Vitalis (Certificación 6, Sesión 6, Cap. 6, Lite Thinking).
**Continuidad:** este pipeline ya se ejecutó dos veces en modo "Claude simulando los 3 agentes en el chat". Este documento formaliza el paso pendiente registrado como próximo hito: pipeline Python ejecutable de verdad, con el Agente 2 llamando a un modelo real vía OpenRouter.

---

## 1. Resumen ejecutivo

Clínica Vitalis atiende ~300 pacientes/mes en 3 sedes. Cada historia clínica es texto libre que mezcla datos médicos con 4 identificadores del paciente (nombre completo, cédula, dirección, teléfono). Hoy una persona del equipo de calidad lee cada historia a mano, identifica condición, riesgo y antecedentes, y los pasa a un formulario de seguimiento epidemiológico — 40% del tiempo del equipo de calidad se va en esto. La política interna prohíbe que un dato identificable salga hacia un proveedor externo (LLM) sin anonimizar primero. No es negociable ni discutible: es la regla que nació del incidente del analista junior.

La solución es un pipeline de 3 agentes con responsabilidad única, donde la garantía de no-fuga **no depende de que nadie recuerde la regla** — está forzada por el contrato de datos entre etapas:

```
Historia clínica (texto libre + 4 identificadores)
        │
        ▼
┌─────────────────────┐
│ AGENTE 1             │  Determinístico, sin LLM, sin red externa.
│ Anonimizador         │  Sustituye los 4 identificadores por un código.
└─────────┬────────────┘
          │  SOLO { codigo_paciente, texto_anonimizado }
          ▼
┌─────────────────────┐
│ AGENTE 2             │  Único agente que llama a un LLM externo
│ Clasificador clínico │  (OpenRouter). Nunca ve nombre, cédula,
│                      │  dirección ni teléfono — estructuralmente
└─────────┬────────────┘  no pueden llegarle.
          │  { codigo_paciente, 7 campos clínicos }
          ▼
┌─────────────────────┐
│ AGENTE 3             │  Determinístico. Escribe el Excel final.
│ Generador de salida  │  Verificación anti-fuga antes de entregar.
└─────────┬────────────┘
          ▼
   Formulario_Salida (xlsx) — cero datos identificables
```

---

## 2. Hallazgo sobre los archivos del proyecto (léase antes de programar)

Se encontraron **dos versiones distintas del insumo**, y la elección de cuál usar afecta el esquema de datos:

| | `Dataset_Historias_Clinicas_Sinteticas.xlsx` | `Formulario_Salida_Vitalis.xlsx` |
|---|---|---|
| Identificadores en `Historias_Clinicas_Entrada` | Nombre completo, Cédula (2) | Nombre completo, Cédula, Dirección, Teléfono (4) |
| Columnas de la hoja de entrada | 5 | 7 |
| Coincide con el PDF del caso (que dice "nombre, cédula, dirección y teléfono") | No | Sí |
| Hoja `Formulario_Salida` | Solo fila de ejemplo (PAC-000) | 12 filas llenas (PAC-001…PAC-012), solo la fila 2 marcada visualmente como ejemplo |

**Decisión de arquitectura: usar `Formulario_Salida_Vitalis.xlsx` como fuente de verdad**, tanto para el esquema de entrada (7 columnas, 4 identificadores) como para el set de referencia de salida. Las 12 filas ya llenas de ese archivo **no se copian directamente al entregable** — son el oráculo de prueba contra el que se valida que el Agente 2 clasifica razonablemente (ver sección 10). El pipeline debe generar sus propias 12 filas desde cero, procesando `Historias_Clinicas_Entrada` de este mismo archivo.

`Dataset_Historias_Clinicas_Sinteticas.xlsx` queda como material histórico/de práctica de una iteración anterior del ejercicio (2 identificadores) — Claude Code no debe construir el pipeline contra su esquema de 5 columnas.

---

## 3. Fundamentación de diseño (respuesta arquitectónica a las 3 preguntas del caso)

Estas respuestas no son un ejercicio académico aparte: **son la justificación de cada decisión de la sección 4 en adelante.**

**¿Por qué separar "anonimizar" y "clasificar" en dos agentes distintos, en vez de un solo prompt?**
Porque en un solo prompt, el mismo proceso que ve el nombre real es el que decide qué escribir hacia afuera — la seguridad depende de que ese proceso "se acuerde" de no filtrar nada, y un LLM (o un desarrollador bajo presión) puede fallar en eso de mil formas sutiles: parafrasear el nombre, dejarlo en un campo de contexto, citarlo en una aclaración. Separarlos convierte la regla de negocio en un **límite estructural**: el Agente 2 físicamente no recibe el nombre en su payload, así que no hay "olvido" posible. Es exactamente el mecanismo que la Dra. Moreno necesitaba tras el incidente del analista junior: quitar la decisión humana (o del modelo) del camino, no reforzarla con más advertencias.

**Si el clasificador nunca ve el nombre real, ¿qué gana la clínica exactamente — y qué NO gana?**
Gana que ningún dato identificable sale hacia el proveedor externo del LLM, que es la política no negociable — cumplimiento verificable por diseño, no por confianza. Gana trazabilidad limpia: el código de paciente conecta todo sin exponer nada.
Lo que **no** gana: el riesgo de reidentificación indirecta sigue existiendo si el texto anonimizado conserva detalles muy específicos y poco comunes (una combinación rara de edad + diagnóstico + fecha + sede, por ejemplo, en una población de 300 pacientes/mes podría ser suficiente para que alguien con acceso a la hoja de entrada original infiera de quién se trata). Tampoco resuelve la seguridad del **mapa de auditoría** (código → identidad real): si ese archivo se filtra, la anonimización aguas abajo no sirve de nada. Por eso ese mapa se trata como el activo más sensible de todo el sistema (sección 9).

**¿Este problema es más automatización o más agente?**
Es un caso mixto, y el pipeline debe reflejarlo en el nivel de autonomía de cada etapa:
- **Agente 1 (anonimizar) y Agente 3 (escribir salida) son automatización pura**, no agentes en el sentido fuerte: el camino es siempre el mismo (misma regex, mismo mapeo de columnas), no hay ambigüedad real en la entrada — por eso ambos son determinísticos, sin LLM, sin margen de "interpretación".
- **Agente 2 (clasificar) sí es un agente**: la entrada es texto libre no estructurado, con ambigüedad real (síntomas que no siempre apuntan a un diagnóstico claro, información faltante), y requiere razonamiento clínico, no un mapeo fijo. Por eso es el único que justifica el costo/latencia/no-determinismo de un LLM — y precisamente por eso es el único al que hay que restringirle brutalmente lo que puede ver.

---

## 4. Contratos de datos entre agentes (obligatorios, no sugerencias)

Cada contrato se implementa como un modelo validado (ej. `pydantic`) con **campos explícitos**, nunca un diccionario abierto. El paso de una etapa a otra debe pasar por un `assert`/validación que rechace cualquier campo fuera del esquema — la exclusión de identificadores debe ser estructural, no "por convención de no incluirlos".

### 4.1 Salida Agente 1 → entrada Agente 2 (el contrato más crítico del sistema)

```json
{
  "codigo_paciente": "PAC-001",
  "texto_anonimizado": "Paciente [PAC-001], [ANON], [ANON] años. Consulta por fatiga..."
}
```
- Exactamente estas dos claves. Ninguna otra.
- `codigo_paciente`: formato `PAC-NNN`, correlativo de 3 dígitos, generado en orden de `ID_Registro`.
- `texto_anonimizado`: el texto de `Nota clínica (texto libre)` con los 4 identificadores sustituidos (ver sección 6). Fecha de consulta, edad, peso, talla, ciudad genérica u otros datos clínicos **no** son identificadores bajo este contrato y se conservan tal cual — son necesarios para la clasificación.

### 4.2 Salida Agente 2 → entrada Agente 3

```json
{
  "codigo_paciente": "PAC-001",
  "enfermedad_probable": "diabetes tipo 2",
  "nivel_riesgo": "medio",
  "comportamiento_observado": "Fatiga persistente y sed excesiva de 3 meses...",
  "confianza": "alta",
  "antecedentes": "antecedente familiar de diabetes tipo 2",
  "fuma": "No",
  "consumo_sustancias": "No registrado"
}
```
- `nivel_riesgo` ∈ {bajo, medio, alto}
- `confianza` ∈ {alta, media, baja}
- `fuma`, `consumo_sustancias` ∈ {Sí, No, "No registrado"}
- `enfermedad_probable = "indeterminado"` cuando la evidencia clínica es insuficiente. Es una **regla de negocio explícita, no un fallback silencioso**: cuando se usa, `confianza` debe ser `"baja"` y `comportamiento_observado` debe explicar por qué la evidencia es insuficiente (no dejarlo genérico).
- Validación de contrato en el orquestador: el payload que efectivamente se envía al Agente 2 debe verificarse (assert) que contiene únicamente `codigo_paciente` y `texto_anonimizado` de 4.1 — nunca el registro original completo "por si acaso".

### 4.3 Salida Agente 3

Archivo `.xlsx` con una única hoja de resultados (`Formulario_Salida`), mismos 8 encabezados y mismo orden que el archivo de referencia. Sin hoja de entrada, sin mapa de auditoría, sin ninguna columna adicional.

---

## 5. Especificación — Agente 1: Anonimizador

**Naturaleza:** determinístico. Sin llamadas a red externa, sin LLM. Esto no es una preferencia de estilo — es el control de seguridad principal del sistema: el paso que toca los 4 identificadores en crudo debe ser el más simple, más auditable y más fácil de probar exhaustivamente de todo el pipeline.

**Entrada:** una fila de `Historias_Clinicas_Entrada` (`ID_Registro`, `Nombre completo`, `Cédula`, `Dirección`, `Teléfono`, `Fecha de consulta`, `Nota clínica`).

**Lógica:**
1. Generar `codigo_paciente` = `PAC-{n:03d}` según el orden de `ID_Registro`.
2. Construir la lista de tokens a eliminar del texto libre a partir de las columnas estructuradas de esa misma fila (nunca inventados, siempre derivados del registro):
   - Nombre completo íntegro, y cada uno de sus componentes por separado (nombre(s) y apellido(s)) — en la nota suele aparecer solo el nombre completo, pero la regla debe cubrir apariciones parciales.
   - Cédula, en todas sus variantes de formato: con puntos (`52.884.117`), sin puntos (`52884117`), con prefijo `CC` pegado o separado.
   - Dirección completa y también fragmentos reconocibles (número de carrera/calle + complemento).
   - Teléfono, con y sin guiones.
3. Reemplazar cada ocurrencia por el marcador `[ANON]` (no por el `codigo_paciente` — el código de paciente identifica la fila en el sistema, pero no debe aparecer repetido dentro del texto libre como si fuera parte de la narrativa clínica; mantener ambos conceptos separados evita ambigüedad al leer logs o intermedios).
4. **Verificación anti-fuga de dos capas, obligatoria antes de dejar avanzar el registro:**
   - Capa 1 (regex): confirmar que ninguna de las cadenas exactas de nombre/cédula/dirección/teléfono sobrevive en `texto_anonimizado`.
   - Capa 2 (red de seguridad): buscar también variantes con puntuación alterada, mayúsculas/minúsculas, y componentes individuales del nombre de 3+ caracteres que puedan haber quedado sueltos (ej. si el apellido aparece sin el nombre).
   - Si cualquiera de las dos capas detecta un residuo: **el pipeline se detiene para ese registro** (no se "arregla en silencio" ni se deja pasar con una advertencia). Se registra el incidente en un log interno y el registro queda marcado como `requiere_revision_manual` — nunca avanza al Agente 2.

**Salida:**
- Hacia el Agente 2: únicamente el contrato de la sección 4.1.
- Hacia el archivo interno de trazabilidad (sección 9): la hoja `Historias_Clinicas_Entrada` original, con `codigo_paciente` añadido como columna nueva, para permitir seguimiento posterior sin duplicar datos identificables en una tabla aparte.

---

## 6. Especificación — Agente 2: Clasificador clínico

**Naturaleza:** el único agente con razonamiento no determinístico. Único punto del sistema autorizado a llamar a un LLM externo (OpenRouter).

**Entrada:** exclusivamente el contrato 4.1 — `codigo_paciente` y `texto_anonimizado`. El código que invoca este agente debe rechazar programáticamente cualquier intento de pasarle un objeto con más campos.

**Tarea:** producir los 7 campos clínicos del contrato 4.2 a partir de `texto_anonimizado`.

**Reglas de negoción del prompt (no opcionales):**
- Instrucción explícita al modelo de que el texto ya está anonimizado y que bajo ninguna circunstancia debe inferir, inventar o solicitar un nombre — su única referencia al paciente es `codigo_paciente`.
- `confianza` es una **declaración del modelo sobre su propia certeza**, nunca un valor decorativo. Si la nota no trae evidencia suficiente para un diagnóstico razonable, la respuesta correcta es `enfermedad_probable = "indeterminado"` + `confianza = "baja"` + una explicación honesta en `comportamiento_observado` — no una invención plausible.
- Salida forzada a JSON estructurado (usar modo de salida estructurada / JSON schema del proveedor si OpenRouter y el modelo elegido lo soportan; si no, parsing estricto con reintento en caso de JSON inválido).
- Reintentos: máximo 2 reintentos ante error de red o JSON malformado, con backoff. Al tercer fallo, el registro se marca `error_clasificacion` y no se inventa una fila — se reporta como pendiente, igual que un registro con evidencia insuficiente se marca `indeterminado` en vez de forzarse un diagnóstico.

**Configuración:**
- `OPENROUTER_API_KEY` se lee de variable de entorno. Nunca hardcodeada, nunca en el repo, nunca en logs.
- El modelo (`model=`) es un valor de configuración externo (archivo de config o env var), no un literal enterrado en el código — para poder cambiarlo sin tocar lógica.

---

## 7. Especificación — Agente 3: Generador de salida

**Naturaleza:** determinístico, sin LLM.

**Entrada:** la colección de resultados del Agente 2 (contrato 4.2), uno por `codigo_paciente`.

**Tarea:**
1. Escribir un `.xlsx` con la hoja `Formulario_Salida`, mismos encabezados y orden exacto que el archivo de referencia: `código_paciente, enfermedad_probable, nivel_riesgo, comportamiento_observado, confianza, antecedentes, fuma, consumo_sustancias`.
2. Una fila por paciente, en orden de `codigo_paciente`.
3. Fuente profesional (Arial), sin la fila de ejemplo resaltada del archivo original — el entregable no debe mezclar el ejemplo de formato con resultados reales, tal como advierte la leyenda del propio archivo.
4. **Verificación anti-fuga final, sobre el archivo ya escrito**, no solo sobre los datos en memoria: releer el `.xlsx` generado y confirmar que ninguna cadena de nombre, cédula, dirección o teléfono de la hoja de entrada aparece en ninguna celda de la hoja de salida. Esta es la última línea de defensa antes de que el archivo se considere entregable.
5. El archivo final **no incluye** la hoja `Historias_Clinicas_Entrada` ni el mapa de auditoría — solo `Formulario_Salida`.

---

## 8. La capa anti-fuga es infraestructura, no un cuarto agente

Deliberadamente el pipeline tiene 3 agentes, no 4. La verificación anti-fuga (regex + red de seguridad en el Agente 1, y el escaneo final en el Agente 3) **no es un agente que decide** — es una función determinística que corre automáticamente en cada transición de etapa y que puede detener el pipeline, pero nunca "interpreta" ni "decide caso por caso" qué dato es seguro copiar. Esa es exactamente la distinción que resolvió el incidente del analista junior en el caso: quitarle a un humano (o a un modelo) la decisión de juicio en el momento, y reemplazarla por una regla que se ejecuta siempre igual.

---

## 9. Aislamiento del mapa de auditoría (y trazabilidad para seguimiento futuro)

El mapa `codigo_paciente ↔ identidad real` es el activo más sensible del sistema — más que la nota clínica anonimizada, porque revierte toda la anonimización de una sola vez si se filtra. Al mismo tiempo, ese mapa tiene un uso legítimo de negocio: si el equipo clínico necesita hacer **seguimiento real a un paciente** a partir de un resultado del formulario de salida (ej. contactar a `PAC-007` por su migraña), necesita poder volver de `codigo_paciente` a la persona. El diseño tiene que servir ambos objetivos a la vez — no ocultar el vínculo, sino aislarlo.

**Implementación concreta:** el Agente 1, además de producir el contrato 4.1 hacia el Agente 2, **añade la columna `codigo_paciente` a la propia hoja `Historias_Clinicas_Entrada`** (la que ya tiene los 4 identificadores) y la guarda como archivo interno — en vez de mantener una tabla de auditoría duplicada y separada. Esto evita tener dos copias de los mismos datos identificables desincronizables entre sí, y deja un único punto de consulta para seguimiento: se busca el `codigo_paciente` en esa hoja y ahí están nombre, cédula, dirección y teléfono en la misma fila.

Reglas de aislamiento (no cambian por este ajuste, solo cambia dónde vive el dato):
- Ese archivo enriquecido (`historias_clinicas_con_codigo.xlsx` o equivalente) vive únicamente en `data/internal/`, nunca en `data/output/`.
- Ningún componente del Agente 2 o del Agente 3 tiene ruta de acceso a ese archivo — ni siquiera de solo lectura. Se garantiza por estructura de carpetas y por las firmas de función (el Agente 2 y el Agente 3 no reciben ese path como argumento en ningún punto del código).
- No se sube a control de versiones (debe estar en `.gitignore` desde el primer commit).
- No se incluye en logs, ni siquiera en modo debug — los logs deben registrar `codigo_paciente`, nunca `Nombre completo`/`Cédula`/`Dirección`/`Teléfono`, ni en mensajes de error ni en trazas de excepción.
- El acceso a ese archivo para fines de seguimiento clínico es un proceso manual, fuera del pipeline automatizado — el pipeline lo escribe, pero no lo vuelve a leer en ninguna etapa posterior.

---

## 10. Plan de pruebas

### 10.1 Oráculo de referencia
Las 12 filas ya llenas de `Formulario_Salida_Vitalis.xlsx` (PAC-001…PAC-012) se usan como set de referencia — **no como respuesta exacta a igualar carácter por carácter** (el texto libre que produce un LLM variará), sino para validar:
- Los campos categóricos (`nivel_riesgo`, `fuma`, `consumo_sustancias`) deberían coincidir o ser clínicamente defendibles frente al patrón del caso.
- Los 5 casos marcados `indeterminado` en la referencia (PAC-003, PAC-004, PAC-008, PAC-010, PAC-012, según ese archivo) son el caso de prueba más importante de todo el sistema: verifican que el Agente 2 no fuerza un diagnóstico cuando la evidencia es débil. Un pipeline que "acierta" diagnósticos pero nunca produce `indeterminado` está violando la regla de negocio, no superándola.

### 10.2 Pruebas obligatorias (nivel de código, no solo inspección visual)
- **Anti-fuga Agente 1:** para cada uno de los 12 registros, ninguna de las 48 cadenas identificadoras (12 × 4 identificadores) sobrevive en el `texto_anonimizado` correspondiente — probado programáticamente, no a ojo.
- **Contrato Agente 2:** el payload real que se serializa hacia la llamada al LLM contiene exactamente las claves `codigo_paciente` y `texto_anonimizado` — cualquier clave adicional falla la prueba.
- **Regla `indeterminado`:** todo registro con `enfermedad_probable = "indeterminado"` tiene `confianza = "baja"` (nunca `alta`/`media`).
- **Anti-fuga final:** el archivo `.xlsx` de salida, releído desde disco, no contiene ninguna cadena de las 48 identificadoras originales.
- **Aislamiento del mapa de auditoría:** prueba estática/de importación que confirme que ni `agent2_clasificador.py` ni `agent3_generador_salida.py` importan o referencian el módulo/ruta del mapa de auditoría.
- **Casos límite:** registro con nota clínica vacía o corrupta (no debe tumbar el pipeline completo, se marca y se continúa con los demás); fallo simulado de la API de OpenRouter (reintentos, luego marca de error, nunca un diagnóstico inventado para rellenar).

---

## 11. Stack técnico

| Componente | Elección | Motivo |
|---|---|---|
| Lenguaje | Python 3.11+ | Consistente con el resto de la infraestructura de TS3+/Yesid |
| Lectura/escritura Excel | `openpyxl` (formato/formulas) + `pandas` (lectura masiva) | Estándar ya usado en iteraciones previas de este proyecto |
| Validación de contratos | `pydantic` | Fuerza el esquema en tiempo de ejecución, no solo por convención |
| Cliente LLM | `httpx`/`requests` contra `https://openrouter.ai/api/v1` | Ya decidido como próximo hito en el proyecto |
| Configuración/credenciales | variables de entorno (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`) vía `os.environ`, sin hardcodear | No negociable — ya registrado como decisión previa |
| Pruebas | `pytest` | Para las pruebas de la sección 10 |
| Logging | `logging` estándar, con filtro que impide loguear campos identificadores | Control de fuga en capa de observabilidad |

---

## 12. Estructura de carpetas propuesta

```
vitalis_pipeline/
├── agents/
│   ├── agente1_anonimizador.py
│   ├── agente2_clasificador.py
│   └── agente3_generador_salida.py
├── core/
│   ├── contratos.py            # modelos pydantic de las secciones 4.1–4.3
│   ├── reglas_anonimizacion.py # regex + capa de seguridad
│   ├── verificacion_antifuga.py
│   ├── cliente_openrouter.py
│   └── auditoria.py            # único módulo con acceso al mapa código↔identidad
├── orquestador.py              # coordina las 3 etapas y los gates de validación
├── config.py                   # lee env vars, nunca valores hardcodeados
├── data/
│   ├── input/                  # copia de Formulario_Salida_Vitalis.xlsx (hoja de entrada)
│   ├── internal/                # Historias_Clinicas_Entrada + codigo_paciente — NUNCA en outputs, NUNCA en git
│   └── output/                  # Formulario_Salida_Vitalis_resultado.xlsx (entregable)
├── tests/
│   ├── fixtures/                # las 12 filas de referencia de Formulario_Salida_Vitalis.xlsx
│   ├── test_anonimizacion.py
│   ├── test_contrato_agente2.py
│   ├── test_regla_indeterminado.py
│   └── test_antifuga_final.py
├── .gitignore                   # debe incluir data/internal/
├── requirements.txt
└── README.md
```

---

## 13. Plan de implementación por fases (con gates, siguiendo el patrón ya usado en este proyecto)

Cada fase requiere aprobación explícita antes de pasar a la siguiente — ninguna fase se asume aprobada por defecto.

1. **Fase 0 — Contratos.** Implementar `core/contratos.py` con los 3 esquemas de la sección 4. Sin lógica de negocio todavía. Gate: revisión de que los esquemas excluyen estructuralmente los identificadores.
2. **Fase 1 — Agente 1 + anti-fuga capa 1 y 2.** Implementar sobre los 12 registros reales de `Formulario_Salida_Vitalis.xlsx`. Gate: las pruebas de anti-fuga de la sección 10.2 pasan en 12/12 registros.
3. **Fase 2 — Agente 2 vía OpenRouter.** Implementar con la validación de contrato de entrada restringida. Gate: prueba de que el payload enviado no contiene más que las 2 claves permitidas, y que los 5 casos esperables como `indeterminado` efectivamente salen así.
4. **Fase 3 — Agente 3 + anti-fuga final.** Gate: el `.xlsx` generado pasa el escaneo anti-fuga completo y respeta encabezados/orden del archivo de referencia.
5. **Fase 4 — Orquestador end-to-end + suite completa de pruebas + manejo de casos límite** (registro vacío, fallo de API). Gate: `pytest` completo en verde, y revisión manual de una muestra de salidas por Yesid antes de considerar el pipeline listo para uso real.

---

## 14. Criterios de aceptación (Definition of Done)

- [ ] Los 12 registros de `Historias_Clinicas_Entrada` (hoja de `Formulario_Salida_Vitalis.xlsx`) se procesan de punta a punta sin intervención manual.
- [ ] Cero identificadores (nombre, cédula, dirección, teléfono) sobreviven en ningún artefacto intermedio ni en el archivo final — verificado por código, no por inspección visual.
- [ ] El Agente 2 nunca recibe en su payload nada distinto a `codigo_paciente` y `texto_anonimizado` — verificado por prueba automática.
- [ ] Los casos con evidencia clínica insuficiente quedan como `indeterminado` + `confianza: baja`, nunca con un diagnóstico inventado.
- [ ] `OPENROUTER_API_KEY` no aparece hardcodeada en ningún archivo del repositorio.
- [ ] El mapa de auditoría vive fuera de `data/output/`, está en `.gitignore`, y ningún módulo de los Agentes 2 o 3 lo importa.
- [ ] El archivo de salida respeta encabezados, orden de columnas y formato profesional del archivo de referencia.
- [ ] Suite de `pytest` en verde, incluyendo los casos límite de registro vacío/corrupto y fallo simulado de la API.

---

## 15. Riesgos abiertos y siguientes pasos

- **Reidentificación indirecta:** aunque los 4 identificadores explícitos se eliminan, combinaciones de edad + diagnóstico + fecha + sede en una población pequeña podrían, en teoría, permitir inferencia. Fuera del alcance de este pipeline (que resuelve la política actual de la clínica), pero vale dejarlo documentado como limitación conocida, no como brecha no vista.
- **Elección del modelo en OpenRouter:** este documento no fija un modelo específico — es un valor de configuración. Se recomienda evaluarlo en la Fase 2 con los 12 casos de referencia antes de fijarlo como default.
- **`Dataset_Historias_Clinicas_Sinteticas.xlsx`** queda fuera del alcance de esta implementación (ver sección 2); si en el futuro se requiere soportar el esquema de 2 identificadores, es un cambio de contrato, no un ajuste menor.
