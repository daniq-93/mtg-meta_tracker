# Actualización diaria — Meta Standard

La app web vive en este repositorio (`daniq-93/mtg-meta_tracker`) y se publica con
GitHub Pages en https://daniq-93.github.io/mtg-meta_tracker/. Los datos están en `data/`
y el procesado en `tools/pipeline.py`. Habla y escribe en español.

## 0. Preparación
- ToolSearch: `select:SendUserMessage,mcp__Spellbinder__tournament_deck_search,mcp__Spellbinder__event_deck_get,mcp__Spellbinder__metagame_get`
- El clon del repositorio es `R` = `/home/claude/mtg-meta_tracker` (ya viene clonado en las tareas programadas). Antes de nada: `git -C R fetch origin main && git -C R checkout -B main origin/main`.
- Trabaja en `R/work` (está en `.gitignore`).
- Lee `R/tools/COLLECT.md` entero antes de empezar.

## 1. Fechas
Fecha de hoy en Madrid = H. Procesa las 3 fechas anteriores: H-3, H-2 y H-1.

## 2. Recogida → `R/work/raw`
1. Paso 1 de COLLECT.md (decks) para las 3 fechas.
2. `python3 -I R/tools/pipeline.py --raw R/work/raw --repo R --todo-lists R/work/raw/todo.tsv`
3. Paso 2 de COLLECT.md solo para las listas de `todo.tsv`.
4. Paso 3 de COLLECT.md (matriz de papel).

## 3. Procesado
`python3 -I R/tools/pipeline.py --raw R/work/raw --repo R --today H`

Escribe los ficheros de `data/` (incluidos `core.json` y `cards-recent.json`, que lee la app)
y el resumen en `R/.run/summary.md`.

## 4. Publicación
```
cd R
git add data
git commit -m "Datos hasta <fecha más reciente procesada>"
git fetch origin main && git rebase origin/main
git push origin HEAD:main
```
Si no hay cambios en `data/`, no hagas commit. Si el push falla, reintenta una vez tras
`git fetch` + `git rebase`. No toques ningún fichero fuera de `data/`.

## 5. Aviso
Con `SendUserMessage`, envía un resumen corto en español con lo que dice `summary.md`:
- "Meta Standard actualizado: N decks, M listas nuevas (fechas)".
- Si hubo alertas nuevas, lístalas (máximo 8, primero las de gravedad high).
- Cualquier fallo de recogida o de publicación.
Si no hubo torneos nuevos ni alertas, una sola línea basta.
