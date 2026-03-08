# SMC + ML Automated Trading Bot

Sistema di trading automatico basato su **Smart Money Concepts (SMC)** + **Machine Learning**, progettato per operare su **XAUUSD** e **EURUSD** su timeframe M5.
Ottimizzato per superare le challenge delle principali **prop firm** (FTMO, MyFundedFX, The5ers).

> **Requisiti di sistema:** Windows con MetaTrader 5 installato · Python 3.10+

> **Compatibilità Ubuntu/Linux:** la dashboard, il training ML e il backtest girano su Ubuntu senza modifiche (se i CSV sono già presenti). Il trading live e il download dati richiedono Windows + MT5.

---

## Guida rapida – passo per passo

### Passo 1 — Installa le dipendenze Python

```bash
pip install -r requirements.txt
```

---

### Passo 2 — Avvia la dashboard

```bash
python run_dashboard.py
```

La dashboard si apre automaticamente nel browser su **http://localhost:5050**

Da qui puoi fare **tutto senza toccare il codice**.

---

### Passo 3 — Configura le impostazioni (tab "Impostazioni")

Nella dashboard, clicca il tab **Impostazioni** e compila:

| Sezione | Cosa inserire |
|---|---|
| **Connessione MT5** | Server (es. `FTMO-Demo`), numero conto, password |
| **Strumenti & Sessioni** | Simboli attivi, sessioni London/NY, timeframe |
| **Risk Management** | Rischio per trade, max trade/giorno, limiti drawdown |
| **Modello ML** | Abilita/disabilita ML, soglia confidence minima |
| **Notifiche Telegram** | Token bot, Chat ID, quali notifiche ricevere |

Clicca **"Salva Impostazioni"** — il sistema aggiorna automaticamente `config.py` e `settings.json`.

> **Alternativa manuale:** puoi modificare direttamente `trading_system/config.py`

---

### Passo 4 — Scarica i dati storici (tab "Dati & Modello")

1. Assicurati che **MetaTrader 5 sia aperto** e connesso al conto
2. Scegli quanti anni di storico vuoi (default: **4 anni**)
3. Clicca **"Scarica da MT5"**
4. Aspetta il completamento — vedi la barra di avanzamento per ogni simbolo

I file vengono salvati in `trading_system/data/XAUUSD_M5.csv` e `EURUSD_M5.csv`.

> **Alternativa manuale:** esporta da MT5 → `Strumenti → History Center → XAUUSD → M5 → Export`
> e copia i file in `trading_system/data/`

---

### Passo 5 — Addestra il modello ML (tab "Dati & Modello")

1. Clicca **"Addestra Modello"**
2. Segui l'output in tempo reale nella dashboard
3. Al termine vedrai i file `.pkl` elencati con data e dimensione

Oppure da terminale:

```bash
python trading_system/ml/train.py
```

Output atteso:

```
============================================================
  Addestramento modello: XAUUSD
============================================================
  Candele totali caricate: 210,000
  Periodo: 2021-01-04 → 2024-12-31

  ── RISULTATI TEST ──────────────────────────────
  Accuracy : 0.71
  Precision: 0.74
  Recall   : 0.68
  F1       : 0.71
  AUC-ROC  : 0.78
  Modello salvato in: trading_system/models/model_xauusd.pkl
```

---

### Passo 6 — Avvia il bot (tab "Dashboard")

Clicca **"Avvia Bot"** nella dashboard oppure da terminale:

```bash
python trading_system/bot.py
```

Il bot inizia a operare nelle sessioni configurate (London / NY).

---

### Passo 7 — Esegui un backtest (tab "Backtest")

1. Scegli il simbolo (XAUUSD / EURUSD)
2. Imposta il periodo (data inizio / data fine)
3. Clicca **"Esegui Backtest"**
4. Visualizza i risultati: Win Rate, Profit Factor, Net R, Max Drawdown, Sharpe Ratio, storico trade completo

---

## Dashboard — 5 Tab

### Tab 1 · Dashboard
- **Stato bot** — ONLINE / OFFLINE con timer sessione attiva
- **KPI in tempo reale** — Saldo, DD giornaliero, DD totale, Win Rate, Trade oggi
- **Segnali SMC live** — direzione, confluenze rilevate, confidence ML
- **Posizioni aperte** — simbolo, direzione, entry, SL, TP, P&L corrente
- **Perché non apro posizioni?** — motivo preciso ad ogni ciclo (sessione chiusa, news, DD superato, ecc.)
- **Storico trade di oggi** — con P&L e esito WIN/LOSS

### Tab 2 · Dati & Modello
- **Scarica dati da MT5** — download automatico 1–10 anni di storico M5
- **Barre di avanzamento** per simbolo con stato e numero candele
- **Lista CSV presenti** con righe, date e dimensione
- **Addestra modello ML** — avvia il training con output live in tempo reale
- **Lista modelli .pkl** con data di aggiornamento e dimensione

### Tab 3 · Backtest
- Seleziona simbolo, periodo e avvia il backtest
- **Metriche**: Trade totali, Win Rate, Profit Factor, Net R, Max Drawdown, Balance finale, Net P&L, Sharpe Ratio, Avg Win R, Avg Loss R
- **Storico completo** di tutti i trade con entry, SL, TP, exit, R e P&L

### Tab 4 · Log Live
- Log colorato in tempo reale con auto-scroll
- **Verde** = trade / successi, **Rosso** = errori, **Giallo** = warning, **Grigio** = info

### Tab 5 · Impostazioni
- **Connessione MT5** — server, conto, password (salvati in `settings.json`)
- **Strumenti & Sessioni** — simboli attivi, sessioni London/NY, timeframe
- **Risk Management** — rischio per trade, max trade/giorno, limiti DD, R:R minimo
- **Modello ML** — abilita/disabilita, soglia confidence
- **Notifiche Telegram** — token bot, chat ID, tipologie di notifica
- Il pulsante **"Salva Impostazioni"** aggiorna automaticamente anche `config.py`

---

## Architettura del sistema

```
Dati MT5 (OHLCV M5)
        │
        ▼
┌─────────────────┐
│  SMC Detector   │  BOS / CHoCH / Order Block / FVG / Liquidity
└────────┬────────┘
         │ segnale SMC
         ▼
┌─────────────────┐
│   ML Classifier │  Gradient Boosting – 29 feature – soglia configurabile
└────────┬────────┘
         │ conferma
         ▼
┌─────────────────┐
│  Session Filter │  Kill zone London 08-11 / NY 14-17 (CET)
│  News Filter    │  Blocco automatico eventi high-impact
└────────┬────────┘
         │ via libera
         ▼
┌─────────────────┐
│  Risk Manager   │  Sizing configurabile · DD giornaliero · DD totale
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MT5 Executor   │  Ordini a mercato con SL/TP · chiusura EOD automatica
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  Telegram Bot   │  Notifiche trade / warning / segnali
└─────────────────┘
```

---

## Feature del modello ML (29 feature)

| Categoria | Feature |
|-----------|---------|
| **Candela** | body %, ombre superiore/inferiore, direzione |
| **Rendimenti** | ret 1 / 3 / 5 / 10 / 20 candele |
| **EMA** | distanza dal prezzo vs EMA 9 / 21 / 50 / 100 / 200 |
| **Volatilità** | ATR %, volatilità storica 5 / 20 candele |
| **Momentum** | RSI, MACD, istogramma MACD, Stochastic K/D |
| **SMC** | trend, BOS bull/bear, CHoCH bull/bear, barre dall'ultimo segnale |

**Label:** il trade nella direzione del trend tocca il TP prima dello SL entro 10 candele?

---

## SMC – Logica del segnale

Un trade viene aperto solo se si verificano **tutti** questi elementi:

1. **Trend confermato** — BOS o CHoCH rilevato sulla struttura M5
2. **Order Block attivo** — prezzo ritorna su un OB non invalidato nella direzione del trend
3. **Confluenza FVG** — Fair Value Gap presente nella stessa zona (bonus)
4. **Sweep di liquidità** — equal highs/lows spazzati prima dell'inversione (bonus)
5. **ML confidence ≥ soglia** — il modello conferma il setup (configurabile da dashboard)
6. **Kill zone attiva** — siamo in London (08–11) o NY (14–17) CET
7. **No news** — nessun evento macro nelle prossime 30 minuti

---

## Regole prop firm integrate

| Regola | Default | Limite prop firm |
|--------|---------|-----------------|
| Max daily drawdown | 3% | 4–5% |
| Max total drawdown | 7% | 8–10% |
| Rischio per trade | 0.5% | — |
| Max trade al giorno | 3 | — |
| Chiusura EOD | 21:00 CET | no overnight |
| R:R minimo | 1:2 | — |

Tutti i valori sono modificabili dal tab **Impostazioni** senza toccare il codice.

---

## API della dashboard

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/` | Dashboard HTML |
| GET | `/api/state` | Stato bot corrente (JSON) |
| GET | `/api/log` | Ultime N righe di log |
| POST | `/api/control` | `{"action": "start"\|"stop"}` |
| POST | `/api/data/download` | Avvia download dati MT5 `{"years": 4}` |
| GET | `/api/data/status` | Stato e progresso del download |
| GET | `/api/data/files` | Elenco CSV con statistiche |
| POST | `/api/train` | Avvia training modello ML |
| GET | `/api/train/status` | Stato training + output live |
| GET | `/api/models/files` | Elenco modelli `.pkl` |
| POST | `/api/backtest` | Avvia backtest `{"symbol", "start_date", "end_date"}` |
| GET | `/api/backtest/status` | Stato e risultati del backtest |
| GET | `/api/settings` | Legge le impostazioni correnti |
| POST | `/api/settings` | Salva impostazioni e aggiorna config.py |

---

## Struttura del progetto

```
trading_system/
├── config.py              ← parametri configurabili (aggiornato automaticamente dalla dashboard)
├── settings.json          ← impostazioni salvate dalla dashboard (generato automaticamente)
├── bot.py                 ← avvio del bot live
├── data/
│   ├── downloader.py      ← download automatico storico da MT5
│   ├── XAUUSD_M5.csv      ← (generato dopo download)
│   └── EURUSD_M5.csv      ← (generato dopo download)
├── models/
│   ├── model_xauusd.pkl   ← (generato dopo training)
│   └── model_eurusd.pkl   ← (generato dopo training)
├── dashboard/
│   ├── app.py             ← server Flask con tutte le API
│   └── templates/
│       └── index.html     ← UI web dark theme (5 tab)
├── smc/
│   ├── structure.py       ← rilevamento BOS, CHoCH, trend
│   ├── zones.py           ← Order Block, FVG, Liquidity levels
│   └── detector.py        ← segnale SMC finale
├── ml/
│   ├── features.py        ← feature engineering (29 feature)
│   ├── model.py           ← Gradient Boosting Classifier
│   └── train.py           ← script di training
├── filters/
│   ├── session.py         ← kill zone (London / NY)
│   └── news.py            ← blocco eventi macro (ForexFactory)
├── risk/
│   └── manager.py         ← sizing, drawdown, prop firm rules
├── backtest/
│   └── engine.py          ← motore di backtest su dati storici
└── mt5/
    ├── connector.py       ← connessione, fetch dati e download storico
    └── executor.py        ← apertura / chiusura ordini

run_dashboard.py           ← avvio dashboard (apre browser automaticamente)
requirements.txt           ← dipendenze Python
```

---

## Simboli supportati

| Simbolo | Tipo | Note |
|---------|------|------|
| XAUUSD | Oro / USD | 1 pip = $0.01 |
| EURUSD | Forex | 1 pip = $0.0001 |
| GBPUSD | Forex | abilitabile dalle impostazioni |

---

## Disclaimer

Questo sistema è sviluppato a scopo educativo e di ricerca personale.
Il trading comporta rischi significativi di perdita del capitale.
Testa sempre su **conto demo** prima di usare capitali reali.

---

Copyright (c) 2025-2026 Raffaele De Vita. Tutti i diritti riservati.
