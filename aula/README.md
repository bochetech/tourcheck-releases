# Aula

Motor de tutoría con IA para educación en casa, anclado a un currículo nacional
validado. Diseñado para dos hijos concretos (7 y 13 años) en Chile, pero
currículo-agnóstico por construcción: Chile es *un adaptador*, no *el* currículo.

El diseño completo, con la investigación que lo sostiene, está en
[`docs/DISENO.md`](docs/DISENO.md).

## Estado

**Fase 1 en curso.** Lo que ya funciona:

| Pieza | Estado |
| --- | --- |
| Modelo canónico del currículo | ✅ funciona |
| **Validador de 12 reglas duras** | ✅ funciona |
| Índice de legibilidad en español (Fernández Huerta) | ✅ funciona |
| Lectura/escritura YAML diffeable | ✅ funciona |
| CLI `aula curriculum validate` | ✅ funciona |
| **Configuración de modelos por rol** | ✅ funciona, 5 perfiles |
| **Vocabulario cerrado de reparación** | ✅ funciona, 11 operaciones |
| **Bucle de auto-reparación** | ✅ funciona |
| **Cliente de modelos (OpenAI-compatible)** | ✅ funciona, local y nube |
| **Familia, estudiantes y asignación de planes** | ✅ funciona |
| **Importador de currículo (`fetch` / `extract` / `import`)** | ✅ funciona |
| Primera corrida contra documentos reales del MINEDUC | ⬜ siguiente |
| Motor socrático, anclaje, voz | ⬜ fases 2-5 |

## Por qué el validador va primero

El validador **no es una puerta para el padre, es el bucle de retroalimentación
de la IA**. Cada hallazgo trae una instrucción de reparación accionable y un
`datos` estructurado, para que el importador se corrija solo:

```json
{
  "regla": 2,
  "codigo_regla": "R02_PREREQ_INEXISTENTE",
  "severidad": "bloqueante",
  "mensaje": "el prerrequisito 'MA02 OA 99' no existe en el currículo",
  "reparacion": "Corrige o elimina la referencia 'MA02 OA 99' en el objetivo 'MA02 OA 02'…",
  "datos": {"objetivo": "MA02 OA 02", "prerequisito_roto": "MA02 OA 99"}
}
```

Por eso se construye antes que el extractor: el extractor se desarrolla contra un
criterio de correctitud, no contra la intuición. Al padre solo le llega lo que el
bucle no logró cerrar.

## Las 12 reglas

| # | Regla | Severidad |
| --- | --- | --- |
| 1 | El grafo de prerrequisitos es acíclico | bloqueante |
| 2 | Todo prerrequisito referenciado existe | bloqueante |
| 3 | Ningún objetivo huérfano | bloqueante |
| 4 | Todo objetivo tiene ≥1 ítem de evaluación | bloqueante |
| 5 | Todo objetivo tiene trazabilidad a su fuente | bloqueante |
| 6 | Cobertura del temario oficial al 100% | bloqueante |
| 7 | Las horas cuadran con el plan de estudio (±10%) | advertencia |
| 8 | Sin códigos duplicados | bloqueante |
| 9 | Profundidad del grafo razonable | advertencia |
| 10 | Cada recurso declara su licencia | advertencia |
| 11 | Texto legible para el nivel | advertencia |
| 12 | El currículo declara versión y vigencia | bloq. / adv. |

Las advertencias **no frenan el arranque**: van a la cola de excepciones y se
revisan mientras los niños ya usan el sistema.

## No está hecho para una sola familia

`Familia → Estudiantes → Asignación`. Multi-estudiante desde el primer día, aunque
la primera familia tenga dos hijos: añadirlo después obliga a reescribir el
esquema entero, y hacerlo ahora cuesta casi nada.

```bash
aula familia crear "Familia Pérez" --adulto Ana
aula familia agregar "Mateo" --nacimiento 2019-04-10
aula familia asignar mateo --curriculo cl-mineduc-2026 --version 2026-03 --nivel 02
aula familia mostrar
```

La edad decide la piel y el perfil de voz por defecto —Explorador y voz
restringida por debajo de los 10, Taller y voz abierta por encima— y un adulto
puede fijar ambos a mano: un niño de 11 con dificultades de lectura puede
necesitar Explorador, y uno de 9 muy adelantado, Taller.

**El plan se fija a una versión concreta.** Si el ministerio publica una versión
nueva a mitad de año, el niño sigue con la que empezó hasta que un adulto lo
migre, y la migración queda en el historial. No es burocracia: el currículo
chileno está en disputa y la estructura 8+4 pasa a 6+6 en 2027.

⚠️ Esto cubre **una instalación por familia**. Alojar a familias de terceros es
otro proyecto: añade cuentas, facturación y responsabilidad legal sobre datos de
menores ajenos.

## El plan se corrige solo

El validador no es una puerta para el padre: es el bucle de retroalimentación de
la IA. El modelo **no reescribe el YAML** — propone operaciones de un vocabulario
cerrado de 11, que el código valida contra el currículo real antes de aplicar.

```
validar → proponer → aplicar → revalidar → repetir
```

Dos propiedades de seguridad:

- El modelo solo puede actuar con el vocabulario cerrado. Aunque alucine, no
  puede romper el plan: lo que no cuadra se descarta con un motivo, y ese motivo
  vuelve al modelo en la vuelta siguiente.
- **Una vuelta que empeore el plan se descarta entera.** Se trabaja sobre una
  copia y solo se adopta si los bloqueantes bajaron. Un bucle que puede degradar
  el currículo es peor que no tener bucle.

## Modelos configurables, por rol

No hay "un modelo": hay **roles** con exigencias y precios muy distintos.

| Rol | Cuándo corre | Qué necesita |
| --- | --- | --- |
| `tutor` | cada turno, con el niño delante | sostener el método socrático |
| `anclaje` | cada turno | ser barato; es una clasificación binaria |
| `rubrica` | al cerrar un bloque | criterio, con la rúbrica en contexto |
| `extraccion` | una vez por nivel | fidelidad al documento oficial |
| `enriquecimiento` | una vez por nivel | razonamiento: infiere los prerrequisitos |
| `items` | una vez por nivel | variedad |
| `resumen` | una vez por objetivo | densidad; **son el índice RAG** |

Cinco perfiles en `src/aula/config/modelos.yaml`:

| Perfil | Reparto | Coste |
| --- | --- | --- |
| `local` | todo en el Mac | 0 |
| **`plan-premium`** | **construir el plan en la nube, dar clases en local** | ~5-20 USD una vez por nivel, ~0/mes |
| `hibrido` | tutor en la nube, resto local | ~2-8 USD/mes |
| `nube` | todo en la nube | ~8-16 USD/mes |
| `lmstudio` | todo en LM Studio, con `modelo: auto` | 0 |

`plan-premium` es el reparto recomendado, y la razón es que **la calidad del plan
se acumula y la de una clase no**: un prerrequisito mal inferido envenena todas
las sesiones futuras de ese tema, mientras que un turno flojo se corrige en el
turno siguiente. Caro donde el error es permanente, barato donde es recuperable.

Lo único que hay que medir antes de fiarse: que el modelo local **sostenga el
método socrático** cuando el niño insista en que le den la respuesta. Si cede, el
tutor es la única pieza que vale la pena pagar — para eso está `hibrido`.

La configuración **traduce los términos de uso en código**: los roles marcados
con `•` procesan lo que dice un niño en vivo, y apuntarlos a un proveedor cuyos
términos exigen 18 años es un error de configuración, no una nota al pie.

Comparar local contra nube no exige editar archivos:

```bash
AULA_MODELO_TUTOR=gpt-5-mini AULA_PROVEEDOR_TUTOR=openai aula config show
aula config probe                 # ¿responde el servidor? ¿qué modelo tiene cargado?
```

`modelo: auto` le pregunta al servidor qué tiene cargado, así no hay que acertar
el identificador exacto que LM Studio le pone al modelo.

### Docker sí, pero el modelo fuera

Docker Desktop en macOS **no pasa la GPU al contenedor**: un modelo dentro caería
a 2-8 tokens/s, que es justo el caso inviable. LM Studio corre nativo en el Mac;
en Docker van la app, Postgres y el resto.

Y el detalle que rompe a todo el mundo: desde dentro de un contenedor `127.0.0.1`
es el contenedor, no el Mac. Por eso las URL locales llevan
`${AULA_HOST_LLM:-127.0.0.1}` y el `docker-compose.yml` fija
`AULA_HOST_LLM=host.docker.internal`.

## Correr

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

197 tests, ninguno toca la red:

```bash
pytest
```

Validar un plan:

```bash
aula curriculum validate ejemplos/cl-2basico-matematica.yaml
aula curriculum validate ejemplos/cl-2basico-roto.yaml
aula curriculum validate ejemplos/cl-2basico-roto.yaml --json
aula config show --perfil plan-premium
```

Base de datos local (Postgres + pgvector), cuando haga falta:

```bash
docker compose up -d
```

## El importador: descargar y entender son dos programas

```
  fetch  ─────────────►  datos/fuentes/  ─────────────►  extract
  (red, una vez)         caché + manifiesto              (sin red, n veces)
```

No es una separación estética. Descargar necesita salida a internet y permiso;
entender necesita iterar el prompt veinte veces. Juntarlos obliga a volver a bajar
el PDF cada vez que se ajusta una instrucción. Separados, **la caché es el
fixture**: se comparte la carpeta y la extracción se desarrolla offline contra
documentos reales.

```bash
aula curriculum fetch --pais CL --nivel 02        # única etapa que usa red
aula curriculum inspeccionar                      # qué hay dentro, sin modelo
aula curriculum extract --pais CL --nivel 02      # sin red
aula curriculum import --pais CL --nivel 02       # todo seguido
```

¿Ya tienes el PDF bajado a mano? Entra por el mismo camino:

```bash
aula curriculum adjuntar ~/Downloads/articles-18977_programa.pdf \
  --id cl-programa-matematica --titulo "Programa de Estudio — Matemática"
```

**No hay selectores.** El documento se lleva a texto plano y el modelo extrae los
objetivos con un esquema JSON como decodificación restringida. Nada depende de la
estructura HTML de `curriculumnacional.cl`, que cambia sin avisar.

### La procedencia se calcula, no se pregunta

Los códigos de objetivo se buscan con una expresión regular sobre el documento
completo **antes de la primera llamada al modelo**. De ahí salen la página, el
documento y la URL de cada objetivo. Un modelo puede alucinar un código; no puede
alucinar en qué página del PDF estaba.

De ahí salen las dos comprobaciones que sostienen la confianza:

- Un código que el modelo devuelve y **no está en el documento** se descarta,
  aunque tenga forma perfecta. Es el caso peligroso: el malformado se cae solo, el
  bien formado e inventado se cuela.
- La **cobertura** (cuántos de los códigos del documento acabaron en el currículo)
  tiene el denominador calculado por la expresión regular. Es la única métrica del
  importador que el modelo no puede inflar.

La confianza de cada objetivo sale de señales computables —aparece en la fuente,
dos trozos independientes coinciden, el largo es plausible, el nivel cuadra— nunca
de la opinión del modelo sobre sí mismo. Es lo que decide qué llega a la cola de
revisión del padre.

### Trocear sin partir objetivos

Los cortes caen solo donde empieza un código. Un objetivo queda entero en un trozo
o repetido en dos, nunca partido por la mitad. El solapamiento produce duplicados
a propósito: dos trozos que coinciden en el texto son **señal de confianza**.

### Y lo que ningún ministerio publica

Tres pases globales cierran lo que no se puede sacar mirando un trozo:
**prerrequisitos** (las Bases dan una lista, no un grafo; sin grafo no hay
secuencia), **resúmenes** (el índice RAG, escrito una vez y leído en cada turno
durante años) e **ítems** de evaluación (regla 4: lo que no se puede evaluar no se
puede dar por dominado).

## Decisiones que conviene conocer antes de tocar el código

- **El LLM nunca es la autoridad en matemáticas.** Los resultados los calcula y
  verifica SymPy. El modelo explica el veredicto, no lo emite.
- **El planificador decide el tema, no el modelo.** El LLM nunca elige qué se estudia.
- **El anclaje al plan es estructural, no un ruego en el prompt.** Cuatro capas:
  alcance cerrado por sesión, contrato de herramientas, RAG con filtro duro por
  objetivo, y chequeo de anclaje a la salida.
- **Se indexan resúmenes, no páginas.** Es lo que mantiene el contexto recuperado
  por debajo de 1.500 tokens por turno, que es donde un modelo local de 7-12B
  todavía rinde.
- **El currículo se fija por versión y por estudiante.** El currículo chileno está
  en disputa y la estructura 8+4 pasa a 6+6 en 2027; hornearlo en el código sería
  quedarse obsoleto en un año.
- **Se distribuye el importador, no el contenido importado.** El material del
  MINEDUC tiene licencias por recurso, mixtas. El repositorio lleva código y
  reglas de extracción, nunca PDFs de terceros.

## Este directorio va a un repo propio

Vive dentro de `tourcheck-releases` solo porque la sesión que lo creó estaba
limitada a ese repositorio. Para extraerlo conservando el historial:

```bash
git subtree split --prefix=aula -b aula-solo
```
