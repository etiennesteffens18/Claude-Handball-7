#!/usr/bin/env python3
"""Holt Spiele, Tabellen und Spielberichte und legt sie als JSON für die Web-App ab.

Quellen
  handballnet  – https://www.handball.net/api/new/…  (DHB-Ligen, HVNB/nuLiga u. a.)
  h4a          – https://spo.handball4all.de/service/if_g_json.php  (BWHV, solange
                 der Verband nicht auf handball.net umgestellt ist)

Beide Schnittstellen sind die, mit denen die Webseiten selbst arbeiten. Es gibt
keine offizielle Doku – deshalb wird hier alles tolerant gelesen und lieber eine
Lücke gelassen als etwas erfunden. Nur Python-Standardbibliothek.

Aufruf:  python scripts/abruf.py                 (echter Abruf)
         python scripts/abruf.py --offline DIR   (Testdaten statt Netz)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
CONFIG = WURZEL / "config" / "ligen.json"
AUSGABE = WURZEL / "docs" / "data"
CACHE = WURZEL / "cache" / "berichte.json"

HBNET = "https://www.handball.net/api/new"
H4A = "https://spo.handball4all.de/service/if_g_json.php"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 handball-app/1.0 (privat)")
PAUSE = 0.5            # Rücksicht auf die Quelle
MAX_BERICHTE = 60      # höchstens so viele neue Spielberichte je Lauf

STATUS = {             # handball.net liefert den Status auf Spanisch (iSquad-Backend)
    "Pendiente": "geplant", "Finalizado": "beendet", "En juego": "live",
    "Aplazado": "verlegt", "Suspendido": "abgesetzt", "Anulado": "annulliert",
}

OFFLINE: Path | None = None
_letzter = 0.0


# ----------------------------------------------------------------------- Netz
def hole(url: str, params: dict | None = None, referer: str = "https://www.handball.net/"):
    """JSON holen – oder im Offline-Modus aus einer Testdatei lesen."""
    global _letzter
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    if OFFLINE is not None:
        name = re.sub(r"[^a-z0-9]+", "_", (url.split("/api/new/")[-1].split("/service/")[-1]
                                           + "_" + "_".join(f"{k}{v}" for k, v in sorted(params.items()))
                                           ).lower()).strip("_")
        datei = OFFLINE / f"{name}.json"
        if not datei.exists():
            print(f"  (offline) keine Testdatei {datei.name}", file=sys.stderr)
            return None
        return json.loads(datei.read_text(encoding="utf-8"))

    voll = url + ("?" + urllib.parse.urlencode(params) if params else "")
    for versuch in range(3):
        warten = PAUSE - (time.monotonic() - _letzter)
        if warten > 0:
            time.sleep(warten)
        _letzter = time.monotonic()
        req = urllib.request.Request(voll, headers={
            "User-Agent": UA, "Accept": "application/json",
            "Accept-Language": "de-DE,de;q=0.9", "Referer": referer})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                print(f"  HTTP {e.code} bei {voll}", file=sys.stderr)
                return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  Fehler bei {voll}: {e}", file=sys.stderr)
        time.sleep(2 * (versuch + 1))
    return None


def hole_alle_seiten(pfad: str, params: dict) -> list[dict]:
    """handball.net begrenzt per_page auf 100 – also blättern."""
    alle, seite = [], 1
    while True:
        antwort = hole(f"{HBNET}/{pfad}", {**params, "per_page": 100, "page": seite})
        if not antwort:
            break
        alle.extend(antwort.get("data") or [])
        letzte = (antwort.get("pagination") or {}).get("last_page")
        if not letzte or seite >= letzte:
            break
        seite += 1
    return alle


# -------------------------------------------------------------- Hilfsfunktionen
_GROSS_OK = {"TV", "TSV", "TUS", "SG", "SV", "HSG", "JSG", "MTV", "SC", "FC", "HC", "HSC",
             "TG", "TSG", "BV", "SF", "DJK", "ASV", "II", "III", "IV", "JANO"}
_SCHREIB = {"VFL": "VfL", "VFB": "VfB", "TUS": "TuS", "DHFK": "DHfK"}


def schoen(name: str) -> str:
    """Vereinsnamen kommen teils komplett groß ("FRISCH AUF GÖPPINGEN")."""
    name = (name or "").strip()
    if not name or any("a" <= c <= "z" for c in name):
        return name
    raus = []
    for w in name.split(" "):
        g = w.upper()
        if g in _SCHREIB:
            raus.append(_SCHREIB[g])
        elif g in _GROSS_OK or (len(w) <= 4 and not set(g) & set("AEIOUÄÖÜ")):
            raus.append(w)
        else:
            raus.append("/".join("-".join(t.capitalize() for t in teil.split("-")) for teil in w.lower().split("/")))
    return " ".join(raus)


def anzeigename(vor: str, nach: str, jugend: bool, kuerzen: bool) -> str:
    vor, nach = (vor or "").strip().title(), (nach or "").strip().title()
    if jugend and kuerzen and nach:
        return f"{vor} {nach[0]}.".strip()
    return " ".join(t for t in (vor, nach) if t)


def ortszeit_hbnet(roh: str | None) -> str | None:
    """Der Offset der API stimmt nicht – die Uhrzeit ist bereits Ortszeit."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", str(roh or ""))
    return f"{m.group(1)}T{m.group(2)}" if m else None


def tore(wert) -> int | None:
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- handball.net
def liga_handballnet(cfg: dict, cache: dict, kuerzen: bool) -> dict:
    pid = cfg["phase_id"]
    roh = hole_alle_seiten("matches", {"phase_id": pid})
    teams: dict[int, dict] = {}
    spiele, gesehen = [], set()

    for s in sorted(roh, key=lambda x: (x.get("date") or "", x.get("id") or 0)):
        zeit = ortszeit_hbnet(s.get("date"))
        heim, gast = s.get("local") or {}, s.get("visitor") or {}
        schluessel = (zeit, heim.get("id"), gast.get("id"))
        if not zeit or schluessel in gesehen:        # API liefert teils Dubletten
            continue
        gesehen.add(schluessel)
        for t in (heim, gast):
            if t.get("id"):
                teams[t["id"]] = {"id": t["id"], "name": schoen(t.get("name")),
                                  "logo": t.get("logo") or t.get("image") or None}
        status_roh = (s.get("status") or {})
        status = STATUS.get(status_roh.get("name", ""), "geplant")
        if status_roh.get("is_finished"):
            status = "beendet"
        erg = s.get("result") or {}
        hg, ag = tore(erg.get("local")), tore(erg.get("visitor"))
        if status == "beendet" and not hg and not ag:  # 0:0 = nicht gemeldet
            hg = ag = None
        if status == "geplant":
            hg = ag = None
        feld = s.get("field") or {}
        spiele.append({
            "id": s.get("id"), "datum": zeit, "runde": s.get("round"),
            "heim": schoen(heim.get("name")), "heimId": heim.get("id"),
            "gast": schoen(gast.get("name")), "gastId": gast.get("id"),
            "hTore": hg, "gTore": ag, "status": status,
            "halle": schoen(feld.get("name") or (feld.get("installation") or {}).get("name") or ""),
            "link": f"https://www.handball.net/spiele/{s.get('id')}" if s.get("id") else None,
        })

    tabelle = tabelle_handballnet(pid)
    torschuetzen, strafen = berichte_auswerten(spiele, cache, cfg.get("jugend", False), kuerzen)
    hz = halbzeitlaenge(cache, spiele, cfg.get("halbzeit_minuten"))
    return {"teams": list(teams.values()), "spiele": spiele, "tabelle": tabelle,
            "torschuetzen": torschuetzen, "teamStrafen": strafen,
            "verlauf": zeit_und_auszeiten(spiele, cache, hz)}


def tabelle_handballnet(pid: int) -> list[dict]:
    """standings liefert einen Stand je Spieltag – wir nehmen den jüngsten gespielten."""
    antwort = hole(f"{HBNET}/standings", {"phase_id": pid}) or {}
    daten = antwort.get("data") or []
    if not daten:
        return []
    runden: dict[int, list] = {}
    for e in daten:
        runden.setdefault(e.get("round") or 1, []).append(e)
    gespielt = [r for r, es in runden.items() if any(x.get("played") for x in es)]
    stand = runden[max(gespielt) if gespielt else min(runden)]
    if any(e.get("position") for e in stand):
        stand.sort(key=lambda e: e.get("position") or 99)
    return [{
        "platz": e.get("position") or i + 1,
        "team": schoen((e.get("team") or {}).get("name")),
        "teamId": (e.get("team") or {}).get("id"),
        "sp": e.get("played", 0), "s": e.get("won", 0), "u": e.get("drawn", 0),
        "n": e.get("lost", 0), "tore": e.get("goals_for", 0),
        "gegentore": e.get("goals_against", 0), "diff": e.get("goals_diff", 0),
        "punkte": e.get("points", 0),
    } for i, e in enumerate(stand)]


CACHE_VERSION = 2


def spielsekunde(e: dict) -> int | None:
    """Laufende Spielzeit in Sekunden.

    handball.net liefert `global_minute` (über das ganze Spiel gezählt) und
    `minute` als "MM:SS" innerhalb der Halbzeit – aus beidem ergibt sich die
    sekundengenaue Zeit.
    """
    gm = e.get("global_minute")
    m = re.match(r"^(\d{1,3}):(\d{2})$", str(e.get("minute") or ""))
    if gm is None and not m:
        return None
    if gm is None:
        return int(m.group(1)) * 60 + int(m.group(2))
    return int(gm) * 60 + (int(m.group(2)) if m else 0)


def halbzeitlaenge(cache: dict, spiele: list[dict], vorgabe: int | None) -> int:
    """Minuten je Halbzeit: aus der Konfiguration oder aus den Berichten ablesen."""
    if vorgabe:
        return int(vorgabe)
    werte = []
    for sp in spiele:
        for e in (cache.get(str(sp["id"])) or {}).get("ereignisse", []):
            if e.get("art") in ("Teilende", "Halbzeit") and e.get("abschnitt", "").startswith("1.") \
                    and e.get("sek"):
                werte.append(round(e["sek"] / 60))
    werte = [w for w in werte if 15 <= w <= 35]
    return max(set(werte), key=werte.count) if werte else 30


def zeit_und_auszeiten(spiele: list[dict], cache: dict, hz: int) -> dict:
    """Wann fallen die Tore (je Team gegen Liga-Schnitt) und was bringt eine Auszeit?

    Phasen: jede Halbzeit in drei gleich lange Abschnitte (bei 2×30 also
    1.–10., 11.–20., …). Tore in der Verlängerung zählen nicht mit.
    Auszeit: Wer wirft das nächste Tor? Und wie stehen die Tore in den
    drei Minuten danach?
    """
    N, dauer = 6, 2 * hz * 60
    grenzen = [round(i * hz / 3) for i in range(4)]
    labels = [f"{a + 1}.–{b}." for a, b in zip(grenzen, grenzen[1:])]
    labels = labels + [f"{a + 1 + hz}.–{b + hz}." for a, b in zip(grenzen, grenzen[1:])]
    teams: dict = {}
    auszeiten: dict = {}
    for sp in spiele:
        bericht = cache.get(str(sp["id"]))
        if not bericht or sp["status"] != "beendet" or bericht.get("v") != CACHE_VERSION:
            continue
        ev = [e for e in bericht["ereignisse"] if e.get("sek") is not None]
        tore_ = sorted((e for e in ev if e["tor"] and e["team"]), key=lambda e: e["sek"])
        if not tore_:
            continue
        seiten = {sp["heimId"]: sp["gastId"], sp["gastId"]: sp["heimId"]}
        for tid in seiten:
            t = teams.setdefault(tid, {"spiele": 0, "tore": [0] * N, "gegen": [0] * N})
            t["spiele"] += 1
        for e in tore_:
            if e["team"] not in seiten or e["sek"] > dauer:
                continue
            i = min(int(e["sek"] * N / dauer), N - 1)
            teams[e["team"]]["tore"][i] += 1
            teams[seiten[e["team"]]]["gegen"][i] += 1
        for a in ev:
            if a["art"] != "Auszeit" or a["team"] not in seiten:
                continue
            nach = [e for e in tore_ if e["sek"] >= a["sek"]]
            st = auszeiten.setdefault(a["team"], {"anzahl": 0, "naechstesEigen": 0, "naechstesGegner": 0,
                                                  "tore3": 0, "gegen3": 0})
            st["anzahl"] += 1
            if nach:
                st["naechstesEigen" if nach[0]["team"] == a["team"] else "naechstesGegner"] += 1
            for e in nach:
                if e["sek"] - a["sek"] > 180:
                    break
                st["tore3" if e["team"] == a["team"] else "gegen3"] += 1
    spiele_ges = sum(t["spiele"] for t in teams.values())
    liga = [round(sum(t["tore"][i] for t in teams.values()) / spiele_ges, 2) if spiele_ges else 0
            for i in range(N)]
    return {"halbzeit": hz, "labels": labels, "ligaSchnitt": liga,
            "teams": [{"teamId": k, **v} for k, v in teams.items()],
            "auszeiten": [{"teamId": k, **v} for k, v in auszeiten.items()],
            "zahl": ueber_unterzahl(spiele, cache, hz)}


ZEITSTRAFE = ("zwei minuten", "2 min", "zeitstrafe", "zwei-minuten")


def ueber_unterzahl(spiele: list[dict], cache: dict, hz: int) -> list[dict]:
    """Tore und Gegentore in Über- und Unterzahl je Team.

    Jede Zeitstrafe (und jede Disqualifikation ohne gleichzeitige Zeitstrafe)
    schwächt das Team 2 Minuten lang. Ein Team ist in Überzahl, wenn beim
    Gegner mehr Strafen laufen als bei ihm selbst – und umgekehrt.
    Gezählt werden Sekunden sowie Tore/Gegentore in diesen Phasen.
    """
    teams: dict = {}
    for sp in spiele:
        bericht = cache.get(str(sp["id"]))
        if not bericht or sp["status"] != "beendet" or bericht.get("v") != CACHE_VERSION:
            continue
        ev = [e for e in bericht["ereignisse"] if e.get("sek") is not None]
        if not any(e["tor"] for e in ev):
            continue
        seiten = {sp["heimId"]: sp["gastId"], sp["gastId"]: sp["heimId"]}
        strafen = {t: [] for t in seiten}
        zwei_zeit = {(e["team"], e["sek"]) for e in ev if any(z in e["art"].lower() for z in ZEITSTRAFE)}
        for e in ev:
            art = e["art"].lower()
            if e["team"] not in seiten:
                continue
            if any(z in art for z in ZEITSTRAFE) or \
                    ("disqualifikation" in art and (e["team"], e["sek"]) not in zwei_zeit):
                strafen[e["team"]].append(e["sek"])
        ende = max([2 * hz * 60] + [e["sek"] for e in ev])
        aktiv = lambda t, s: sum(1 for a in strafen[t] if a < s <= a + 120)
        for t, g in seiten.items():
            st = teams.setdefault(t, {"spiele": 0, "ueSek": 0, "ueTore": 0, "ueGegen": 0,
                                      "uzSek": 0, "uzTore": 0, "uzGegen": 0})
            st["spiele"] += 1
            for s in range(1, ende + 1):
                d = aktiv(g, s) - aktiv(t, s)
                if d > 0:
                    st["ueSek"] += 1
                elif d < 0:
                    st["uzSek"] += 1
        for e in ev:
            if not e["tor"] or e["team"] not in seiten:
                continue
            t, g = e["team"], seiten[e["team"]]
            d = aktiv(g, e["sek"]) - aktiv(t, e["sek"])
            if d > 0:
                teams[t]["ueTore"] += 1
                teams[g]["uzGegen"] += 1
            elif d < 0:
                teams[t]["uzTore"] += 1
                teams[g]["ueGegen"] += 1
    return [{"teamId": k, **v} for k, v in teams.items()]


def bericht_hbnet(sp: dict) -> list[dict] | None:
    """Spielverlauf von handball.net (JSON)."""
    antwort = hole(f"{HBNET}/matches/{sp['id']}/events")
    if antwort is None:
        return None
    roh = antwort.get("data", antwort) if isinstance(antwort, dict) else antwort
    ereignisse = []
    for e in roh if isinstance(roh, list) else []:
        art = e.get("event_type") or {}
        sp_ = e.get("player") or {}
        ereignisse.append({
            "art": art.get("name") or "", "tor": bool(art.get("is_goal")),
            "team": (e.get("team") or {}).get("id"),
            "spieler": sp_.get("id"), "vor": sp_.get("first_name") or "",
            "nach": sp_.get("last_name") or "",
            "sek": spielsekunde(e), "abschnitt": (e.get("block") or "").strip(),
        })
    return ereignisse


def berichte_auswerten(spiele: list[dict], cache: dict, jugend: bool, kuerzen: bool,
                       holer=bericht_hbnet):
    """Spielberichte (Ereignisse je Spiel) holen – einmalig, dann aus dem Cache."""
    neu = 0
    for sp in spiele:
        if sp["status"] not in ("beendet", "live") or not sp["id"]:
            continue
        key = str(sp["id"])
        if key in cache and cache[key].get("v") == CACHE_VERSION and not cache[key].get("vorlaeufig"):
            continue
        if neu >= MAX_BERICHTE:
            break
        neu += 1
        ereignisse = holer(sp)
        if ereignisse is None:
            continue
        if jugend and kuerzen:   # Repo ist öffentlich: Jugendnamen schon im Cache kürzen
            for e in ereignisse:
                if e.get("spieler"):
                    e["spieler"] = hashlib.sha1(str(e["spieler"]).encode()).hexdigest()[:12]
                    e["nach"] = (e.get("nach") or "")[:1]
        cache[key] = {"v": CACHE_VERSION, "ereignisse": ereignisse,
                      "vorlaeufig": sp["status"] == "live"}

    spieler: dict[str, dict] = {}
    strafen: dict[int, dict] = {}
    for sp in spiele:
        bericht = cache.get(str(sp["id"]))
        if not bericht:
            continue
        in_spiel = set()
        for e in bericht["ereignisse"]:
            art = e["art"].lower()
            if e["team"] and not e["tor"]:
                st = strafen.setdefault(e["team"], {"zwei": 0, "gelb": 0, "rot": 0, "spiele": set()})
                st["spiele"].add(sp["id"])
                if "zwei" in art or "2 min" in art or "zeitstrafe" in art:
                    st["zwei"] += 1
                elif "verwarnung" in art or "gelb" in art:
                    st["gelb"] += 1
                elif "disqualifikation" in art or "rot" in art:
                    st["rot"] += 1
            if not e["spieler"]:
                continue
            pid = str(e["spieler"])
            p = spieler.setdefault(pid, {
                "name": anzeigename(e["vor"], e["nach"], jugend, kuerzen), "teamId": e["team"],
                "tore": 0, "siebenTore": 0, "siebenWuerfe": 0, "zwei": 0, "spiele": 0})
            if (sp["id"], pid) not in in_spiel:
                in_spiel.add((sp["id"], pid))
                p["spiele"] += 1
            sieben = "siebenmeter" in art or "7m" in art or "7-m" in art
            if e["tor"]:
                p["tore"] += 1
                if sieben:
                    p["siebenTore"] += 1
                    p["siebenWuerfe"] += 1
            elif sieben:
                p["siebenWuerfe"] += 1
            elif "zwei" in art or "2 min" in art or "zeitstrafe" in art:
                p["zwei"] += 1

    liste = sorted((p for p in spieler.values() if p["tore"] > 0 or p["zwei"] > 0),
                   key=lambda p: (-p["tore"], p["name"]))
    return liste, [{"teamId": t, "zwei": v["zwei"], "gelb": v["gelb"], "rot": v["rot"],
                    "spiele": len(v["spiele"])} for t, v in strafen.items()]


# --------------------------------------------------------------- Handball4All
def liga_h4a(cfg: dict) -> dict:
    og, cl = cfg["org_id"], cfg["class_id"]
    antwort = hole(H4A, {"cmd": "ps", "og": og, "cl": cl, "ca": 1},
                   referer="https://www.handball4all.de/")
    if isinstance(antwort, list):
        antwort = antwort[0] if antwort else {}
    inhalt = (antwort or {}).get("content") or {}
    roh = []
    for key in ("futureGames", "actualGames"):
        block = inhalt.get(key)
        if isinstance(block, dict):
            roh.extend(block.get("games") or [])

    spiele, gesehen, teams = [], set(), {}
    for g in roh:
        if str(g.get("gID")) in gesehen:
            continue
        gesehen.add(str(g.get("gID")))
        m = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})$", (g.get("gDate") or "").strip())
        if not m:
            continue
        z = re.match(r"^(\d{1,2}):(\d{2})$", (g.get("gTime") or "").strip())
        zeit = f"20{m.group(3)}-{m.group(2)}-{m.group(1)}T" + (
            f"{int(z.group(1)):02d}:{z.group(2)}" if z else "00:00")
        heim, gast = schoen(g.get("gHomeTeam") or ""), schoen(g.get("gGuestTeam") or "")
        for t in (heim, gast):
            teams[t] = {"id": t, "name": t, "logo": None}
        hg, ag = tore(g.get("gHomeGoals")), tore(g.get("gGuestGoals"))
        bemerkung = (g.get("gComment") or "").strip().lower()
        if hg is not None and ag is not None and not (hg == 0 and ag == 0):
            status = "beendet"
        else:
            hg = ag = None
            status = "abgesetzt" if bemerkung else "geplant"   # Bemerkung ohne Ergebnis = Ausfall/Wertung
        if (g.get("gToken") or "").strip() and status != "beendet":
            status = "live"
        spiele.append({
            "id": g.get("gID"), "datum": zeit, "runde": None,
            "heim": heim, "heimId": heim, "gast": gast, "gastId": gast,
            "hTore": hg, "gTore": ag, "status": status,
            "halle": ", ".join(t for t in (schoen((g.get("gGymnasiumName") or "").strip()),
                                           (g.get("gGymnasiumTown") or "").strip()) if t),
            "link": f"https://www.handball4all.de/home/portal/baden-wuerttembergischer-hv#/league?ogId={og}&lId={cl}",
            "bericht": (str(g.get("sGID") or "").strip() or None) if str(g.get("sGID") or "").strip() not in ("", "0") else None,
            "hz": (f"{tore(g.get('gHomeGoals_1'))}:{tore(g.get('gGuestGoals_1'))}"
                   if status == "beendet" and tore(g.get("gHomeGoals_1")) is not None
                   and tore(g.get("gGuestGoals_1")) is not None else None),
        })
    spiele.sort(key=lambda s: s["datum"])

    tabelle, letzter_platz = [], 0
    for i, e in enumerate(inhalt.get("score") or []):
        name = schoen(e.get("tabTeamname") or "")
        platz = tore(e.get("tabScore")) or letzter_platz or i + 1   # punktgleich: Platz leer
        letzter_platz = platz
        tabelle.append({
            "platz": platz, "team": name, "teamId": name,
            "sp": tore(e.get("numPlayedGames")) or 0, "s": tore(e.get("numWonGames")) or 0,
            "u": tore(e.get("numEqualGames")) or 0, "n": tore(e.get("numLostGames")) or 0,
            "tore": tore(e.get("numGoalsShot")) or 0, "gegentore": tore(e.get("numGoalsGot")) or 0,
            "diff": (tore(e.get("numGoalsShot")) or 0) - (tore(e.get("numGoalsGot")) or 0),
            "punkte": tore(e.get("pointsPlus")) or 0,
        })
    namen_zuordnen(tabelle, spiele)
    cache, kuerzen = H4A_KONTEXT["cache"], H4A_KONTEXT["kuerzen"]
    torschuetzen, strafen = berichte_auswerten(spiele, cache, cfg.get("jugend", False), kuerzen,
                                               holer=bericht_h4a)
    hz = halbzeitlaenge(cache, spiele, cfg.get("halbzeit_minuten"))
    return {"teams": list(teams.values()), "spiele": spiele, "tabelle": tabelle,
            "torschuetzen": torschuetzen, "teamStrafen": strafen,
            "verlauf": zeit_und_auszeiten(spiele, cache, hz)}


H4A_PDF = "https://spo.handball4all.de/misc/sboPublicReports.php"
H4A_KONTEXT: dict = {"cache": {}, "kuerzen": True}

_ZEILE = re.compile(r"^\s*(\d{1,2}:\d{2}:\d{2})\s+(\d{1,3}):(\d{2})\s+(?:(\d+):(\d+)\s+)?(.+?)\s*$")
_PERSON = re.compile(r"^(?P<aktion>.+?)\s+(?:durch|für)\s+(?P<name>.+?)\s*\((?P<nr>\w+),\s*(?P<team>.+)\)$")
_ARTEN = [  # (Anfang des Aktionstexts, Name wie bei handball.net, ist Tor)
    ("7m-tor", "Siebenmeter Tor", True), ("7m, kein tor", "Siebenmeter Fehlwurf", False),
    ("tor", "Tor", True), ("2-min", "Zwei Minuten", False), ("verwarnung", "Verwarnung", False),
    ("disqualifikation", "Disqualifikation", False), ("rot", "Disqualifikation", False),
    ("blau", "Disqualifikation", False),
]


def hole_pdf(sgid: str) -> bytes | None:
    if OFFLINE is not None:
        datei = OFFLINE / f"pdf_{sgid}.pdf"
        return datei.read_bytes() if datei.exists() else None
    global _letzter
    for versuch in range(2):
        warten = 1.0 - (time.monotonic() - _letzter)
        if warten > 0:
            time.sleep(warten)
        _letzter = time.monotonic()
        req = urllib.request.Request(f"{H4A_PDF}?sGID={urllib.parse.quote(sgid)}", headers={
            "User-Agent": UA, "Referer": "https://www.handball4all.de/"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                daten = r.read()
            return daten if daten[:4] == b"%PDF" else None
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  PDF {sgid}: {e}", file=sys.stderr)
            time.sleep(3)
    return None


def _gleiches_team(name: str, kandidaten: dict[str, str]) -> str | None:
    """Teamnamen im Bericht dem Heim- oder Gastteam zuordnen (exakt, sonst über Wörter)."""
    n = name.strip().lower()
    for k, wert in kandidaten.items():
        if k.strip().lower() == n:
            return wert
    woerter = lambda t: {w for w in re.split(r"[^a-zäöüß0-9]+", t.lower()) if len(w) > 1}
    best = max(kandidaten, key=lambda k: len(woerter(k) & woerter(name)), default=None)
    return kandidaten[best] if best and woerter(best) & woerter(name) else None


def bericht_h4a(sp: dict) -> list[dict] | None:
    """Spielbericht-PDF (SBO) lesen: Spielverlauf mit Spielzeit, Toren, Strafen, Auszeiten."""
    if not sp.get("bericht"):
        return None
    try:
        import pypdf  # nur für Handball4All nötig
    except ImportError:
        print("  pypdf fehlt – Spielberichte werden übersprungen (pip install pypdf)", file=sys.stderr)
        return None
    roh = hole_pdf(sp["bericht"])
    if not roh:
        return None
    import io
    try:
        text = "\n".join((seite.extract_text() or "") for seite in pypdf.PdfReader(io.BytesIO(roh)).pages)
    except Exception as e:                          # kaputtes PDF: nächstes Mal neu versuchen
        print(f"  PDF {sp['bericht']} nicht lesbar: {e!r}", file=sys.stderr)
        return None
    zeilen = text.splitlines()
    heim_lang = next((z.split(":", 1)[1].strip() for z in zeilen if z.startswith("Heim:")), "")
    gast_lang = next((z.split(":", 1)[1].strip() for z in zeilen if z.startswith("Gast:")), "")
    teams = {sp["heim"]: sp["heimId"], sp["gast"]: sp["gastId"]}
    if heim_lang:
        teams[heim_lang] = sp["heimId"]
    if gast_lang:
        teams[gast_lang] = sp["gastId"]

    ereignisse = []
    for z in zeilen:
        m = _ZEILE.match(z)
        if not m:
            continue
        sek = int(m.group(2)) * 60 + int(m.group(3))
        aktion = m.group(6).strip()
        if aktion.lower().startswith("auszeit"):
            team = _gleiches_team(aktion[7:].strip(), teams)
            ereignisse.append({"art": "Auszeit", "tor": False, "team": team, "spieler": None,
                               "vor": "", "nach": "", "sek": sek, "abschnitt": ""})
            continue
        p = _PERSON.match(aktion)
        if not p:
            continue
        a = p.group("aktion").lower()
        art = next(((name, tor) for anfang, name, tor in _ARTEN if a.startswith(anfang)), None)
        if not art:
            continue
        team = _gleiches_team(p.group("team"), teams)
        teile = p.group("name").split()
        ereignisse.append({
            "art": art[0], "tor": art[1], "team": team,
            "spieler": f"{team}#{p.group('nr')}#{p.group('name')}",
            "vor": " ".join(teile[:-1]), "nach": teile[-1] if teile else "",
            "sek": sek, "abschnitt": "",
        })
    if not ereignisse:
        return None
    # Halbzeit eintragen (für die Halbzeitlänge): Spielende ≈ 60/50/40 Min.
    ende = max(e["sek"] for e in ereignisse)
    hz = max(20, min(30, round(ende / 60 / 10) * 5))
    for e in ereignisse:
        e["abschnitt"] = "1. Halbzeit" if e["sek"] <= hz * 60 else "2. Halbzeit"
    ereignisse.append({"art": "Teilende", "tor": False, "team": None, "spieler": None,
                       "vor": "", "nach": "", "sek": hz * 60, "abschnitt": "1. Halbzeit"})
    return ereignisse


def namen_zuordnen(tabelle: list[dict], spiele: list[dict]) -> None:
    """H4A schreibt in der Tabelle den langen Vereinsnamen ("Jugendhandball-Akademie
    Neuhausen-Ostfildern 2"), im Spielplan den kurzen ("JANO Filder 2"). Zugeordnet
    wird über die Tore: Geworfene und kassierte Tore aus dem Spielplan müssen zur
    Tabellenzeile passen. Klappt das nicht eindeutig, entscheiden gemeinsame Wörter.
    """
    kurz: dict[str, list[int]] = {}
    for s in spiele:
        for n in (s["heim"], s["gast"]):
            kurz.setdefault(n, [0, 0])
        if s["status"] == "beendet" and s["hTore"] is not None:
            kurz[s["heim"]][0] += s["hTore"]; kurz[s["heim"]][1] += s["gTore"]
            kurz[s["gast"]][0] += s["gTore"]; kurz[s["gast"]][1] += s["hTore"]
    frei = set(kurz)
    woerter = lambda t: {w for w in re.split(r"[^a-zäöüß0-9]+", t.lower()) if len(w) > 1}
    offen = []
    for z in tabelle:
        if z["team"] in frei:
            frei.discard(z["team"]); continue
        treffer = [n for n in frei if kurz[n] == [z["tore"], z["gegentore"]]]
        if len(treffer) == 1:
            z["teamId"] = treffer[0]; frei.discard(treffer[0])
        else:
            offen.append(z)
    for z in offen:
        if not frei:
            break
        bester = max(frei, key=lambda n: len(woerter(n) & woerter(z["team"])))
        z["teamId"] = bester; frei.discard(bester)


# ------------------------------------------------------------------- Hauptteil
def tabelle_aus_spielen(spiele: list[dict]) -> list[dict]:
    """Rückfall, falls die Quelle keine Tabelle liefert: aus den Ergebnissen rechnen."""
    t: dict = {}
    for s in spiele:
        if s["status"] != "beendet" or s["hTore"] is None:
            continue
        for seite, tid, name, f, g in (("h", s["heimId"], s["heim"], s["hTore"], s["gTore"]),
                                       ("g", s["gastId"], s["gast"], s["gTore"], s["hTore"])):
            e = t.setdefault(tid, {"team": name, "teamId": tid, "sp": 0, "s": 0, "u": 0, "n": 0,
                                   "tore": 0, "gegentore": 0, "punkte": 0})
            e["sp"] += 1
            e["tore"] += f
            e["gegentore"] += g
            if f > g:
                e["s"] += 1
                e["punkte"] += 2
            elif f == g:
                e["u"] += 1
                e["punkte"] += 1
            else:
                e["n"] += 1
    liste = sorted(t.values(), key=lambda e: (-e["punkte"], -(e["tore"] - e["gegentore"]), -e["tore"]))
    for i, e in enumerate(liste):
        e["diff"] = e["tore"] - e["gegentore"]
        e["platz"] = i + 1
    return liste


def main() -> int:
    global OFFLINE
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", type=Path, help="Testdaten-Ordner statt Netzabruf")
    args = ap.parse_args()
    OFFLINE = args.offline

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    kuerzen = cfg.get("jugendnamen_kuerzen", True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    H4A_KONTEXT.update(cache=cache, kuerzen=kuerzen)
    AUSGABE.mkdir(parents=True, exist_ok=True)
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    index = {"aktualisiert": jetzt, "saison": cfg.get("saison"), "ligen": []}
    fehler = 0

    for liga in cfg["ligen"]:
        print(f"→ {liga['kurz']} ({liga['quelle']})")
        try:
            daten = liga_h4a(liga) if liga["quelle"] == "h4a" else liga_handballnet(liga, cache, kuerzen)
        except Exception as e:                       # eine kaputte Liga stoppt nicht alle
            print(f"  ABBRUCH: {e!r}", file=sys.stderr)
            fehler += 1
            continue
        tabelle_quelle = "verband"
        if not daten["tabelle"]:
            daten["tabelle"] = tabelle_aus_spielen(daten["spiele"])
            tabelle_quelle = "berechnet"
        if not daten["spiele"]:
            alt = AUSGABE / f"{liga['slug']}.json"
            if alt.exists():                          # leere Antwort: alten Stand behalten
                print("  keine Spiele erhalten – alter Stand bleibt", file=sys.stderr)
                fehler += 1
                index["ligen"].append(json.loads(alt.read_text(encoding="utf-8"))["meta"])
                continue
        meta = {k: liga.get(k) for k in ("slug", "name", "kurz", "quelle", "jugend", "link")}
        lang_zu_id = {z["team"]: z["teamId"] for z in daten["tabelle"]}
        meta["meineTeams"] = [lang_zu_id.get(t, t) for t in liga.get("meine_teams", [])]
        meta["aktualisiert"] = jetzt
        meta["abrufFehler"] = not daten["spiele"]
        meta["tabelleQuelle"] = tabelle_quelle
        (AUSGABE / f"{liga['slug']}.json").write_text(
            json.dumps({"meta": meta, **daten}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        index["ligen"].append(meta)
        print(f"  {len(daten['spiele'])} Spiele, {len(daten['tabelle'])} Tabellenplätze, "
              f"{len(daten['torschuetzen'])} Spieler")

    (AUSGABE / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return 1 if fehler and fehler == len(cfg["ligen"]) else 0


if __name__ == "__main__":
    sys.exit(main())
