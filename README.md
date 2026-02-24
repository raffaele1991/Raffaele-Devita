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

### Passo 3 — Esporta i dati storici da MT5

Servono almeno **6 mesi** di dati M5 per ciascun simbolo (meglio 1–2 anni).

1. Apri **MetaTrader 5**
2. Menu `Strumenti` → `History Center`
3. Seleziona `XAUUSD` → `M5` → `Export` → salva come **`XAUUSD_M5.csv`**
4. Ripeti per `EURUSD` → salva come **`EURUSD_M5.csv`**
5. Copia entrambi i file nella cartella `trading_system/data/`

```
trading_system/
└── data/
    ├── XAUUSD_M5.csv   ← metti qui
    └── EURUSD_M5.csv   ← metti qui
```

---

### Passo 4 — Addestra i modelli ML

```bash
python trading_system/ml/train.py
```

Lo script legge i CSV, calcola le feature SMC+ML e salva i modelli addestrati.
Output atteso:

```
============================================================
  Addestramento modello: XAUUSD
============================================================
  Candele totali caricate: 120,000
  Periodo: 2023-01-02 → 2024-12-31

  ── RISULTATI TEST ──────────────────────────────
  Accuracy : 0.71
  Precision: 0.74
  Recall   : 0.68
  F1       : 0.71
  AUC-ROC  : 0.78
  Modello salvato in: trading_system/models/model_xauusd.pkl
```

I modelli vengono salvati in `trading_system/models/`.

---

### Passo 5 — Avvia il bot e la dashboard

Apri **due terminali separati**:

**Terminale 1 – Bot di trading:**
```bash
python trading_system/bot.py
```

**Terminale 2 – Dashboard web:**
```bash
python run_dashboard.py
```

La dashboard si apre automaticamente nel browser su **http://localhost:5050**

---

## Dashboard

La dashboard mostra in tempo reale:

- **Saldo** corrente del conto
- **Drawdown giornaliero e totale** con barra colorata (verde → giallo → rosso)
- **Sessione attiva** (LONDON / NY / CLOSED) con countdown
- **Segnali SMC live** per XAUUSD e EURUSD con confidence ML
- **Posizioni aperte** con P&L in tempo reale
- **Perché non apro posizioni?** — motivo preciso ad ogni ciclo
- **Storico trade** della giornata
- **Log live** con auto-scroll e colori per tipo di messaggio
- **Pulsante Stop** per fermare il bot in modo sicuro

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
│   ML Classifier │  Gradient Boosting – 26 feature – soglia 78%
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

## Struttura del progetto

```
trading_system/
├── config.py              ← tutti i parametri configurabili
├── bot.py                 ← avvio del bot live
├── data/                  ← metti qui i CSV esportati da MT5
├── models/                ← modelli ML salvati dopo il training
├── dashboard/
│   ├── app.py             ← server Flask della dashboard
│   └── templates/
│       └── index.html     ← UI web dark theme
├── smc/
│   ├── structure.py       ← rilevamento BOS, CHoCH, trend
│   ├── zones.py           ← Order Block, FVG, Liquidity levels
│   └── detector.py        ← segnale SMC finale
├── ml/
│   ├── features.py        ← feature engineering (26 feature)
│   ├── model.py           ← Gradient Boosting Classifier
│   └── train.py           ← script di training
├── filters/
│   ├── session.py         ← kill zone (London / NY)
│   └── news.py            ← blocco eventi macro (ForexFactory)
├── risk/
│   └── manager.py         ← sizing, drawdown, prop firm rules
└── mt5/
    ├── connector.py       ← connessione e fetch dati MT5
    └── executor.py        ← apertura / chiusura ordini

run_dashboard.py           ← avvio dashboard (apre browser automaticamente)
```

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
