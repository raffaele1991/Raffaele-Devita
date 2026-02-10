# Bug Bounty Vulnerability Scanner Agent v2.0

Agent automatico per la scansione di vulnerabilita web, progettato per attivita di bug bounty e penetration testing autorizzato.

## Due modalita

### Modalita LITE (solo Python, zero dipendenze esterne)
Scanner interno con payload propri. Perfetto per iniziare.

```bash
python -m bugbounty_scanner.cli -t example.com
```

### Modalita PRO v2.0 (orchestratore tool professionali)
Coordina automaticamente **13 fasi di scansione** con tool professionali + moduli interni.

```bash
python -m bugbounty_scanner.cli_pro -t example.com
```

---

## Funzionalita Principali

### Scope Automatico da Programma Bug Bounty
Estrae automaticamente scope e out-of-scope dalla pagina del programma su **HackerOne, Intigriti, Bugcrowd**:

```bash
python -m bugbounty_scanner.cli_pro -t example.com \
  --program "https://hackerone.com/example"
```

Oppure da un file di testo (un dominio per riga):

```bash
python -m bugbounty_scanner.cli_pro -t example.com --scope scope.txt
```

Il tool estrae:
- Domini in scope e out-of-scope
- Regole del programma
- Vulnerabilita escluse (self-xss, ecc.)
- Blocca automaticamente le richieste verso domini fuori scope

### Identificazione Bug Bounty
```bash
python -m bugbounty_scanner.cli_pro -t example.com \
  -H "X-Bug-Bounty: kobraraf91" \
  --email kobraraf91@intigriti.me \
  --rate-limit 5
```

### Notifiche Telegram e Discord
Ricevi avvisi sul telefono quando trova vulnerabilita:

```bash
# Telegram
python -m bugbounty_scanner.cli_pro -t example.com \
  --telegram-token "TOKEN_BOT" \
  --telegram-chat "CHAT_ID"

# Discord
python -m bugbounty_scanner.cli_pro -t example.com \
  --discord-webhook "URL_WEBHOOK"
```

---

## Pipeline di Scansione PRO (13 fasi)

| # | Tool/Modulo | Cosa fa | Fase |
|---|-------------|---------|------|
| 1 | **Subfinder** | Enumerazione sottodomini passiva (OSINT) | Ricognizione |
| 2 | **httpx** | Probing HTTP, tech detection, status check | Ricognizione |
| 3 | **Nmap** | Scansione porte e fingerprint servizi | Ricognizione |
| 4 | **Crawler** | Scopre pagine, form, parametri, email | Discovery |
| 5 | **Wayback** | Cerca endpoint storici dalla Wayback Machine | Discovery |
| 6 | **ffuf** | Fuzzing directory/file (brute-force veloce) | Discovery |
| 7 | **JS Scanner** | Estrae API key, secret, endpoint dai file .js | Analisi |
| 8 | **Nuclei** | Migliaia di template per CVE, misconfig, exposure | Scansione |
| 9 | **Nikto** | Scanner web server (CGI, versioni obsolete) | Scansione |
| 10 | **Dalfox** | XSS avanzato con bypass WAF e DOM analysis | Exploit |
| 11 | **SQLMap** | SQL injection con database takeover | Exploit |
| 12 | **Headers** | Analisi header sicurezza, CORS, cookie | Check |
| 13 | **Sensitive Files** | File e endpoint sensibili esposti | Check |

## Installazione

### 1. Scarica i file
Dopo l'acquisto riceverai un archivio con i file eseguibili. Estraili e rendili eseguibili:
```bash
chmod +x bbscanner bbscanner_pro bbscanner_activate
```

### 2. Attiva la licenza
```bash
./bbscanner_activate BBSC-LA-TUA-CHIAVE
```

### 3. (Solo PRO) Installa i tool esterni
La modalita PRO richiede tool professionali (Nuclei, Nmap, etc.):
```bash
chmod +x install_tools.sh
./install_tools.sh
```

### 4. Verifica che tutto funzioni
```bash
./bbscanner_pro -t example.com --check
```

## Esempi di Utilizzo

### Comando completo per bug bounty
```bash
python -m bugbounty_scanner.cli_pro \
  -t example.com \
  --program "https://app.intigriti.com/researcher/programs/company/program" \
  -H "X-Bug-Bounty: kobraraf91" \
  --email kobraraf91@intigriti.me \
  --rate-limit 5 \
  --telegram-token "TOKEN" \
  --telegram-chat "CHAT_ID"
```

### Modalita LITE
```bash
# Scansione completa
python -m bugbounty_scanner.cli -t example.com

# Solo XSS e SQLi con header custom
python -m bugbounty_scanner.cli -t "https://example.com/search?q=test&id=1" \
  -m xss sqli -H "X-Bug-Bounty: kobraraf91" --rate-limit 5

# Salta ricognizione
python -m bugbounty_scanner.cli -t example.com --no-recon
```

### Modalita PRO
```bash
# Scansione completa con tutti i tool
python -m bugbounty_scanner.cli_pro -t example.com

# Solo alcuni tool
python -m bugbounty_scanner.cli_pro -t example.com --pipeline subfinder httpx nuclei

# Solo vulnerabilita critiche con Nuclei
python -m bugbounty_scanner.cli_pro -t example.com --nuclei-severity critical,high

# Nuclei con tag specifici
python -m bugbounty_scanner.cli_pro -t example.com --nuclei-tags cve,misconfig

# Scansione porte completa
python -m bugbounty_scanner.cli_pro -t example.com --nmap-scan full

# SQLMap aggressivo
python -m bugbounty_scanner.cli_pro -t "https://example.com/page?id=1" \
  --sqlmap-level 3 --sqlmap-risk 2

# Crawler profondo
python -m bugbounty_scanner.cli_pro -t example.com --crawl-depth 5 --crawl-pages 200
```

## Tutte le Opzioni CLI PRO

| Flag | Descrizione |
|------|-------------|
| **Target** | |
| `-t, --target` | URL o dominio target (obbligatorio) |
| `--pipeline` | Tool da eseguire (default: tutti) |
| `--check` | Verifica tool installati ed esci |
| **Programma BB** | |
| `--program` | URL programma HackerOne/Intigriti/Bugcrowd (estrae scope) |
| `--scope` | File scope (un dominio per riga) |
| **Identificazione** | |
| `-H, --header` | Header custom (ripetibile) |
| `--email` | Email identificativa |
| `--rate-limit` | Max richieste al secondo (default: 5) |
| **Notifiche** | |
| `--telegram-token` | Token bot Telegram |
| `--telegram-chat` | Chat ID Telegram |
| `--discord-webhook` | URL webhook Discord |
| `--notify-severity` | Gravita minima notifiche: CRITICAL, HIGH, MEDIUM, LOW, INFO |
| **Crawler** | |
| `--crawl-depth` | Profondita crawling (default: 3) |
| `--crawl-pages` | Max pagine da crawlare (default: 100) |
| **Nuclei** | |
| `--nuclei-severity` | Filtro gravita (es: critical,high) |
| `--nuclei-tags` | Filtro tag (es: cve,misconfig) |
| `--nuclei-templates` | Path template custom |
| `--nuclei-rate` | Rate limit Nuclei (default: 100) |
| **Nmap** | |
| `--nmap-scan` | quick, default, full |
| **SQLMap** | |
| `--sqlmap-level` | Livello test 1-5 |
| `--sqlmap-risk` | Rischio 1-3 |
| **ffuf** | |
| `--ffuf-wordlist` | Wordlist custom |
| `--ffuf-threads` | Thread ffuf (default: 40) |
| **Output** | |
| `-o, --output-dir` | Cartella report (default: reports) |
| `-f, --format` | json, html, markdown, all |
| `-v, --verbose` | Output dettagliato |
| `-q, --quiet` | Output minimo |

## Struttura del Progetto

```
bugbounty_scanner/
  __init__.py             # Package principale
  config.py               # Configurazione, payload, costanti
  scanner.py              # Motore scansione LITE
  orchestrator.py         # Motore scansione PRO (orchestratore)
  reporter.py             # Report: JSON, HTML (dark-mode), Markdown
  http_session.py         # Sessione HTTP con rate limiting e header custom
  program_parser.py       # Parser programmi BB (HackerOne, Intigriti, Bugcrowd)
  scope_checker.py        # Verificatore scope in/out
  notifier.py             # Notifiche Telegram e Discord
  cli.py                  # CLI modalita LITE
  cli_pro.py              # CLI modalita PRO v2.0
  modules/                # Moduli interni
    recon.py              #   Ricognizione (subdomain, porte, tech)
    crawler.py            #   Deep crawler (pagine, form, parametri)
    wayback.py            #   Wayback Machine (endpoint storici)
    js_scanner.py         #   JavaScript scanner (secret, API key, endpoint)
    headers.py            #   Security headers e CORS
    xss.py                #   Cross-Site Scripting
    sqli.py               #   SQL Injection
    ssrf.py               #   SSRF
    open_redirect.py      #   Open Redirect
    sensitive_files.py    #   File sensibili esposti
  tools/                  # Wrapper tool professionali
    base.py               #   Classe base wrapper
    subfinder.py          #   Subfinder
    httpx_tool.py         #   httpx
    nmap_tool.py          #   Nmap
    nuclei_tool.py        #   Nuclei
    ffuf_tool.py          #   ffuf
    sqlmap_tool.py        #   SQLMap
    dalfox_tool.py        #   Dalfox
    nikto_tool.py         #   Nikto
install_tools.sh          # Installer automatico tool
```

## Codici di Uscita

| Codice | Significato |
|--------|-------------|
| 0 | Nessuna vulnerabilita critica/alta/media |
| 1 | Vulnerabilita MEDIE trovate |
| 2 | Vulnerabilita CRITICHE o ALTE trovate |

## Software a Pagamento - Licenza Richiesta

Questo software e **a pagamento** e protetto da un **sistema di chiavi di licenza**.
Senza una chiave valida il programma **non si avvia**.

### Piani disponibili - Abbonamento mensile

| Piano | Prezzo | Per chi | Cosa include | Supporto |
|-------|--------|---------|-------------|----------|
| **LITE** | **19€/mese** | Singolo utente | Modalita LITE (7 moduli) | - |
| **PRO** | **49€/mese** | Professionista o team (max 5) | LITE + PRO (tutti i 13 moduli) | Email (48h) |
| **ENTERPRISE** | **149€/mese** | Azienda (utenti illimitati) | Tutto PRO + personalizzazioni + formazione | Prioritario (24h) |

Risparmia con l'annuale: **2 mesi gratis** (LITE 190€/anno, PRO 490€/anno, ENTERPRISE 1.490€/anno)

### Come funziona l'acquisto

1. **Contattami** via email a **devita.raffaele@gmail.com** specificando:
   - Quale piano vuoi (LITE, PRO o ENTERPRISE)
   - Per quante persone/quale azienda
2. **Ricevi il preventivo** con il prezzo e le modalita di pagamento:
   - PayPal
   - Bonifico bancario
   - Carta di credito/debito
3. **Dopo il pagamento** ricevi via email:
   - I **file eseguibili** del software (gia compilati, pronti all'uso)
   - La tua **chiave di licenza personale** (formato: `BBSC-...`)
   - Le istruzioni di installazione
4. **Attiva la chiave** sul tuo computer:
   ```bash
   ./bbscanner_activate BBSC-LA-TUA-CHIAVE
   ```
5. **Fatto!** Ora puoi usare lo scanner:
   ```bash
   ./bbscanner -t example.com          # Modalita LITE
   ./bbscanner_pro -t example.com      # Modalita PRO
   ```

### Protezione anti-pirateria

Il software viene distribuito come **eseguibile compilato** (non come codice sorgente):

- Il codice sorgente **non e incluso**: ricevi solo i file eseguibili
- Ogni chiave e **unica e personale**, legata alla tua email e al tuo piano
- Ogni chiave ha una **data di scadenza** (12 o 24 mesi in base al piano)
- Le chiavi sono **firmate crittograficamente**: non possono essere generate, modificate o falsificate
- Chi ha una licenza **LITE** non puo usare la modalita **PRO**
- **Senza chiave valida il software non si avvia**

### Verifica stato licenza

Per vedere se la tua licenza e attiva e quando scade:
```bash
./bbscanner_activate
```

### Rinnovo

Alla scadenza della licenza il software smette di funzionare. Per rinnovare scrivi a **devita.raffaele@gmail.com** e riceverai una nuova chiave.

### Garanzia

Rimborso completo entro **30 giorni** dall'acquisto se il software non funziona come descritto in questa documentazione.

### Termini completi

Consulta il file [LICENSE](LICENSE) per tutti i termini e condizioni del contratto di licenza.

---

## Disclaimer

Questo strumento deve essere utilizzato **esclusivamente** per attivita di sicurezza autorizzate (bug bounty, penetration testing con permesso scritto). L'utilizzo non autorizzato contro sistemi di terze parti e illegale.

---

Copyright (c) 2025-2026 Raffaele De Vita. Tutti i diritti riservati.
