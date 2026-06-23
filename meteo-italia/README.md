# Meteo Italia — raccolta dati giornaliera automatica

Rete di ~50 punti stratificati (urbani / costieri / rurali / montani, Nord/Centro/Sud + isole).
Scarica dati meteo **giornalieri** da [Open-Meteo](https://open-meteo.com) e li accumula in
un CSV "tidy" pronto per l'interpolazione spaziale (kriging).

Gira **gratis su GitHub Actions**: il tuo PC può restare spento. GitHub esegue lo script
ogni notte e committa il CSV aggiornato in `data/meteo_italia_daily.csv`.

## Setup (5 minuti, senza installare niente in locale)

1. Crea un repository su GitHub (può essere privato).
2. Carica questi file mantenendo la struttura delle cartelle
   (in particolare `.github/workflows/meteo.yml`).
3. Vai su **Settings → Actions → General → Workflow permissions** e imposta
   **Read and write permissions** (serve perché il job possa committare il CSV).
4. Vai sulla scheda **Actions**, seleziona il workflow *Meteo Italia* → **Run workflow**,
   scegli `mode: backfill`, `years: 5` e avvia. In pochi minuti hai 5 anni di storico.
5. Da lì in poi non devi fare nulla: ogni notte (`cron: '0 3 * * *'`, UTC) il job parte
   in modalità `daily` e aggiorna il dataset.

## Cosa contiene il CSV

Una riga per ogni coppia (punto, giorno):

| colonna | significato |
|---|---|
| `data` | giorno (YYYY-MM-DD) |
| `punto_id`, `nome`, `lat`, `lon` | identità del punto |
| `quota_m` | quota della cella di griglia (covariata chiave per il kriging) |
| `macroarea`, `tipo` | stratificazione (urbano/costiero/rurale/montano) |
| `fonte` | `era5` = definitivo · `forecast` = provvisorio (verrà sovrascritto) |
| `temperature_2m_max/min/mean`, `precipitation_sum`, `wind_speed_10m_max` | i dati |

## Finestra mobile auto-correttiva

L'archivio ERA5 ha ~5 giorni di latenza. Per questo il job giornaliero:
- prende gli ultimi 14 giorni dalla **Forecast API** (provvisori, disponibili subito);
- ri-scarica la finestra ormai consolidata dall'**Archive API** (ERA5), che
  **sovrascrive** i valori provvisori non appena diventano definitivi.

Così non ci sono buchi e i valori si "auto-guariscono" da soli.

## Esecuzione locale (opzionale)

```bash
pip install -r requirements.txt
python meteo_italia.py --mode backfill --years 5   # storico
python meteo_italia.py --mode daily                # aggiornamento
```

## Licenza dati

Dati Open-Meteo sotto **CC BY 4.0**: cita la fonte nei grafici/pubblicazioni
("Weather data by Open-Meteo.com").

## Personalizzare i punti

Modifica `points.csv`: una riga per punto. Aggiungerne è gratis (resti molto sotto
il limite di 10.000 chiamate/giorno). Per un variogramma stabile tieni almeno 30–50
punti ben distribuiti e stratificati.
