# Bug Bounty Vulnerability Scanner Agent

Agent automatico per la scansione di vulnerabilita web, progettato per attivita di bug bounty e penetration testing autorizzato.

## Moduli di Scansione

| Modulo | Descrizione |
|--------|-------------|
| **recon** | Enumerazione sottodomini, scansione porte, rilevamento tecnologie |
| **headers** | Analisi header di sicurezza, CORS, cookie |
| **xss** | Rilevamento XSS riflesso e DOM-based |
| **sqli** | SQL Injection (error-based, boolean-blind, time-blind) |
| **ssrf** | Server-Side Request Forgery |
| **open_redirect** | Redirect aperti |
| **sensitive_files** | File e endpoint sensibili esposti |

## Installazione

```bash
pip install -r requirements.txt
```

Oppure installa come pacchetto:

```bash
pip install -e .
```

## Utilizzo

### Scansione completa

```bash
python -m bugbounty_scanner.cli -t example.com
```

### Solo moduli specifici

```bash
python -m bugbounty_scanner.cli -t example.com -m xss sqli headers
```

### Scansione con parametri URL

```bash
python -m bugbounty_scanner.cli -t "https://example.com/search?q=test&id=1"
```

### Salta la ricognizione

```bash
python -m bugbounty_scanner.cli -t example.com --no-recon
```

### Report in formato specifico

```bash
python -m bugbounty_scanner.cli -t example.com -f html
python -m bugbounty_scanner.cli -t example.com -f json markdown
```

### Opzioni avanzate

```bash
python -m bugbounty_scanner.cli -t example.com --threads 20 --delay 1.0 -v -o output/
```

## Opzioni CLI

| Flag | Descrizione |
|------|-------------|
| `-t, --target` | URL o dominio target (obbligatorio) |
| `-m, --modules` | Moduli da eseguire (default: tutti) |
| `--no-recon` | Salta ricognizione |
| `--threads` | Thread paralleli (default: 10) |
| `--delay` | Ritardo tra moduli in secondi (default: 0.5) |
| `-o, --output-dir` | Cartella report (default: reports) |
| `-f, --format` | Formato report: json, html, markdown, all |
| `-v, --verbose` | Output dettagliato |
| `-q, --quiet` | Output minimo |

## Struttura del Progetto

```
bugbounty_scanner/
  __init__.py          # Package principale
  cli.py               # Interfaccia riga di comando
  config.py            # Configurazione, payload, costanti
  scanner.py           # Motore di scansione principale
  reporter.py          # Generazione report (JSON, HTML, Markdown)
  modules/
    __init__.py
    recon.py            # Ricognizione (subdomain, porte, tech)
    headers.py          # Analisi header di sicurezza
    xss.py              # Cross-Site Scripting
    sqli.py             # SQL Injection
    ssrf.py             # Server-Side Request Forgery
    open_redirect.py    # Redirect aperti
    sensitive_files.py  # File sensibili esposti
```

## Codici di Uscita

| Codice | Significato |
|--------|-------------|
| 0 | Nessuna vulnerabilita critica/alta/media trovata |
| 1 | Vulnerabilita di gravita MEDIA trovate |
| 2 | Vulnerabilita CRITICHE o ALTE trovate |

## Disclaimer

Questo strumento deve essere utilizzato esclusivamente per attivita di sicurezza autorizzate (bug bounty, penetration testing con permesso scritto). L'utilizzo non autorizzato contro sistemi di terze parti e illegale.
