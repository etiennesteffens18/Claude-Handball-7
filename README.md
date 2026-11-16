# Handball 7 – deine Handball-Web-App

Spiele, Tabellen und Statistiken deiner Ligen auf einer Seite – fürs Handy optimiert,
installierbar wie eine App. Läuft komplett kostenlos auf GitHub.

```
handball.net / Handball4All  →  GitHub Action (holt Daten automatisch)  →  docs/data/*.json  →  Web-App (GitHub Pages)
```

## Einrichten (einmalig, ca. 10 Minuten, geht auch am Handy)

1. **GitHub-Konto** anlegen: https://github.com/signup
2. **Neues Repository** erstellen: oben rechts „+“ → *New repository* → Name z. B. `hallenbuch`,
   **Public** (GitHub Pages ist bei privaten Repos kostenpflichtig) → *Create repository*.
3. **Dateien hochladen**: Im leeren Repo auf *uploading an existing file* tippen und den
   *Inhalt* dieses Ordners hochladen (die Ordner `config`, `docs`, `scripts`, `cache`, `.github`
   und diese README). Am Handy geht das am einfachsten über die Desktop-Ansicht des Browsers.
   ⚠️ Der Ordner `.github` ist auf manchen Rechnern versteckt – er muss mit hoch, sonst läuft nichts automatisch.
4. **Schreibrechte für die Automatik**: *Settings → Actions → General → Workflow permissions →
   „Read and write permissions“* → *Save*.
5. **Seite einschalten**: *Settings → Pages → Source: „Deploy from a branch“ → Branch `main`,
   Ordner `/docs`* → *Save*.
6. **Ersten Abruf starten**: Reiter *Actions* → *Daten abrufen* → *Run workflow*.
   Nach 1–2 Minuten ist alles da.
7. Deine App liegt unter `https://<dein-name>.github.io/hallenbuch/`.
   Am Handy im Browser öffnen → *Teilen → Zum Home-Bildschirm*.

Danach aktualisiert sich alles von selbst: am Wochenende stündlich, unter der Woche zweimal am Tag.

## Ligen hinzufügen – `config/ligen.json`

Jede Liga ist ein Block in `"ligen"`. Bearbeiten direkt auf GitHub (Stift-Symbol), speichern,
dann unter *Actions* einmal *Run workflow*.

**handball.net** (DHB-Ligen, HVNB/nuLiga und alle Verbände, die schon umgestellt haben):

```json
{
  "slug": "jblh-sued",
  "name": "Jugendbundesliga A-Jugend männlich – 1. Liga Süd",
  "kurz": "JBLH Süd",
  "quelle": "handballnet",
  "phase_id": 14032,
  "jugend": true,
  "meine_teams": [87031],
  "link": "https://www.handball.net/ligen/9518?phaseId=14032&season_id=2627&fed_id=1"
}
```

- `phase_id` steht in der Liga-Adresse auf handball.net: `…/ligen/9518?phaseId=`**14032**
- `meine_teams`: die Team-ID aus der Team-Adresse: `handball.net/team/`**87031**
- `slug`: frei wählbarer Kurzname ohne Leerzeichen/Umlaute

**Handball4All** (BWHV – der Verband ist für 2026/27 noch nicht auf handball.net):

```json
{
  "slug": "wue-landesliga",
  "name": "Männer Landesliga Staffel 2",
  "kurz": "LL M 2",
  "quelle": "h4a",
  "org_id": 216,
  "class_id": 161166,
  "jugend": false,
  "meine_teams": ["TSV Beispiel 2"]
}
```

- `class_id` = `lId=` in der Adresse des H4A-Portals (`…#/league?ogId=216&lId=`**161166**)
- `meine_teams` hier als **Name, genau so geschrieben wie im Spielplan**

Optional: `"halbzeit_minuten": 25` legt die Halbzeitlänge fest (sonst liest die App sie aus
den Spielberichten ab – B-Jugend 2×25, A-Jugend und Aktive 2×30).

`"jugend": true` kürzt Spielernamen auf „Vorname N.“ – bitte bei Jugendligen so lassen,
die Seite ist öffentlich erreichbar.

## Was die App zeigt

- **Startseite – Meine Teams**: je Team eine Karte mit Tabellenplatz, letztem Ergebnis und
  nächstem Spiel.
- **Team antippen** öffnet die Teamseite mit drei Reitern:
  - **Spiele**: zuerst nur die Spiele des Teams (nächste Spiele, dann Ergebnisse);
    umschaltbar auf **Ganze Liga**
  - **Tabelle**: eigenes Team hervorgehoben; ein Team antippen zeigt dessen Spiele
  - **Statistik**: Torschützen (7 m, Zeitstrafen), Teamwerte, Tore & Gegentore pro Spiel mit
    Liga-Schnitt, „Wann fallen die Tore?“ (Säulen = Team, Linie = Liga-Schnitt),
    Torerfolg nach Auszeit
- Ein Spiel antippen zeigt Tabellenstand beider Teams und den direkten Vergleich.

## Gut zu wissen

- Beide Schnittstellen sind inoffiziell (die, mit der die Webseiten selbst arbeiten). Ändert
  ein Anbieter etwas, kann der Abruf ausfallen – die App zeigt dann den letzten Stand.
  Fehler stehen unter *Actions* im jeweiligen Lauf.
- Die Daten gehören DHB bzw. den Verbänden. Für private Nutzung und dein Team gedacht,
  nicht für kommerzielle Weiterverbreitung.
- Lokal testen: `python scripts/abruf.py` und dann `python -m http.server -d docs`.

## Neu
- **Gegner-Reiter**: Scouting für das nächste Spiel (Vergleich, gefährlichste Werfer, Torphasen, Auffälligkeiten).
- **Über- und Unterzahl** je Team und **7-Meter-Quote** je Werfer und Team.
- Tabelle mit Plus- und Minuspunkten (z. B. 10:2).
