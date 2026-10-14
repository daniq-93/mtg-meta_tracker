# Meta Standard

App web con el meta de Magic: The Gathering Standard (papel y MTGO) para el grupo de testeo:
cuotas de arquetipos, cruces en papel, tendencias, tecnología de las listas de top 8 y alertas.

**Abrir la app:** https://daniq-93.github.io/mtg-meta_tracker/

En el móvil se puede instalar como una app:
- **iPhone (Safari):** Compartir → Añadir a pantalla de inicio.
- **Android (Chrome):** menú ⋮ → Instalar app (o el botón "Instalar" que aparece en la propia página).

Los datos salen de los torneos públicos indexados por Spellbinder y se actualizan cada día
sobre las 6:00 (hora de Madrid).

## Estructura
- `index.html`, `manifest.webmanifest`, `sw.js`, `icons/`: la app.
- `data/`: histórico por día (`days/`), listas agregadas (`cards/`), índices, matriz de cruces,
  alertas y los ficheros que lee la app (`core.json`, `cards-recent.json`).
- `tools/`: procesado (`pipeline.py`) e instrucciones de la actualización diaria (`RUN.md`, `COLLECT.md`).
