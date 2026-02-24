# SMC + ML Automated Trading System

Sistema di trading automatico basato su **Smart Money Concepts (SMC)** + **Machine Learning**, progettato per operare su **XAUUSD** e **EURUSD** su timeframe M5.
Ottimizzato per superare le challenge delle principali **prop firm** (FTMO, MyFundedFX, The5ers).

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
```

---

## Setup e utilizzo

### 1. Installa le dipendenze

```bash
pip install -r requirements.txt
```

> **Nota:** `MetaTrader5` funziona **solo su Windows** con MT5 installato.

### 2. Esporta i dati da MT5

1. Apri MetaTrader 5
2. Menu `Strumenti` → `History Center`
3. Seleziona `XAUUSD` → `M5` → `Export` → salva come `XAUUSD_M5.csv`
4. Ripeti per `EURUSD` → `EURUSD_M5.csv`
5. Copia entrambi i file in `trading_system/data/`

### 3. Addestra i modelli ML

```bash
python trading_system/ml/train.py
```

Output atteso:
```
Candele totali caricate: 120,000
Accuracy : 0.71
Precision: 0.74
AUC-ROC  : 0.78
Modello salvato in: trading_system/models/model_xauusd.pkl
```

### 4. Configura MT5 in config.py

```python
MT5_ACCOUNT  = 123456        # numero conto FTMO demo
MT5_PASSWORD = "password"
MT5_SERVER   = "FTMO-Demo"
```

### 5. Avvia il bot

```bash
python trading_system/bot.py
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
6. **Kill zone attiva** — siamo in London o NY
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
