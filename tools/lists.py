#!/usr/bin/env python3
"""Listas medias de cada arquetipo, para los Meta Decks del Game Tracker.

Lee los agregados diarios de data/cards/<fecha>.json (Top 8 en "l", puestos 9-16
en "l16") y escribe data/meta-decks.json: para cada arquetipo, la lista media de
los últimos días y el historial de cambios respecto a las versiones anteriores.

Lista media: entran las cartas que lleva al menos la mitad de las listas, con su
número de copias habitual (media redondeada entre las listas que la juegan), y se
ajusta a 60 + 15 con las siguientes más jugadas. Se usa el Top 8 de los últimos
14 días; si hay menos de MIN_LISTS listas se suma el Top 16 y luego se amplía la
ventana. Si un arquetipo deja de tener datos se conserva su última lista.

Uso:
  python3 -I tools/lists.py --data data [--today 2026-10-16]

Con --today, la ventana acaba el día anterior (el último que procesa la
actualización diaria); sin él, en la fecha más reciente de data/cards.
"""
import argparse, datetime as dt, glob, json, os, re

WINDOWS = (14, 30, 60, 120)
TIERS = (("l",), ("l", "l16"))          # Top 8; Top 8 + puestos 9-16
MIN_LISTS = 3
HISTORY = 10
TARGET = {"main": 60, "side": 15}
GENERIC = re.compile(r"^([wubrg]+|unknown|other)$")  # arquetipos genéricos por colores
BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
          "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
          "Snow-Covered Mountain", "Snow-Covered Forest"}
OUT = "meta-decks.json"


def load_cards(data_dir):
    docs = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "cards", "*.json"))):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        docs[doc.get("date") or os.path.basename(path)[:-5]] = doc
    return docs


def aggregate(docs, dates, tiers):
    """{arquetipo: {"n": listas, "paper": listas en papel, "c": {carta: [lm, qm, ls, qs]}}}"""
    out = {}
    for date in dates:
        doc = docs.get(date) or {}
        for tier in tiers:
            for ch, archs in (doc.get(tier) or {}).items():
                for arch, node in archs.items():
                    a = out.setdefault(arch, {"n": 0, "paper": 0, "c": {}})
                    a["n"] += node.get("n", 0)
                    if ch == "paper":
                        a["paper"] += node.get("n", 0)
                    for name, v in node.get("c", {}).items():
                        c = a["c"].setdefault(name, [0, 0, 0, 0])
                        for i in range(4):
                            c[i] += v[i]
    return out


def half_up(x):
    return int(x + 0.5)


def build_side(cards, n, section, main=None):
    """Lista media de una sección ("main" o "side") como {carta: copias}."""
    k_i, q_i = (0, 1) if section == "main" else (2, 3)
    target = TARGET[section]
    cands = [(name, v[k_i], v[q_i] / v[k_i]) for name, v in cards.items() if v[k_i]]
    cands.sort(key=lambda c: (-c[1], -c[2], c[0]))   # más listas, más copias, nombre
    avg = {name: a for name, _, a in cands}

    def cap(name):
        if name in BASICS:
            return 99
        main_avg = cards[name][1] / cards[name][0] if cards[name][0] else 0
        limit = 99 if main_avg > 4 else 4                # cartas sin límite de copias
        return limit - (main or {}).get(name, 0)

    qty = {}
    for name, k, a in cands:
        if 2 * k >= n and cap(name) > 0:
            qty[name] = min(cap(name), max(1, half_up(a)))
    total = sum(qty.values())

    # Sobran: se quitan copias empezando por las cartas menos jugadas.
    for name, k, a in sorted(cands, key=lambda c: (c[1], c[2], c[0])):
        while total > target and qty.get(name):
            qty[name] -= 1
            total -= 1
        if qty.get(name) == 0:
            del qty[name]
    # Faltan: entran las siguientes más jugadas…
    for name, k, a in cands:
        if total >= target:
            break
        if name not in qty and cap(name) > 0:
            add = min(cap(name), max(1, half_up(a)), target - total)
            qty[name] = add
            total += add
    # …y si aún faltan, una copia más a las que más perdieron al redondear.
    while total < target:
        grow = [nm for nm in qty if qty[nm] < cap(nm)]
        if not grow:
            break
        nm = max(grow, key=lambda nm: (avg[nm] - qty[nm], nm in BASICS, cards[nm][k_i]))
        qty[nm] += 1
        total += 1
    order = {name: i for i, (name, _, _) in enumerate(cands)}
    return dict(sorted(qty.items(), key=lambda kv: order[kv[0]]))


def consensus(node):
    main = build_side(node["c"], node["n"], "main")
    side = build_side(node["c"], node["n"], "side", main)
    return main, side


def pick(aggs, arch):
    """Primera ventana con MIN_LISTS listas; si ninguna llega, la primera con alguna."""
    first = None
    for days in WINDOWS:
        for tiers in TIERS:
            node = aggs[(days, tiers)].get(arch)
            if not node or not node["n"]:
                continue
            if node["n"] >= MIN_LISTS:
                return days, tiers, node
            first = first or (days, tiers, node)
    return first


def diff(old, new):
    out = {}
    for name in sorted(set(old) | set(new)):
        d = new.get(name, 0) - old.get(name, 0)
        if d:
            out[name] = d
    return out


def undo(lst, delta):
    out = dict(lst)
    for name, d in delta.items():
        out[name] = out.get(name, 0) - d
        if out[name] <= 0:
            out.pop(name)
    return out


def as_dict(pairs):
    return {name: q for name, q in pairs}


def build(docs, names, previous, end):
    aggs = {}
    for days in WINDOWS:
        dates = [(end - dt.timedelta(days=i)).isoformat() for i in range(days)]
        for tiers in TIERS:
            aggs[(days, tiers)] = aggregate(docs, dates, tiers)
    archs = sorted({a for agg in aggs.values() for a in agg if not GENERIC.match(a)})
    prev = (previous or {}).get("archetypes", {})
    out, changed = {}, []
    for arch in archs:
        picked = pick(aggs, arch)
        if not picked:
            continue
        days, tiers, node = picked
        main, side = consensus(node)
        if sum(main.values()) < 40:      # agregados incompletos: mejor no publicar
            continue
        old = prev.get(arch) or {}
        history = list(old.get("changes", []))
        since = old.get("since", end.isoformat())
        if old:
            base_main, base_side = as_dict(old["main"]), as_dict(old["side"])
            # Si ya se calculó hoy, se compara con la lista de antes de ese cálculo.
            if history and history[0]["date"] == end.isoformat():
                h = history.pop(0)
                base_main, base_side = undo(base_main, h.get("main", {})), undo(base_side, h.get("side", {}))
                since = history[0]["date"] if history else old.get("first", since)
            dm, ds = diff(base_main, main), diff(base_side, side)
            if dm or ds:
                history.insert(0, {"date": end.isoformat(), "main": dm, "side": ds})
                since = end.isoformat()
                changed.append(arch)
        out[arch] = {
            "name": (names.get(arch) or {}).get("n", arch),
            "lists": node["n"], "paper": node["paper"],
            "top": 16 if "l16" in tiers else 8, "days": days,
            "from": (end - dt.timedelta(days=days - 1)).isoformat(), "to": end.isoformat(),
            "main": [[name, q] for name, q in main.items()],
            "side": [[name, q] for name, q in side.items()],
            "since": since, "first": old.get("first", end.isoformat()),
            "changes": history[:HISTORY],
        }
    for arch, entry in prev.items():     # sin datos recientes: se conserva su última lista
        if arch not in out and not GENERIC.match(arch):
            out[arch] = entry
    return {"updated": end.isoformat(), "format": "standard", "archetypes": out}, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="carpeta data/ del repositorio")
    ap.add_argument("--today", default="", help="fecha de hoy (Madrid); la ventana acaba el día anterior")
    args = ap.parse_args()
    docs = load_cards(args.data)
    if not docs:
        raise SystemExit("No hay data/cards: nada que calcular")
    end = (dt.date.fromisoformat(args.today) - dt.timedelta(days=1)) if args.today else dt.date.fromisoformat(max(docs))
    names = {}
    idx = os.path.join(args.data, "index", "archs.json")
    if os.path.exists(idx):
        with open(idx, encoding="utf-8") as f:
            names = json.load(f).get("a", {})
    path = os.path.join(args.data, OUT)
    previous = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            previous = json.load(f)
    result, changed = build(docs, names, previous, end)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    print(f"Meta Decks: {len(result['archetypes'])} listas hasta {result['updated']}; "
          f"cambiaron {len(changed)}{': ' + ', '.join(changed) if changed else ''}")


if __name__ == "__main__":
    main()
