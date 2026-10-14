# Recogida de datos — Meta Standard

Cómo recoger los datos de un rango de fechas desde el conector Spellbinder y
dejarlos en ficheros que lee `pipeline.py`. Carga las herramientas con
ToolSearch: `select:mcp__Spellbinder__tournament_deck_search,mcp__Spellbinder__event_deck_get,mcp__Spellbinder__metagame_get`.

El conector admite como mucho 60 llamadas por minuto: si una llamada devuelve
"Rate limited", espera unos 40 segundos y repítela.

Directorio de salida: `RAW` (lo indica quien te encarga la tarea).

## 1. Decks de cada día → `RAW/decks/<fecha>.tsv`

Para CADA fecha del rango, y para cada canal:

- MTGO: `tournament_deck_search(format="standard", location="digital", date_from=<fecha>, date_to=<fecha>, placing_at_most=1000, per_page=25, page=N)`
- Papel: igual con `location="tabletop"`

Pide páginas hasta que `has_more` sea false. Fichero con cabecera y una fila
por deck, campos separados por TAB (11 columnas):

```
date	ch	ev	event	players	arch	arch_name	place	record	deck	deck_id
```

- `date`: `event.date`
- `ch`: `mtgo` si `event.source == "mtgo"`; `paper` si `event.location == "tabletop"`. **Descarta** cualquier deck digital cuyo `event.source` no sea `mtgo` (son eventos de Arena): no escribas esa fila.
- `ev`: los 8 primeros caracteres de `event.event_id`
- `event`: `event.name` (sin tabuladores)
- `players`: `0`
- `arch`: `archetype.slug` (si falta, `unknown`); `arch_name`: `archetype.name`
- `place`: `placement`; `record`: `record` tal cual (p. ej. `7-2-0`; si falta, `0-0-0`)
- `deck`: el último segmento de `url` (p. ej. `izzet-prowess-11gr9bczti`)
- `deck_id`: `deck_id` completo (UUID)

Si un día no tiene decks, crea igualmente el fichero solo con la cabecera.
Un fichero por fecha con las filas de los dos canales.

## 2. Listas del top 8 → `RAW/lists/<deck_id>.txt`

Si te han dado un fichero de pendientes (`todo.tsv`, columnas `deck_id` y
`header`), descarga solo esas listas. Si no, descarga la de cada deck del paso 1
con `place <= 8`.

Para cada una, llama a `event_deck_get(deck_id=<deck_id>, format="text")` y
escribe un fichero:

```
#deck <ch>|<date>|<arch>|<place>|<record>|<deck>|<event>
<contenido exacto del campo "decklist">
```

(con `todo.tsv`, la primera línea es exactamente la columna `header`). El
campo `decklist` ya trae `Main Deck:` y `Sideboard:`; cópialo línea a línea sin
cambiar cantidades ni nombres. Si una llamada falla dos veces, sáltala y anótalo.

## 3. Matriz de cruces en papel → `RAW/matrix.tsv`

Llama una vez a `metagame_get(format="standard", days="30", location="tabletop", include_matchups=true, top=10)`
y escribe (TAB entre campos, slugs sin el prefijo `standard-`):

```
P	<period.from>	<period.to>	<period.days>	<sample.total_matches>
A	<slug>	<display_name>	<deck_count>        ← una línea por matchup_matrix.archetypes, en su orden ("other" → slug other, nombre Otros)
K	<slug>	<colores separados por coma>        ← una línea por cada entrada de archetypes (la lista de arriba) que tenga colors
R	<slug fila>	<w/l> <w/l> ...                 ← una línea por arquetipo de la matriz: para cada columna, en el orden de las líneas A, "wins/losses" de la celda (fila, columna)
```

Usa los ids (`row_archetype_id`, `col_archetype_id`) para emparejar cada celda
con su fila y columna. Cada línea R debe tener tantos valores como líneas A.

## 4. Comprobación

Cuenta filas por fichero y listas escritas y devuelve ese recuento y cualquier
fallo. No inventes datos: si algo no viene en la respuesta, déjalo como se
indica arriba.
