# Bug Bounty Vulnerability Scanner Agent

Agent automatico per la scansione di vulnerabilita web, progettato per attivita di bug bounty e penetration testing autorizzato.

## Due modalita

### Modalita LITE (solo Python, zero dipendenze esterne)
Scanner interno con payload propri. Perfetto per iniziare.

```bash
python -m bugbounty_scanner.cli -t example.com
```

### Modalita PRO (orchestratore tool professionali)
Coordina automaticamente: **Subfinder + httpx + Nmap + ffuf + Nuclei + Nikto + Dalfox + SQLMap**.

```bash
python -m bugbounty_scanner.cli_pro -t example.com
```

---

## Tool Professionali Integrati (Modalita PRO)

| Tool | Cosa fa | Fase |
|------|---------|------|
| **Subfinder** | Enumerazione sottodomini passiva (OSINT) | Ricognizione |
| **httpx** | Probing HTTP, tech detection, status check | Ricognizione |
| **Nmap** | Scansione porte e fingerprint servizi | Ricognizione |
| **ffuf** | Fuzzing directory/file (brute-force veloce) | Discovery |
| **Nuclei** | Migliaia di template per CVE, misconfig, exposure | Scansione |
| **Nikto** | Scanner web server (CGI, versioni obsolete) | Scansione |
| **Dalfox** | XSS avanzato con bypass WAF e DOM analysis | Exploit |
| **SQLMap** | SQL injection con database takeover | Exploit |

La pipeline li esegue in ordine intelligente: prima trova i target, poi li analizza, poi li testa.

## Installazione Rapida

### 1. Dipendenze Python
```bash
pip install -r requirements.txt
```

### 2. Tool professionali (per modalita PRO)
```bash
chmod +x install_tools.sh
./install_tools.sh
```

### 3. Verifica installazione
```bash
python -m bugbounty_scanner.cli_pro -t example.com --check
```

## Utilizzo - Modalita LITE

```bash
# Scansione completa
python -m bugbounty_scanner.cli -t example.com

# Solo XSS e SQLi
python -m bugbounty_scanner.cli -t example.com -m xss sqli

# Con parametri URL (migliore per XSS/SQLi)
python -m bugbounty_scanner.cli -t "https://example.com/search?q=test&id=1"

# Salta ricognizione
python -m bugbounty_scanner.cli -t example.com --no-recon

# Report solo HTML
python -m bugbounty_scanner.cli -t example.com -f html
```

## Utilizzo - Modalita PRO

```bash
# Scansione completa con tutti i tool
python -m bugbounty_scanner.cli_pro -t example.com

# Solo alcuni tool
python -m bugbounty_scanner.cli_pro -t example.com --pipeline subfinder httpx nuclei

# Solo vulnerabilita critiche e alte con Nuclei
python -m bugbounty_scanner.cli_pro -t example.com --nuclei-severity critical,high

# Nuclei con tag specifici (CVE, misconfig, ecc.)
python -m bugbounty_scanner.cli_pro -t example.com --nuclei-tags cve,misconfig

# Scansione porte completa con Nmap
python -m bugbounty_scanner.cli_pro -t example.com --nmap-scan full

# SQLMap aggressivo (livello 3, rischio 2)
python -m bugbounty_scanner.cli_pro -t "https://example.com/page?id=1" --sqlmap-level 3 --sqlmap-risk 2

# Wordlist custom per ffuf
python -m bugbounty_scanner.cli_pro -t example.com --ffuf-wordlist /path/to/wordlist.txt

# Output dettagliato
python -m bugbounty_scanner.cli_pro -t example.com -v -f html
```

## Opzioni CLI PRO

| Flag | Descrizione |
|------|-------------|
| `-t, --target` | URL o dominio target (obbligatorio) |
| `--pipeline` | Tool da eseguire (default: tutti) |
| `--check` | Verifica tool installati ed esci |
| `--strict` | Fallisci se un tool manca |
| `--nuclei-severity` | Filtro gravita Nuclei (es: critical,high) |
| `--nuclei-tags` | Filtro tag Nuclei (es: cve,misconfig) |
| `--nuclei-templates` | Path template Nuclei custom |
| `--nmap-scan` | Tipo scansione: quick, default, full |
| `--sqlmap-level` | Livello test SQLMap 1-5 |
| `--sqlmap-risk` | Rischio SQLMap 1-3 |
| `--ffuf-wordlist` | Wordlist custom per ffuf |
| `-o, --output-dir` | Cartella report (default: reports) |
| `-f, --format` | Formato: json, html, markdown, all |
| `-v, --verbose` | Output dettagliato |

## Struttura del Progetto

```
bugbounty_scanner/
  __init__.py             # Package principale
  config.py               # Configurazione, payload, costanti
  scanner.py              # Motore scansione LITE
  orchestrator.py         # Motore scansione PRO (orchestratore)
  reporter.py             # Report: JSON, HTML (dark-mode), Markdown
  cli.py                  # CLI modalita LITE
  cli_pro.py              # CLI modalita PRO
  modules/                # Moduli interni (LITE)
    recon.py              #   Ricognizione
    headers.py            #   Security headers
    xss.py                #   Cross-Site Scripting
    sqli.py               #   SQL Injection
    ssrf.py               #   SSRF
    open_redirect.py      #   Open Redirect
    sensitive_files.py    #   File sensibili
  tools/                  # Wrapper tool professionali (PRO)
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

## Disclaimer

Questo strumento deve essere utilizzato **esclusivamente** per attivita di sicurezza autorizzate (bug bounty, penetration testing con permesso scritto). L'utilizzo non autorizzato contro sistemi di terze parti e illegale.
