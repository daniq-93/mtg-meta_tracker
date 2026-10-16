"""Pruebas de lists.py: python3 -m unittest discover -s tools"""
import datetime as dt, unittest

import lists

END = dt.date(2026, 10, 15)


def deck(main, side):
    """Una lista como agregado de un solo deck."""
    c = {}
    for name, q in main.items():
        c.setdefault(name, [0, 0, 0, 0])[:2] = [1, q]
    for name, q in side.items():
        c.setdefault(name, [0, 0, 0, 0])[2:] = [1, q]
    return {"n": 1, "c": c}


def merge(*nodes):
    out = {"n": 0, "c": {}}
    for nd in nodes:
        out["n"] += nd["n"]
        for name, v in nd["c"].items():
            c = out["c"].setdefault(name, [0, 0, 0, 0])
            for i in range(4):
                c[i] += v[i]
    return out


BASE = {"Forest": 20, "Llanowar Elves": 4, "Hydra": 4, "Ranger": 4, "Bear": 4, "Wolf": 4,
        "Elk": 4, "Giant": 4, "Druid": 4, "Spider": 4, "Growth": 4}
SIDE = {"Naturalize": 3, "Plummet": 4, "Fog": 4, "Duress": 4}


def doc(date, ch, tier, arch, node):
    return {"date": date, tier: {ch: {arch: node}}}


class Consensus(unittest.TestCase):
    def test_lista_de_un_deck_es_ese_deck(self):
        main, side = lists.consensus(deck(BASE, SIDE))
        self.assertEqual(main, BASE)
        self.assertEqual(side, SIDE)

    def test_entran_las_de_la_mitad_con_copias_habituales(self):
        a = deck({**BASE, "Growth": 2, "Shock": 2}, SIDE)
        b = deck({**BASE, "Growth": 3, "Shock": 1}, SIDE)
        c = deck({**BASE, "Growth": 1, "Rare": 3}, SIDE)
        main, side = lists.consensus(merge(a, b, c))
        self.assertEqual(sum(main.values()), 60)
        self.assertEqual(sum(side.values()), 15)
        self.assertNotIn("Rare", main)            # solo en 1 de 3 listas
        self.assertEqual(main["Shock"], 2)         # 2 de 3 listas, media 1,5 → 2
        self.assertEqual(main["Forest"] + main["Growth"], 22)

    def test_nunca_mas_de_cuatro_entre_main_y_side(self):
        a = deck({**BASE, "Growth": 3, "Bear": 3, "Elk": 3, "Wolf": 3, "Forest": 24}, {**SIDE, "Bear": 3, "Fog": 1})
        main, side = lists.consensus(merge(a, a))
        self.assertLessEqual(main.get("Bear", 0) + side.get("Bear", 0), 4)
        self.assertEqual(sum(side.values()), 15)


class Build(unittest.TestCase):
    def docs(self, extra=None, node=None):
        d = {}
        for i in range(4):
            date = (END - dt.timedelta(days=i)).isoformat()
            d[date] = doc(date, "mtgo", "l", "mono-green", node or deck(BASE, SIDE))
        d.update(extra or {})
        return d

    def test_ventana_y_genericos(self):
        docs = self.docs({"2026-10-01": {"date": "2026-10-01", "l": {"mtgo": {"wu": deck(BASE, SIDE)}}}})
        out, _ = lists.build(docs, {"mono-green": {"n": "Mono-Green"}}, None, END)
        e = out["archetypes"]["mono-green"]
        self.assertEqual((e["name"], e["lists"], e["top"], e["days"], e["from"]), ("Mono-Green", 4, 8, 14, "2026-10-02"))
        self.assertNotIn("wu", out["archetypes"])

    def test_suma_el_top16_antes_de_ampliar_dias(self):
        date = END.isoformat()
        docs = {date: {"date": date, "l": {"paper": {"rare-deck": deck(BASE, SIDE)}},
                       "l16": {"mtgo": {"rare-deck": merge(deck(BASE, SIDE), deck(BASE, SIDE))}}}}
        out, _ = lists.build(docs, {}, None, END)
        e = out["archetypes"]["rare-deck"]
        self.assertEqual((e["lists"], e["paper"], e["top"], e["days"]), (3, 1, 16, 14))

    def test_historial_de_cambios(self):
        first, _ = lists.build(self.docs(), {}, None, END)
        self.assertEqual(first["archetypes"]["mono-green"]["changes"], [])
        nxt = END + dt.timedelta(days=1)
        docs = self.docs(node=deck({**BASE, "Growth": 2, "Shock": 2}, SIDE))
        second, changed = lists.build(docs, {}, first, nxt)
        e = second["archetypes"]["mono-green"]
        self.assertEqual(changed, ["mono-green"])
        self.assertEqual(e["since"], nxt.isoformat())
        self.assertEqual(e["changes"], [{"date": nxt.isoformat(), "main": {"Growth": -2, "Shock": 2}, "side": {}}])
        # Repetir el mismo día no duplica el cambio; si vuelve a la lista de antes, desaparece.
        again, _ = lists.build(docs, {}, second, nxt)
        self.assertEqual(again["archetypes"]["mono-green"]["changes"], e["changes"])
        back, changed = lists.build(self.docs(), {}, second, nxt)
        self.assertEqual((back["archetypes"]["mono-green"]["changes"], changed), ([], []))
        self.assertEqual(back["archetypes"]["mono-green"]["since"], END.isoformat())

    def test_sin_datos_conserva_la_ultima_lista(self):
        first, _ = lists.build(self.docs(), {}, None, END)
        later, _ = lists.build({}, {}, first, END + dt.timedelta(days=200))
        self.assertEqual(later["archetypes"]["mono-green"], first["archetypes"]["mono-green"])


if __name__ == "__main__":
    unittest.main()
