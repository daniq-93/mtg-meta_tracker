#!/usr/bin/env python3
"""Meta Standard — pipeline de procesado.

Lee los datos en bruto recogidos de Spellbinder y el estado actual de la base
de datos del panel, y genera los lotes de escritura (batches) para ArtifactData.

Uso:
  python3 -I pipeline.py --raw RAW_DIR --state STATE_DIR --out OUT_DIR \
      [--eval-dates 2026-10-12,2026-10-13] [--baseline-days 14]

RAW_DIR:
  decks/<fecha>.tsv   una fila por deck (ver COLS)
  lists/<cualquier>.txt  una lista por fichero, cabecera "#deck ..."
  matrix.json         salida de metagame_get (location=tabletop, include_matchups)
STATE_DIR: lo que devuelve ArtifactData list con out_dir (puede estar vacío).
OUT_DIR:   batch_01.json, batch_02.json ... + summary.md
"""
import argparse, json, os, re, glob, sys, datetime as dt
from collections import defaultdict

COLS = ["date", "ch", "ev", "event", "players", "arch", "arch_name", "place", "record", "deck", "deck_id"]
CARD_KEEP_DAYS = 120
# Eventos que no son Standard real (proxies, formatos de fantasía): se ignoran
BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
          "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
          "Snow-Covered Mountain", "Snow-Covered Forest"}
EXCLUDE_EVENT_RE = re.compile(r"fantasy|proxy|proxies|cube|commander", re.I)
BATCH_MAX_ENTRIES = 45
BATCH_MAX_BYTES = 850_000


def d(s):
    return dt.date.fromisoformat(s)


def fx(x):
    """Número con coma decimal (1 decimal)."""
    return f"{x:.1f}".replace(".", ",")


def slugify(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:150] or "x"


def parse_record(r):
    try:
        parts = [int(x) for x in r.split("-")]
        while len(parts) < 3:
            parts.append(0)
        return parts[0], parts[1], parts[2]
    except Exception:
        return 0, 0, 0


# ---------------------------------------------------------------- estado
def load_state(state_dir):
    """Devuelve {coleccion: {doc_id: (data, version)}}."""
    out = defaultdict(dict)
    if not state_dir or not os.path.isdir(state_dir):
        return out
    for path in glob.glob(os.path.join(state_dir, "**", "*.json"), recursive=True):
        rel = os.path.relpath(path, state_dir)
        parts = rel[:-5].split(os.sep)
        if len(parts) < 2:
            continue
        coll, doc_id = "/".join(parts[:-1]), parts[-1]
        with open(path) as f:
            raw = json.load(f)
        data, version = raw, None
        if isinstance(raw, dict):
            # formatos posibles: {"data": {...}, "version": n} o el documento tal cual
            if "data" in raw and isinstance(raw["data"], dict) and ("version" in raw or "id" in raw):
                data, version = raw["data"], raw.get("version")
            elif "version" in raw and "__name__" in raw:
                version = raw.pop("version")
            for k in ("__version__", "_version"):
                if k in raw and version is None:
                    version = raw.get(k)
        out[coll][doc_id] = (data, version)
    return out


# ---------------------------------------------------------------- crudo
def load_decks(raw_dir):
    rows = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "decks", "*.tsv"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip() or line.startswith("date\t") or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 9:
                    print(f"[aviso] fila incompleta en {path}: {line[:80]}", file=sys.stderr)
                    continue
                parts += ["-"] * (len(COLS) - len(parts))
                r = dict(zip(COLS, parts[: len(COLS)]))
                r["arch"] = r["arch"].removeprefix("standard-") or "unknown"
                try:
                    r["place"] = int(r["place"])
                except ValueError:
                    r["place"] = 999
                try:
                    r["players"] = int(r["players"])
                except ValueError:
                    r["players"] = 0
                if r["ch"] not in ("mtgo", "paper"):
                    continue
                if EXCLUDE_EVENT_RE.search(r["event"]):
                    continue
                rows.append(r)
    # deduplicar por (ev, place, arch, record)
    seen, uniq = set(), []
    for r in rows:
        k = (r["ev"], r["place"], r["arch"], r["record"], r["deck"])  # deck_id puede faltar
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


LINE_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")


def load_lists(raw_dir):
    lists = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "lists", "*.txt"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        lines = text.splitlines()
        if not lines or not lines[0].startswith("#deck"):
            print(f"[aviso] lista sin cabecera: {path}", file=sys.stderr)
            continue
        meta = lines[0][len("#deck"):].strip().split("|", 6)
        meta += [""] * (7 - len(meta))
        ch, date, arch, place, record, deck, event = meta[:7]
        if ch not in ("mtgo", "paper") or EXCLUDE_EVENT_RE.search(event or ""):
            continue
        section, main, side = "main", defaultdict(int), defaultdict(int)
        for ln in lines[1:]:
            low = ln.strip().lower()
            if low.startswith("sideboard"):
                section = "side"; continue
            if low.startswith("main") or low.startswith("deck") or not low:
                continue
            m = LINE_RE.match(ln)
            if not m:
                continue
            q, name = int(m.group(1)), m.group(2).strip()
            (main if section == "main" else side)[name] += q
        if not main:
            continue
        try:
            place = int(place)
        except ValueError:
            place = 999
        lists.append({"ch": ch, "date": date, "arch": (arch or "unknown").removeprefix("standard-"),
                      "place": place, "record": record, "deck": deck, "event": event,
                      "main": dict(main), "side": dict(side)})
    return lists


# ---------------------------------------------------------------- docs
def build_day_docs(decks):
    by_date = defaultdict(list)
    for r in decks:
        by_date[r["date"]].append(r)
    docs = {}
    for date, rows in by_date.items():
        a = {"mtgo": {}, "paper": {}}
        names, events = {}, {}
        for r in rows:
            ch, s = r["ch"], r["arch"]
            names[s] = r["arch_name"]
            w, l, dr = parse_record(r["record"])
            cell = a[ch].setdefault(s, [0, 0, 0, 0, 0, 0])  # decks, W, L, D, top8, 1º
            cell[0] += 1; cell[1] += w; cell[2] += l; cell[3] += dr
            if r["place"] <= 8: cell[4] += 1
            if r["place"] == 1: cell[5] += 1
            ev = events.setdefault(r["ev"], {"id": r["ev"], "n": r["event"], "ch": ch,
                                             "p": r["players"], "d": 0, "w": None})
            ev["d"] += 1
            ev["p"] = max(ev["p"], r["players"])
            if r["place"] == 1:
                ev["w"] = s
        docs[date] = {"date": date, "a": a, "names": names,
                      "ev": sorted(events.values(), key=lambda e: (e["ch"], e["n"]))}
    return docs


def build_card_docs(lists, existing=None):
    """Agrega las listas por fecha. Si ya hay un documento de esa fecha en la base de
    datos, añade solo las listas cuyo deck no estaba (la agregación es aditiva)."""
    existing = existing or {}
    by_date = defaultdict(list)
    for L in lists:
        by_date[L["date"]].append(L)
    docs = {}
    for date, ls in by_date.items():
        base = json.loads(json.dumps(existing.get(date) or {"date": date, "l": {}, "top": []}))
        l, top = base.setdefault("l", {}), base.setdefault("top", [])
        have = {t.get("u") for t in top}
        added = 0
        for L in ls:
            if L["deck"] and L["deck"] in have:
                continue
            have.add(L["deck"])
            added += 1
            node = l.setdefault(L["ch"], {}).setdefault(L["arch"], {"n": 0, "c": {}})
            node["n"] += 1
            for name, q in L["main"].items():
                c = node["c"].setdefault(name, [0, 0, 0, 0])
                c[0] += 1; c[1] += q
            for name, q in L["side"].items():
                c = node["c"].setdefault(name, [0, 0, 0, 0])
                c[2] += 1; c[3] += q
            top.append({"ch": L["ch"], "a": L["arch"], "p": L["place"], "r": L["record"],
                        "u": L["deck"], "e": L["event"]})
        if not added:
            continue
        top.sort(key=lambda t: (t["e"], t["p"]))
        base["date"] = date
        docs[date] = base
    return docs


def write_todo(decks, card_state, path):
    """Escribe las cabeceras de las listas de top 8 que faltan por descargar."""
    have = defaultdict(set)
    for ds, (doc, _v) in card_state.items():
        for t in (doc or {}).get("top", []):
            have[ds].add(t.get("u"))
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        f.write("deck_id\theader\n")
        for r in decks:
            if r["place"] > 8 or r["deck"] in have[r["date"]]:
                continue
            if not r.get("deck_id") or r["deck_id"] == "-":
                print(f"[aviso] falta deck_id para {r['deck']}", file=sys.stderr)
                continue
            hdr = f"#deck {r['ch']}|{r['date']}|{r['arch']}|{r['place']}|{r['record']}|{r['deck']}|{r['event']}"
            f.write(f"{r['deck_id']}\t{hdr}\n")
            n += 1
    print(f"Listas pendientes: {n} (en {path})")


# ---------------------------------------------------------------- alertas
def window_dates(end, days):
    return {(end - dt.timedelta(days=i)).isoformat() for i in range(days)}


def arch_share(day_docs, dates, ch):
    tot, per = 0, defaultdict(int)
    for ds in dates:
        doc = day_docs.get(ds)
        if not doc:
            continue
        for s, cell in doc["a"].get(ch, {}).items():
            per[s] += cell[0]; tot += cell[0]
    return tot, per


def cards_in(card_docs, dates, arch=None):
    """{card: {"main": decks, "side": decks, "archs": {arch: n}}} y nº de listas."""
    res, n = {}, 0
    for ds in dates:
        doc = card_docs.get(ds)
        if not doc:
            continue
        for ch, archs in doc["l"].items():
            for s, node in archs.items():
                if arch and s != arch:
                    continue
                n += node["n"]
                for card, c in node["c"].items():
                    e = res.setdefault(card, {"main": 0, "side": 0, "archs": defaultdict(int)})
                    e["main"] += c[0]; e["side"] += c[2]
                    e["archs"][s] += max(c[0], c[2])
    return res, n


def compute_alerts(day_docs, card_docs, names, first_card, first_arch, eval_dates, baseline_until, today):
    alerts = {}

    def add(aid, **kw):
        aid = slugify(aid)[:190]
        alerts[aid] = kw

    def nm(s):
        return names.get(s, s)

    for D in sorted(eval_dates):
        if D < baseline_until:
            continue
        Dd = d(D)
        cdoc = card_docs.get(D)
        prev28 = window_dates(Dd - dt.timedelta(days=1), 28)
        # 1. cartas nuevas en el formato
        if cdoc:
            today_cards, _ = cards_in(card_docs, {D})
            for card, e in today_cards.items():
                if first_card.get(card) == D and card not in BASICS:
                    archs = ", ".join(nm(s) for s in sorted(e["archs"], key=lambda s: -e["archs"][s]))
                    where = "main" if e["main"] else "banquillo"
                    add(f"newcard-{card}", date=D, type="new_card", sev="high" if e["main"] else "med",
                        card=card, arch=next(iter(e["archs"]), None),
                        title=f"Carta nueva en el formato: {card}",
                        detail=f"Aparece por primera vez en una lista de top 8 ({where}), en {archs}.")
            # 2. cartas nuevas dentro de un arquetipo (una alerta por arquetipo y día)
            per_arch = defaultdict(lambda: {"main": [], "side": [], "nb": 0, "ch": set()})
            for ch, archs in cdoc["l"].items():
                for s, node in archs.items():
                    before, nb = cards_in(card_docs, prev28, arch=s)
                    if nb < 4:
                        continue
                    for card, c in node["c"].items():
                        if card in BASICS or card in before or first_card.get(card) == D:
                            continue
                        e = per_arch[s]
                        e["nb"] = nb; e["ch"].add(ch)
                        if c[0] > 0:
                            if card not in e["main"]: e["main"].append(card)
                        elif card not in e["side"] and card not in e["main"]:
                            e["side"].append(card)
            for s, e in per_arch.items():
                cards = e["main"] + e["side"]
                if not cards:
                    continue
                parts = []
                if e["main"]: parts.append("main: " + ", ".join(e["main"]))
                if e["side"]: parts.append("banquillo: " + ", ".join(e["side"]))
                title = (f"{nm(s)} incorpora {cards[0]}" if len(cards) == 1
                         else f"{nm(s)} incorpora {len(cards)} cartas nuevas")
                add(f"archcard-{s}-{D}", date=D, type="arch_card", sev="med" if e["main"] else "low",
                    arch=s, ch="+".join(sorted(e["ch"])), cards=cards, card=cards[0], title=title,
                    detail=(f"En listas de top 8 del {D} ({'; '.join(parts)}). "
                            f"No aparecían en las {e['nb']} listas de este arquetipo de los 28 días anteriores."))
        # 3. arquetipo nuevo
        ddoc = day_docs.get(D)
        if ddoc:
            for ch, archs in ddoc["a"].items():
                for s, cell in archs.items():
                    if first_arch.get(s) == D and s not in ("unknown", "other") and (cell[4] > 0 or cell[0] >= 3):
                        add(f"newarch-{s}", date=D, type="new_arch", sev="high", arch=s, ch=ch,
                            title=f"Arquetipo nuevo: {nm(s)}",
                            detail=f"Primera aparición registrada: {cell[0]} deck(s), {cell[4]} en top 8 ({'MTGO' if ch == 'mtgo' else 'papel'}).")
            # 4. ganador sorpresa
            for ev in ddoc["ev"]:
                w = ev.get("w")
                if not w or ev["d"] < 16:
                    continue
                tot, per = arch_share(day_docs, prev28, ev["ch"])
                if tot < 60:
                    continue
                share = 100 * per.get(w, 0) / tot
                if share < 2.0:
                    add(f"surprise-{ev['id']}", date=D, type="surprise", sev="med", arch=w, ch=ev["ch"],
                        title=f"{nm(w)} gana {ev['n']}",
                        detail=f"Era el {fx(share)}% del meta de {'MTGO' if ev['ch'] == 'mtgo' else 'papel'} en los 28 días anteriores.")

    # 5. subidas y bajadas de cuota (una vez por semana y arquetipo)
    T = d(today)
    if today >= baseline_until:
        last = window_dates(T, 7)
        prev = window_dates(T - dt.timedelta(days=7), 7)
        iso = T.isocalendar()
        for ch in ("mtgo", "paper"):
            t1, p1 = arch_share(day_docs, last, ch)
            t0, p0 = arch_share(day_docs, prev, ch)
            if t1 < 30 or t0 < 30:
                continue
            for s in set(p1) | set(p0):
                if s in ("unknown", "other"):
                    continue
                if max(p1.get(s, 0), p0.get(s, 0)) < 4:
                    continue
                s1, s0 = 100 * p1.get(s, 0) / t1, 100 * p0.get(s, 0) / t0
                delta = s1 - s0
                if abs(delta) >= 3.0:
                    up = delta > 0
                    add(f"share-{ch}-{s}-{iso[0]}w{iso[1]}-{'up' if up else 'down'}", date=today,
                        type="share_up" if up else "share_down", sev="high" if abs(delta) >= 5 else "med",
                        arch=s, ch=ch,
                        title=f"{nm(s)} {'sube' if up else 'baja'} {fx(abs(delta))} puntos en {'MTGO' if ch == 'mtgo' else 'papel'}",
                        detail=f"Pasa del {fx(s0)}% al {fx(s1)}% (últimos 7 días frente a los 7 anteriores; {t1} decks).")
    return alerts


# ---------------------------------------------------------------- matriz
def build_matrix(raw_dir):
    """Lee RAW/matrix.tsv (formato compacto, ver COLLECT.md)."""
    p = os.path.join(raw_dir, "matrix.tsv")
    if not os.path.exists(p):
        return None
    period, archs, colors, rows = {}, [], {}, {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if not parts or not parts[0]:
                continue
            t = parts[0]
            if t == "P" and len(parts) >= 5:
                period = {"from": parts[1], "to": parts[2], "days": int(parts[3]), "matches": int(parts[4])}
            elif t == "A" and len(parts) >= 4:
                archs.append({"s": parts[1].removeprefix("standard-"), "n": parts[2], "d": int(parts[3])})
            elif t == "K" and len(parts) >= 3:
                colors[parts[1].removeprefix("standard-")] = [c for c in parts[2].split(",") if c]
            elif t == "R" and len(parts) >= 3:
                rows[parts[1].removeprefix("standard-")] = parts[2].split()
    order = [a["s"] for a in archs]
    cells = []
    for r, vals in rows.items():
        if len(vals) != len(order):
            print(f"[aviso] fila de matriz {r} con {len(vals)} celdas (esperadas {len(order)})", file=sys.stderr)
        for k, v in zip(order, vals):
            try:
                w, l = (int(x) for x in v.split("/"))
            except ValueError:
                continue
            cells.append([r, k, w, l])
    if not archs:
        return None
    return {**period, "archs": archs, "cells": cells, "colors": colors}


# ---------------------------------------------------------------- repositorio
def _dump(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_repo(repo, writes):
    base = os.path.join(repo, "data")
    for w in writes:
        path = os.path.join(base, w["collection"], f"{w['doc_id']}.json")
        if w["op"] == "delete":
            if os.path.exists(path):
                os.remove(path)
        else:
            _dump(path, w["data"])


BUNDLE_DAYS = 400
BUNDLE_CARD_DAYS = 75
BUNDLE_ALERTS = 400


def build_bundles(datadir):
    """core.json (todo menos las listas) y cards-recent.json para la app web."""
    st = load_state(datadir)
    days = {k: v[0] for k, v in sorted(st.get("days", {}).items())[-BUNDLE_DAYS:]}
    cards = {k: v[0] for k, v in sorted(st.get("cards", {}).items())[-BUNDLE_CARD_DAYS:]}
    alerts = [dict(v[0], id=k) for k, v in st.get("alerts", {}).items()]
    sev = {"high": 0, "med": 1, "low": 2}
    alerts.sort(key=lambda a: (a.get("date", ""), -sev.get(a.get("sev"), 3)), reverse=True)
    core = {
        "status": (st.get("meta", {}).get("status") or ({}, None))[0],
        "days": days,
        "archIdx": (st.get("index", {}).get("archs") or ({}, None))[0].get("a", {}),
        "cardIdx": (st.get("index", {}).get("cards") or ({}, None))[0].get("c", {}),
        "matrix": (st.get("matrix", {}).get("paper") or (None, None))[0],
        "alerts": alerts[:BUNDLE_ALERTS],
        "cardDates": sorted(cards),
    }
    _dump(os.path.join(datadir, "core.json"), core)
    _dump(os.path.join(datadir, "cards-recent.json"), cards)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--state", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--repo", default="", help="carpeta del repositorio: lee y escribe en <repo>/data")
    ap.add_argument("--eval-dates", default="")
    ap.add_argument("--baseline-days", type=int, default=14)
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--todo-lists", default="", help="solo escribe las listas pendientes y termina")
    ap.add_argument("--versions", default="", help="fichero con líneas 'coleccion/doc_id version'")
    args = ap.parse_args()

    if args.repo and not args.state:
        args.state = os.path.join(args.repo, "data")
    if not args.out:
        args.out = os.path.join(args.repo, ".run") if args.repo else "out"
    state = load_state(args.state)
    for skip in ("core", "cards-recent"):
        state.pop(skip, None)
    vers = {}
    if args.versions and os.path.exists(args.versions):
        with open(args.versions) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2 or "/" not in parts[0]:
                    continue
                coll, doc_id = parts[0].rsplit("/", 1)
                vers[(coll, doc_id)] = int(parts[1])
                old = state.get(coll, {}).get(doc_id)
                if old:
                    state[coll][doc_id] = (old[0], int(parts[1]))
    decks = load_decks(args.raw)
    if args.todo_lists:
        write_todo(decks, state.get("cards", {}), args.todo_lists)
        return
    lists = load_lists(args.raw)
    new_days = build_day_docs(decks)
    new_cards = build_card_docs(lists, {k: v[0] for k, v in state.get("cards", {}).items()})

    # historia completa = estado + lo nuevo (lo nuevo manda para las fechas recogidas)
    day_docs = {k: v[0] for k, v in state.get("days", {}).items()}
    card_docs = {k: v[0] for k, v in state.get("cards", {}).items()}
    day_docs.update(new_days)
    card_docs.update(new_cards)

    names = {}
    for ds in sorted(day_docs):
        names.update(day_docs[ds].get("names", {}))

    old_index = state.get("index", {})
    arch_idx = dict((old_index.get("archs") or ({}, None))[0].get("a", {}))
    for ds in sorted(day_docs):
        for ch, archs in day_docs[ds]["a"].items():
            for s, cell in archs.items():
                e = arch_idx.setdefault(s, {"n": names.get(s, s), "f": ds, "l": ds})
                e["n"] = names.get(s, e["n"])
                e["f"] = min(e["f"], ds); e["l"] = max(e["l"], ds)
    first_arch = {s: e["f"] for s, e in arch_idx.items()}

    card_idx = dict((old_index.get("cards") or ({}, None))[0].get("c", {}))
    for ds in sorted(card_docs):
        for ch, archs in card_docs[ds]["l"].items():
            for s, node in archs.items():
                for card in node["c"]:
                    if card not in card_idx or ds < card_idx[card]:
                        card_idx[card] = ds

    status_old = (state.get("meta", {}).get("status") or ({}, None))[0]
    all_dates = sorted(set(day_docs) | set(card_docs))
    since = min([status_old.get("since") or "9999"] + all_dates[:1])
    baseline_until = (d(since) + dt.timedelta(days=args.baseline_days)).isoformat()
    eval_dates = [x for x in args.eval_dates.split(",") if x] or sorted(set(new_days) | set(new_cards))

    alerts = compute_alerts(day_docs, card_docs, names, card_idx, first_arch,
                            eval_dates, baseline_until, max(all_dates) if all_dates else args.today)
    existing_alerts = state.get("alerts", {})
    fresh = {k: v for k, v in alerts.items() if k not in existing_alerts}

    matrix = build_matrix(args.raw)

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    status = {"updated": now, "since": since, "baseline_until": baseline_until,
              "through": max(all_dates) if all_dates else None,
              "days": len(day_docs),
              "decks_last_run": len(decks), "lists_last_run": len(lists),
              "alerts_last_run": len(fresh),
              "last_dates": sorted(set(new_days) | set(new_cards))}

    # ---- escrituras
    writes = []

    def put(coll, doc_id, data):
        old = state.get(coll, {}).get(doc_id)
        entry = {"op": "set", "collection": coll, "doc_id": doc_id, "data": data}
        v = (old[1] if old else None) or vers.get((coll, doc_id))
        if v is not None:
            entry["if_version"] = v
        elif old:
            entry["_needs_version"] = True
        writes.append(entry)

    for ds, doc in sorted(new_days.items()):
        put("days", ds, doc)
    for ds, doc in sorted(new_cards.items()):
        put("cards", ds, doc)
    put("index", "archs", {"a": arch_idx})
    put("index", "cards", {"c": card_idx})
    if matrix:
        put("matrix", "paper", matrix)
    for aid, a in sorted(fresh.items()):
        a["created"] = now
        put("alerts", aid, a)
    put("meta", "status", status)

    # poda de cartas antiguas
    cutoff = (d(args.today) - dt.timedelta(days=CARD_KEEP_DAYS)).isoformat()
    for ds, (data, ver) in state.get("cards", {}).items():
        if ds < cutoff:
            e = {"op": "delete", "collection": "cards", "doc_id": ds}
            if ver is not None:
                e["if_version"] = ver
            writes.append(e)

    if args.repo:
        write_repo(args.repo, writes)
        build_bundles(os.path.join(args.repo, "data"))
        batches = []
    else:
        # ---- partir en lotes: cada documento va a su propio fichero y el lote lo referencia
        os.makedirs(args.out, exist_ok=True)
        docdir = os.path.join(os.path.abspath(args.out), "docs")
        for f in glob.glob(os.path.join(args.out, "batch_*.json")) + glob.glob(os.path.join(docdir, "*.json")):
            os.remove(f)
        os.makedirs(docdir, exist_ok=True)
        batches, cur, size = [], [], 0
        for w in writes:
            s = len(json.dumps(w.get("data", {}), ensure_ascii=False).encode()) + 200
            if "data" in w:
                fp = os.path.join(docdir, f"{w['collection']}__{w['doc_id']}.json")
                with open(fp, "w") as f:
                    json.dump(w.pop("data"), f, ensure_ascii=False)
                w["file_path"] = fp
            w.pop("_needs_version", None)
            if cur and (len(cur) >= BATCH_MAX_ENTRIES or size + s > BATCH_MAX_BYTES):
                batches.append(cur); cur, size = [], 0
            cur.append(w); size += s
        if cur:
            batches.append(cur)
        for i, b in enumerate(batches, 1):
            with open(os.path.join(args.out, f"batch_{i:02d}.json"), "w") as f:
                json.dump(b, f, ensure_ascii=False, indent=0)


    needs = [f"{w['collection']}/{w['doc_id']}" for b in batches for w in b
             if w["op"] in ("set", "delete") and w.get("if_version") is None
             and (w["doc_id"] in state.get(w["collection"], {}))]
    sev_order = {"high": 0, "med": 1, "low": 2}
    lines = [f"# Resumen del procesado ({now})",
             f"- Decks leídos: {len(decks)} · listas: {len(lists)} · fechas: {', '.join(status['last_dates']) or 'ninguna'}",
             f"- Histórico: {len(day_docs)} días desde {since}; alertas activas desde {baseline_until}",
             (f"- Ficheros escritos en el repositorio: {len(writes)}" if args.repo else
              f"- Lotes de escritura: {len(batches)} ({len(writes)} operaciones)"),
             f"- Alertas nuevas: {len(fresh)}"]
    for aid, a in sorted(fresh.items(), key=lambda kv: (sev_order.get(kv[1]['sev'], 3), kv[1]['date'])):
        lines.append(f"  - [{a['sev']}] {a['title']} — {a['detail']}")
    if needs:
        lines.append(f"- AVISO: faltan versiones para: {', '.join(needs)}")
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "summary.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
