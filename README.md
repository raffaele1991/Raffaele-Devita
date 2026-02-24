# SMC + ML Automated Trading System

Sistema di trading automatico basato su **Smart Money Concepts (SMC)** + **Machine Learning**, progettato per operare su **XAUUSD** e **EURUSD** su timeframe M5.
Ottimizzato per superare le challenge delle principali **prop firm** (FTMO, MyFundedFX, The5ers).

> **Requisiti di sistema:** Windows con MetaTrader 5 installato · Python 3.10+

---

## Come iniziare – passo per passo

### Passo 1 — Installa le dipendenze Python

```bash
pip install -r requirements.txt
```

---

### Passo 2 — Configura il conto MT5

Apri `trading_system/config.py` e compila le credenziali del tuo conto:

```python
MT5_ACCOUNT  = 123456        # numero conto (es. FTMO demo)
MT5_PASSWORD = "tuapassword"
MT5_SERVER   = "FTMO-Demo"   # nome server visibile nel login MT5
```

---

### Passo 3 — Avvia la dashboard

```bash
python run_dashboard.py
```

La dashboard si apre nel browser su **http://localhost:5050**

Da qui puoi fare tutto senza usare il terminale:

---

### Passo 4 — Scarica i dati storici (dalla dashboard)

Nella sezione **"Dati Storici MT5"** della dashboard:

1. Assicurati che **MetaTrader 5 sia aperto** e connesso al conto
2. Scegli quanti anni di storico vuoi (default: **4 anni**)
3. Clicca **"Scarica da MT5"**
4. Aspetta: il sistema scarica automaticamente i dati M5 per XAUUSD e EURUSD e li salva in `trading_system/data/`

Vedrai una barra di avanzamento per ogni simbolo con il numero di candele scaricate e il periodo coperto.

> **Alternativa manuale:** se preferisci, puoi esportare i CSV da MT5 manualmente:
> `Strumenti → History Center → XAUUSD → M5 → Export → XAUUSD_M5.csv`
> e copiare i file in `trading_system/data/`

---

### Passo 5 — Addestra il modello ML (dalla dashboard)

Nella sezione **"Training Modello ML"** della dashboard:

1. Clicca **"Addestra Modello"**
2. Segui l'output in tempo reale direttamente nella dashboard
3. Al termine vedrai i modelli `.pkl` elencati con data e dimensione

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

### Passo 6 — Avvia il bot

Apri un secondo terminale e lancia il bot:

```bash
python trading_system/bot.py
```

Oppure usa il pulsante **"Avvia Bot"** direttamente dalla dashboard.

---

## Dashboard

La dashboard è l'interfaccia centrale del sistema. Aprila con:

```bash
python run_dashboard.py
```

Poi vai su **http://localhost:5050**

### Sezioni disponibili

#### Stato e controllo bot
- **Status pill** — RUNNING / STOPPED / OFFLINE con indicatore animato
- **Sessione attiva** — LONDON (08–11) / NY (14–17) / CLOSED con countdown
- **Pulsante Avvia / Stop** — controlla il bot in modo sicuro

#### KPI in tempo reale
- **Saldo** corrente del conto
- **Drawdown giornaliero** con barra colorata (verde → giallo → rosso, limite 3%)
- **Drawdown totale** con barra (limite 7%)
- **Win rate** globale (win / loss)
- **Trade oggi** su massimo 3 al giorno

#### Segnali e posizioni
- **Segnali SMC live** per XAUUSD e EURUSD — direzione, confidence ML, motivo
- **Posizioni aperte** con simbolo, direzione, lot size, entry price, P&L corrente

#### Analisi
- **Perché non apro posizioni?** — motivo preciso ad ogni ciclo (sessione chiusa, news, DD superato, etc.)
- **Storico trade** della giornata con esito WIN/LOSS e P&L

#### Dati & Modello *(novità)*
- **Scarica dati da MT5** — download automatico di 1–10 anni di storico M5 direttamente da MT5
  - Barre di avanzamento per simbolo con stato e numero candele
  - Lista CSV presenti con righe, date e dimensione
- **Addestra modello ML** — avvia il training con output live
  - Log di training in tempo reale nella dashboard
  - Lista modelli `.pkl` con data di aggiornamento

#### Log live
- Log colorato in tempo reale con auto-scroll
- Colori per tipo: errori (rosso), warning (giallo), trade (verde), SMC/ML (blu)

---

## Download automatico dati MT5

Il sistema include un modulo dedicato per scaricare automaticamente lo storico da MT5:

```python
# Da codice
from trading_system.data.downloader import start_download, get_status

start_download(years=4)   # avvia in background
status = get_status()     # controlla lo stato
```

```bash
# Da terminale
python trading_system/data/downloader.py 4   # scarica 4 anni
```

Il file viene salvato automaticamente in `trading_system/data/XAUUSD_M5.csv` e `EURUSD_M5.csv`, pronti per il training.

**Requisito:** MetaTrader 5 deve essere aperto e connesso al conto configurato in `config.py`.

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
│   ML Classifier │  Gradient Boosting – 29 feature – soglia 78%
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
│  Risk Manager   │  Sizing 0.5%/trade · max 3% DD giornaliero · max 7% totale
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MT5 Executor   │  Ordini a mercato con SL/TP · chiusura EOD automatica
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

## Struttura del progetto

```
trading_system/
├── config.py              ← tutti i parametri configurabili
├── bot.py                 ← avvio del bot live
├── data/
│   ├── downloader.py      ← download automatico storico da MT5
│   ├── XAUUSD_M5.csv      ← (generato dopo download)
│   └── EURUSD_M5.csv      ← (generato dopo download)
├── models/
│   ├── model_xauusd.pkl   ← (generato dopo training)
│   └── model_eurusd.pkl   ← (generato dopo training)
├── dashboard/
│   ├── app.py             ← server Flask con API download/training/bot
│   └── templates/
│       └── index.html     ← UI web dark theme
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
└── mt5/
    ├── connector.py       ← connessione, fetch dati e download storico
    └── executor.py        ← apertura / chiusura ordini

run_dashboard.py           ← avvio dashboard (apre browser automaticamente)
```

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

---

## Regole prop firm integrate

| Regola | Valore configurato | Limite prop firm |
|--------|-------------------|-----------------|
| Max daily drawdown | 3% | 4–5% |
| Max total drawdown | 7% | 8–10% |
| Rischio per trade | 0.5% | — |
| Max trade al giorno | 3 | — |
| Chiusura EOD | 21:00 CET | no overnight |
| R:R minimo | 1:2 | — |

---

## SMC – Logica del segnale

Un trade viene aperto solo se si verificano **tutti** questi elementi:

1. **Trend confermato** — BOS o CHoCH rilevato sulla struttura M5
2. **Order Block attivo** — prezzo ritorna su un OB non invalidato nella direzione del trend
3. **Confluenza FVG** — Fair Value Gap presente nella stessa zona (bonus)
4. **Sweep di liquidità** — equal highs/lows spazzati prima dell'inversione (bonus)
5. **ML confidence ≥ 78%** — il modello conferma il setup
6. **Kill zone attiva** — siamo in London (08–11) o NY (14–17) CET
7. **No news** — nessun evento macro nelle prossime 30 minuti

---

## Simboli supportati

| Simbolo | Tipo | Note |
|---------|------|------|
| XAUUSD | Oro / USD | 1 pip = $0.01 |
| EURUSD | Forex | 1 pip = $0.0001 |

---

## Disclaimer

Questo sistema è sviluppato a scopo educativo e di ricerca personale.
Il trading comporta rischi significativi di perdita del capitale.
Testa sempre su **conto demo** prima di usare capitali reali.

---

Copyright (c) 2025-2026 Raffaele De Vita. Tutti i diritti riservati.
