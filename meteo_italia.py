#!/usr/bin/env python3
"""
meteo_italia.py
----------------
Scarica dati meteo GIORNALIERI per una rete di punti stratificati in Italia
(urbani / costieri / rurali / montani) da Open-Meteo e li accumula in un CSV
in formato "lungo"/tidy, pronto per l'interpolazione spaziale (kriging).

Modalita':
  --mode backfill   scarica gli ultimi N anni (default 5) dall'Archive API (ERA5)
  --mode daily      aggiorna una finestra mobile recente e fa UPSERT auto-correttivo
                    (Forecast API per i dati recenti provvisori + Archive API per i
                     valori ERA5 ormai definitivi, che sovrascrivono i provvisori)

Open-Meteo: nessuna API key, gratis per uso non commerciale (<10.000 chiamate/giorno),
licenza dati CC BY 4.0 -> attribuzione richiesta nei grafici/pubblicazioni.

Sintassi CSV di output (data/meteo_italia_daily.csv), una riga = un punto x un giorno:
  data, punto_id, nome, lat, lon, quota_m, macroarea, tipo, fonte, <variabili...>
La chiave di upsert e' (punto_id, data). La 'fonte' ha priorita': era5 > forecast.
"""

import argparse
import csv
import os
import sys
import time
from datetime import date, timedelta

import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Variabili giornaliere richieste (tutte supportate sia da archive che da forecast)
DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
]

HERE = os.path.dirname(os.path.abspath(__file__))
POINTS_CSV = os.path.join(HERE, "points.csv")
DATA_DIR = os.path.join(HERE, "data")
OUT_CSV = os.path.join(DATA_DIR, "meteo_italia_daily.csv")

CSV_FIELDS = [
    "data", "punto_id", "nome", "lat", "lon", "quota_m",
    "macroarea", "tipo", "fonte",
] + DAILY_VARS

# Priorita' della fonte: un valore ERA5 (definitivo) sovrascrive un forecast (provvisorio)
FONTE_RANK = {"forecast": 1, "era5": 2}

TIMEZONE = "Europe/Rome"
SLEEP_BETWEEN_CALLS = 0.4  # cortesia verso l'API pubblica


def load_points(path=POINTS_CSV):
    pts = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["lat"] = float(row["lat"])
            row["lon"] = float(row["lon"])
            pts.append(row)
    return pts


def fetch_point(point, start, end, url, fonte):
    """Scarica un singolo punto in [start, end]. Ritorna lista di dict (una per giorno)."""
    params = {
        "latitude": point["lat"],
        "longitude": point["lon"],
        "daily": ",".join(DAILY_VARS),
        "timezone": TIMEZONE,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    js = r.json()
    if js.get("error"):
        raise RuntimeError(f"{point['punto_id']}: {js.get('reason')}")

    daily = js.get("daily") or {}
    times = daily.get("time", [])
    quota = js.get("elevation")  # quota della cella di griglia (coerente col modello)

    rows = []
    for i, giorno in enumerate(times):
        row = {
            "data": giorno,
            "punto_id": point["punto_id"],
            "nome": point["nome"],
            "lat": point["lat"],
            "lon": point["lon"],
            "quota_m": quota,
            "macroarea": point["macroarea"],
            "tipo": point["tipo"],
            "fonte": fonte,
        }
        valid = False
        for v in DAILY_VARS:
            val = daily.get(v, [None] * len(times))[i]
            row[v] = val
            if val is not None:
                valid = True
        if valid:  # scarta i giorni completamente vuoti (es. oltre il consolidamento)
            rows.append(row)
    return rows


def fetch_window(points, start, end, url, fonte):
    out = []
    for p in points:
        try:
            out.extend(fetch_point(p, start, end, url, fonte))
            print(f"  ok {p['punto_id']:<4} {p['nome']:<22} {fonte:<8} "
                  f"{start} -> {end}")
        except Exception as e:
            print(f"  ERR {p['punto_id']:<4} {p['nome']:<22} {fonte:<8} {e}",
                  file=sys.stderr)
        time.sleep(SLEEP_BETWEEN_CALLS)
    return out


def load_existing():
    """CSV esistente -> dict {(punto_id, data): row}."""
    store = {}
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                store[(row["punto_id"], row["data"])] = row
    return store


def upsert(store, new_rows):
    """Inserisce/aggiorna rispettando la priorita' di fonte."""
    added = updated = 0
    for row in new_rows:
        key = (row["punto_id"], row["data"])
        old = store.get(key)
        if old is None:
            store[key] = row
            added += 1
        else:
            new_rank = FONTE_RANK.get(row["fonte"], 0)
            old_rank = FONTE_RANK.get(old.get("fonte", ""), 0)
            if new_rank >= old_rank:  # >= cosi' un ri-download aggiorna anche pari fonte
                store[key] = row
                updated += 1
    return added, updated


def save(store):
    os.makedirs(DATA_DIR, exist_ok=True)
    rows = sorted(store.values(), key=lambda r: (r["data"], r["punto_id"]))
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
    print(f"Salvate {len(rows)} righe in {OUT_CSV}")


def run_backfill(points, years):
    end = date.today() - timedelta(days=6)          # margine per il lag ERA5
    start = end - timedelta(days=int(years) * 365)
    print(f"BACKFILL {years} anni: {start} -> {end} ({len(points)} punti)")
    store = load_existing()
    rows = fetch_window(points, start, end, ARCHIVE_URL, "era5")
    a, u = upsert(store, rows)
    save(store)
    print(f"Backfill completato: +{a} nuove, {u} aggiornate.")


def run_daily(points):
    today = date.today()
    store = load_existing()

    # 1) Forecast API: ultimi 14 giorni, valori provvisori subito disponibili
    fc_start = today - timedelta(days=14)
    fc_end = today - timedelta(days=1)               # 'oggi' e' incompleto -> escluso
    print(f"DAILY forecast (provvisorio): {fc_start} -> {fc_end}")
    fc_rows = fetch_window(points, fc_start, fc_end, FORECAST_URL, "forecast")

    # 2) Archive API: finestra ormai consolidata, ERA5 sovrascrive i provvisori
    ar_start = today - timedelta(days=20)
    ar_end = today - timedelta(days=6)
    print(f"DAILY archive (definitivo): {ar_start} -> {ar_end}")
    ar_rows = fetch_window(points, ar_start, ar_end, ARCHIVE_URL, "era5")

    a1, u1 = upsert(store, fc_rows)
    a2, u2 = upsert(store, ar_rows)
    save(store)
    print(f"Daily completato: +{a1 + a2} nuove, {u1 + u2} aggiornate.")


def main():
    ap = argparse.ArgumentParser(description="Raccolta meteo giornaliera Italia (Open-Meteo)")
    ap.add_argument("--mode", choices=["backfill", "daily"], required=True)
    ap.add_argument("--years", default="5", help="anni di storico (solo backfill)")
    args = ap.parse_args()

    points = load_points()
    if args.mode == "backfill":
        run_backfill(points, args.years)
    else:
        run_daily(points)


if __name__ == "__main__":
    main()
