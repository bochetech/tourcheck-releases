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
| **Validador de 12 reglas duras** | ✅ funciona, 31 tests |
| Índice de legibilidad en español (Fernández Huerta) | ✅ funciona |
| Lectura/escritura YAML diffeable | ✅ funciona |
| CLI `aula curriculum validate` | ✅ funciona |
| **Configuración de modelos por rol** | ✅ funciona, 4 perfiles |
| Importador desde `curriculumnacional.cl` | ⬜ siguiente |
| Bucle de auto-reparación | ⬜ siguiente |
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

Cuatro perfiles en `config/modelos.yaml`:

| Perfil | Reparto | Coste |
| --- | --- | --- |
| `local` | todo en el Mac | 0 |
| **`plan-premium`** | **construir el plan en la nube, dar clases en local** | ~5-20 USD una vez por nivel, ~0/mes |
| `hibrido` | tutor en la nube, resto local | ~2-8 USD/mes |
| `nube` | todo en la nube | ~8-16 USD/mes |

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
```

## Correr

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                                                   # 43 tests
aula curriculum validate ejemplos/cl-2basico-matematica.yaml   # pasa
aula curriculum validate ejemplos/cl-2basico-roto.yaml         # 4 bloqueantes
aula curriculum validate ejemplos/cl-2basico-roto.yaml --json  # para el bucle

aula config show --perfil plan-premium                   # modelos por rol
```

Base de datos local (Postgres + pgvector), cuando haga falta:

```bash
docker compose up -d
```

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
