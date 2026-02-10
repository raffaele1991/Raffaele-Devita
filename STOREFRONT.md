# Bug Bounty Vulnerability Scanner Agent v2.0

Lo scanner automatico per bug bounty e penetration testing piu completo sul mercato.

---

## Cosa fa

Scansiona automaticamente siti web per trovare vulnerabilita di sicurezza. Usato da professionisti di bug bounty e pentester per risparmiare ore di lavoro manuale.

### Modalita LITE - 7 moduli di scansione
- Ricognizione automatica (subdomain, porte, tecnologie)
- XSS (Cross-Site Scripting)
- SQL Injection
- SSRF (Server-Side Request Forgery)
- Open Redirect
- Security Headers e CORS
- File sensibili esposti

### Modalita PRO - 13 moduli con tool professionali
Tutto cio che e nella LITE, piu:
- **Subfinder** - Enumerazione sottodomini OSINT
- **httpx** - Probing HTTP e tech detection
- **Nmap** - Scansione porte e fingerprint
- **Deep Crawler** - Scopre pagine, form, parametri nascosti
- **Wayback Machine** - Endpoint storici
- **ffuf** - Fuzzing directory/file
- **JS Scanner** - Estrae API key, secret, endpoint dai file JavaScript
- **Nuclei** - Migliaia di template CVE e misconfiguration
- **Nikto** - Scanner web server
- **Dalfox** - XSS avanzato con bypass WAF
- **SQLMap** - SQL injection con database takeover

### Funzionalita extra
- **Scope automatico** da HackerOne, Intigriti, Bugcrowd
- **Notifiche** Telegram e Discord in tempo reale
- **Report** in JSON, HTML (dark mode) e Markdown
- **Rate limiting** e header custom per identificazione bug bounty
- **13 fasi** di scansione orchestrate automaticamente

---

## Piani e Prezzi

| Piano | Per chi | Cosa include | Supporto | Durata |
|-------|---------|-------------|----------|--------|
| **LITE** | Singolo utente | Modalita LITE (7 moduli) | - | 12 mesi |
| **PRO** | Professionista o team (max 5) | LITE + PRO (13 moduli) | Email (48h) | 12 mesi |
| **ENTERPRISE** | Azienda (utenti illimitati) | Tutto + personalizzazioni + formazione | Prioritario (24h) | 24 mesi |

---

## Come acquistare

1. **Scrivi a** devita.raffaele@gmail.com **indicando il piano che vuoi**
2. Ricevi il preventivo e le modalita di pagamento (PayPal, bonifico, carta)
3. Dopo il pagamento ricevi:
   - I file eseguibili del software (pronti all'uso, nessuna installazione complicata)
   - La tua chiave di licenza personale
4. Attivi la chiave e inizi a scansionare

### Garanzia
Rimborso completo entro **30 giorni** se il software non funziona come descritto.

---

## Demo

```
  ____              ____                    _
 | __ ) _   _  __ _| __ )  ___  _   _ _ __ | |_ _   _
 |  _ \| | | |/ _` |  _ \ / _ \| | | | '_ \| __| | | |
 | |_) | |_| | (_| | |_) | (_) | |_| | | | | |_| |_| |
 |____/ \__,_|\__, |____/ \___/ \__,_|_| |_|\__|\__, |
              |___/                              |___/
      ____                              ____  ____   ___
     / ___|  ___ __ _ _ __  _ __   ___ |  _ \|  _ \ / _ \
     \___ \ / __/ _` | '_ \| '_ \ / _ \| |_) | |_) | | | |
      ___) | (_| (_| | | | | | | |  __/|  __/|  _ <| |_| |
     |____/ \___\__,_|_| |_|_| |_|\___||_|   |_| \_\\___/

  Licenza PRO attiva (cliente@email.com)
  Target: example.com
  Pipeline: subfinder > httpx > nmap > crawler > wayback > ffuf >
            js_scanner > nuclei > nikto > dalfox > sqlmap >
            headers > sensitive_files

  [1/13] Subfinder - Enumerazione sottodomini...
  [2/13] httpx - Probing HTTP...
  ...
  [13/13] Sensitive Files - Scansione completata

  === RISULTATI ===
  Vulnerabilita trovate: 23
    CRITICAL: 2
    HIGH: 5
    MEDIUM: 8
    LOW: 8

  Report HTML: reports/example.com_report.html
  Report JSON: reports/example.com_report.json
```

---

## Protezione

- Software distribuito come **eseguibile compilato** (niente codice sorgente)
- Chiavi di licenza **firmate crittograficamente** e con scadenza
- Ogni chiave e personale: legata al tuo piano e alla tua email
- Senza chiave valida il software non si avvia

---

## Contatti

**Email:** devita.raffaele@gmail.com
**Autore:** Raffaele De Vita

---

*Questo strumento e destinato esclusivamente ad attivita di sicurezza autorizzate (bug bounty, penetration testing con permesso scritto). L'utilizzo non autorizzato contro sistemi di terze parti e illegale.*
