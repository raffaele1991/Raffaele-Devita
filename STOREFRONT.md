# Bug Bounty Vulnerability Scanner Agent v2.0

**Lo scanner automatico per bug bounty e penetration testing piu completo sul mercato.**

Trova vulnerabilita in automatico. Risparmi ore di lavoro manuale. Ricevi notifiche in tempo reale quando trova qualcosa.

---

## Cosa fa

Scansiona automaticamente siti web per trovare vulnerabilita di sicurezza. Usato da professionisti di bug bounty e pentester.

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

### Funzionalita extra incluse
- **Scope automatico** da HackerOne, Intigriti, Bugcrowd
- **Notifiche** Telegram e Discord in tempo reale
- **Report** in JSON, HTML (dark mode) e Markdown
- **Rate limiting** e header custom per identificazione bug bounty
- **13 fasi** di scansione orchestrate automaticamente

---

## Prezzi - Abbonamento Mensile

### LITE - 19€/mese
Per chi fa bug bounty come hobby o sta iniziando.

- 1 utente
- Modalita LITE (7 moduli di scansione)
- Aggiornamenti inclusi
- Chiave di licenza personale

### PRO - 49€/mese
Per professionisti e piccoli team di pentesting.

- Fino a 5 utenti
- Modalita LITE + PRO (tutti i 13 moduli)
- Scope automatico da HackerOne/Intigriti/Bugcrowd
- Notifiche Telegram e Discord
- Report HTML, JSON, Markdown
- Supporto email (risposta entro 48h)
- Aggiornamenti inclusi

### ENTERPRISE - 149€/mese
Per aziende e team di sicurezza strutturati.

- Utenti illimitati nella tua organizzazione
- Tutte le funzionalita PRO
- Supporto prioritario (risposta entro 24h)
- Personalizzazioni su richiesta
- Formazione iniziale inclusa (2h)
- Integrazione CI/CD dedicata

### Risparmia con l'abbonamento annuale

| Piano | Mensile | Annuale | Risparmi |
|-------|---------|---------|----------|
| **LITE** | 19€/mese | 190€/anno | 38€ (2 mesi gratis) |
| **PRO** | 49€/mese | 490€/anno | 98€ (2 mesi gratis) |
| **ENTERPRISE** | 149€/mese | 1.490€/anno | 298€ (2 mesi gratis) |

---

## Come funziona

### 1. Scegli il piano e contattami
Scrivi a **devita.raffaele@gmail.com** indicando il piano che vuoi.

### 2. Paga con il metodo che preferisci
- PayPal
- Bonifico bancario
- Carta di credito/debito

### 3. Ricevi il software e la chiave
Dopo il pagamento ricevi via email:
- Il pacchetto software (pronto all'uso)
- La tua chiave di licenza personale

### 4. Attiva e scansiona
```bash
# Attiva la licenza
python3 bbscanner_activate BBSC-LA-TUA-CHIAVE

# Scansiona un target
python3 bbscanner_pro -t example.com
```

### 5. Ogni mese
La licenza si rinnova ogni mese. Se non rinnovi, il software si disattiva automaticamente.

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
         Trovati: 47 sottodomini
  [2/13] httpx - Probing HTTP...
         Attivi: 23 host
  [3/13] Nmap - Scansione porte...
         Porte aperte: 89
  [4/13] Crawler - Deep crawling...
         Pagine: 156 | Form: 12 | Parametri: 45
  ...
  [13/13] Sensitive Files - Completato

  ============================================
   RISULTATI SCANSIONE
  ============================================
   Vulnerabilita trovate: 23
     CRITICAL:  2  ████
     HIGH:      5  ████████
     MEDIUM:    8  ████████████████
     LOW:       8  ████████████████

   Report: reports/example.com_report.html
  ============================================
```

---

## Domande frequenti

**Serve un PC potente?**
No, gira su qualsiasi computer con Python 3.8+. Linux, Mac o Windows.

**Posso provarlo prima di comprare?**
Garanzia soddisfatti o rimborsati entro 30 giorni. Se non ti piace, ti rimborso tutto.

**Come ricevo gli aggiornamenti?**
Ogni mese con il rinnovo ricevi la versione aggiornata.

**Cosa succede se non rinnovo?**
Il software si disattiva. Nessun addebito automatico, nessun vincolo.

**E legale?**
Si, ma solo per attivita autorizzate: programmi di bug bounty ufficiali e penetration testing con contratto scritto.

**Come funziona la protezione?**
Il software e distribuito compilato (non codice sorgente). Ogni chiave e unica, firmata crittograficamente e con scadenza mensile. Senza chiave valida non funziona.

---

## Contatti

**Email:** devita.raffaele@gmail.com
**Autore:** Raffaele De Vita

Per acquisti, supporto tecnico, rinnovi e qualsiasi domanda.

---

*Questo strumento e destinato esclusivamente ad attivita di sicurezza autorizzate (bug bounty, penetration testing con permesso scritto). L'utilizzo non autorizzato contro sistemi di terze parti e illegale.*
