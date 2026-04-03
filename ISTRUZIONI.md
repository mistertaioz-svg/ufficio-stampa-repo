 # ArtAgent Bot — Guida Completa al Setup

## Panoramica

Questo bot Telegram funziona come il tuo assistente artistico personale. Usa Claude (Anthropic) come intelligenza artificiale e un file JSON **persistente** come database del tuo profilo artistico. Il database vive su un Railway Volume ed è sincronizzato automaticamente su GitHub ad ogni modifica: i tuoi dati sono sempre al sicuro.

**Costo stimato:** solo il consumo API di Anthropic (pochi centesimi per conversazione). Railway Hobby plan a $5/mese.

---

## STEP 1 — Creare il Bot Telegram

1. Apri Telegram e cerca **@BotFather**
2. Scrivi `/newbot`
3. Scegli un **nome** per il bot (es. "ArtAgent di Mirco")
4. Scegli un **username** unico che finisca con `bot` (es. `mirco_artagent_bot`)
5. BotFather ti darà un **token** tipo: `7123456789:AAH...` — **copialo e salvalo**, ti servirà dopo

### Personalizzare il bot (opzionale)
- `/setdescription` — Aggiungi una descrizione
- `/setabouttext` — Testo "Chi è questo bot"
- `/setuserpic` — Foto profilo del bot

---

## STEP 2 — Ottenere il tuo Telegram ID

Il bot risponde solo a te. Per questo serve il tuo ID numerico Telegram.

1. Cerca su Telegram il bot **@userinfobot**
2. Scrivici `/start`
3. Ti risponderà con il tuo **ID numerico** (es. `123456789`) — **salvalo**

---

## STEP 3 — Ottenere la API Key Anthropic

1. Vai su [console.anthropic.com](https://console.anthropic.com)
2. Crea un account (o accedi se ne hai già uno)
3. Vai su **Settings → API Keys**
4. Clicca **Create Key**
5. Copia la chiave (inizia con `sk-ant-...`) — **salvala**, non sarà più visibile

### Aggiungere credito
- Vai su **Settings → Billing**
- Aggiungi un metodo di pagamento
- $5 di credito bastano per centinaia di conversazioni

---

## STEP 4 — Creare un GitHub Token per il Backup Automatico

Questo token permette al bot di salvare il database su GitHub ogni volta che lo aggiorna, così non perdi mai nulla anche se il volume di Railway dovesse avere problemi.

1. Vai su **github.com** (accedi al tuo account)
2. Clicca sulla tua **foto profilo** in alto a destra → **Settings**
3. Scorri in fondo al menu laterale sinistro → clicca **Developer settings**
4. Clicca **Personal access tokens → Tokens (classic)**
5. Clicca **Generate new token → Generate new token (classic)**
6. **Note**: scrivi `ArtAgent Bot`
7. **Expiration**: scegli `No expiration` (o 1 anno se preferisci)
8. **Seleziona solo questo permesso**: ✅ `repo` (spunta tutta la voce `repo`)
9. Clicca **Generate token**
10. Copia il token (inizia con `ghp_...`) — **salvalo subito**, sparisce se ricarichi la pagina

---

## STEP 5 — Caricare il Codice su GitHub

1. Vai su [github.com](https://github.com) e accedi
2. Clicca il bottone **"+"** in alto a destra → **New repository**
3. Nome: `art-agent-bot`
4. Seleziona **Private** (importante per sicurezza)
5. Clicca **Create repository**

### Caricare i file
Il modo più semplice (senza usare la riga di comando):

1. Nella pagina del repository appena creato, clicca **"uploading an existing file"**
2. Trascina tutti i file della cartella `telegram-art-bot`:
   - `bot.py`
   - `database.json`
   - `requirements.txt`
   - `Procfile`
   - `railway.json`
   - `.gitignore`
3. Clicca **Commit changes**

---

## STEP 6 — Deploy su Railway

1. Vai su [railway.com](https://railway.com)
2. Accedi con il tuo account **GitHub**
3. Clicca **New Project → Deploy from GitHub repo**
4. Seleziona il repository `art-agent-bot`
5. Railway inizierà automaticamente il build

### Configurare le variabili d'ambiente
Questo è il passaggio più importante:

1. Nel progetto Railway, clicca sul servizio appena creato
2. Vai nella tab **Variables**
3. Aggiungi queste variabili (clicca **New Variable** per ciascuna):

| Nome variabile     | Valore                                         |
|--------------------|------------------------------------------------|
| `TELEGRAM_TOKEN`   | Il token del bot da BotFather                  |
| `ANTHROPIC_API_KEY`| La chiave API da Anthropic                     |
| `MY_TELEGRAM_ID`   | Il tuo ID numerico da @userinfobot             |
| `GITHUB_TOKEN`     | Il token GitHub che hai creato allo step 4     |
| `GITHUB_REPO`      | `tuousername/art-agent-bot` (il tuo repo)      |

`GITHUB_TOKEN` e `GITHUB_REPO` sono opzionali ma fortemente consigliati: senza di essi il backup automatico su GitHub non funziona e i dati vivono solo nel volume Railway.

4. **NON fare ancora il deploy** — prima devi aggiungere il Volume (step successivo)

---

## STEP 7 — Aggiungere il Volume Persistente (FONDAMENTALE)

Questo è il passaggio che rende il database permanente. Senza volume, i dati si perdono ad ogni redeploy.

1. Nel tuo progetto Railway, clicca sul servizio del bot
2. Vai nella tab **Volumes** (oppure **Settings → Volumes**)
3. Clicca **+ Add Volume**
4. Configura il volume:
   - **Mount Path**: `/data`
   - **Size**: 1 GB (più che sufficiente — un database JSON artistico pesa pochi KB)
5. Clicca **Add** (o **Create**)
6. Railway farà automaticamente il redeploy

### Come funziona il sistema di backup doppio

Il bot ora salva i tuoi dati in **due posti**:

1. **Volume Railway** (`/data/database.json`) — il database "live", aggiornato in tempo reale ad ogni messaggio
2. **GitHub** (`database.json` nel tuo repo) — backup automatico ad ogni modifica, con commit datato

Se per qualsiasi motivo il volume Railway dovesse avere problemi, il `database.json` su GitHub è sempre aggiornato all'ultima versione. Puoi scaricarlo, e al prossimo avvio il bot lo usa come template.

### Verificare che funziona
1. Nella tab **Deployments**, aspetta che lo stato diventi **Active**
2. Nella tab **Logs**, dovresti vedere:
   ```
   Volume path: /data
   Database path: /data/database.json
   Copio template nel volume...
   Bot in ascolto...
   ```
3. Vai su Telegram e scrivi `/start` al tuo bot
4. Poi dimmi qualcosa di nuovo (es. "Aggiungi che ho partecipato a X") e vai su GitHub: dovresti vedere un commit automatico "auto-backup database [data ora]"

---

## Come Usare il Bot

### Comandi
- `/start` — Messaggio di benvenuto
- `/help` — Guida rapida
- `/db` — Mostra riepilogo del database (quante opere, mostre, ecc.)
- `/export` — Ti manda il file JSON completo su Telegram (per backup o consultazione)
- `/reset` — Cancella la cronologia della conversazione (non tocca il database)
- `/reload` — Forza la ricopia del database template dalla repo al volume (utile dopo aver aggiornato il template su GitHub)

### Aggiornare il Database (esempi)
Scrivi in linguaggio naturale — il bot capisce cosa fare:

- "Aggiungi una mostra personale: 'Corpi Luminosi' alla Galleria Rossi di Milano, 2025, a cura di Marco Bianchi"
- "Aggiorna la mia bio breve con: Artista visivo che lavora con installazioni immersive..."
- "Aggiungi ai temi di ricerca: Ecologia e pratiche artistiche sostenibili"
- "Aggiungi un'opera: 'Respiro', 2025, installazione sonora, dimensioni ambientali"
- "Rimuovi l'opera 'Titolo Opera 3' dal database"
- "Aggiorna il mio Instagram a @nuovohandle"
- "Segna la candidatura a X come inviata"

Ogni modifica viene salvata **immediatamente** sul volume persistente e sincronizzata su GitHub.

### Generare Testi (esempi)
- "Scrivi uno statement artistico di 200 parole per una open call sul tema dell'identità"
- "Prepara una bio di 100 parole per un catalogo di mostra"
- "Scrivi un comunicato stampa per la mia prossima mostra personale alla Galleria X"
- "Riscrivi la mia bio in inglese per una candidatura internazionale"
- "Prepara il testo per una candidatura a una residenza artistica sul tema dell'ecologia"

### Consultare il Profilo (esempi)
- "Quali mostre ho fatto nel 2024?"
- "Elenca tutte le mie opere"
- "Quali sono i miei temi di ricerca?"

---

## Fare Modifiche al Codice con Claude Code

Se vuoi modificare il comportamento del bot (es. aggiungere un comando, cambiare la personalità dell'AI, aggiornare il database a mano), puoi usare **Claude Code**: uno strumento che scrive e modifica il codice al posto tuo e fa il push su GitHub.

### Installare Claude Code

1. Assicurati di avere **Node.js** installato. Per verificarlo, apri il Terminale (su Mac: cerca "Terminale" in Spotlight) e scrivi:
   ```
   node --version
   ```
   Se ti dà un numero (es. `v20.11.0`), ce l'hai già. Altrimenti scaricalo da [nodejs.org](https://nodejs.org).

2. Installa Claude Code scrivendo nel Terminale:
   ```
   npm install -g @anthropic-ai/claude-code
   ```

3. Configura la tua API key Anthropic:
   ```
   claude config set apiKey sk-ant-...
   ```
   (sostituisci con la tua chiave vera)

### Usare Claude Code per modificare il bot

1. Apri il Terminale
2. Clona il tuo repository GitHub (fallo solo la prima volta):
   ```
   git clone https://github.com/tuousername/art-agent-bot.git
   cd art-agent-bot
   ```
3. Avvia Claude Code nella cartella del progetto:
   ```
   claude
   ```
4. Ora puoi scrivere in italiano quello che vuoi cambiare, per esempio:
   - "Aggiungi un comando /stats che mostra quante candidature ho in stato 'inviata'"
   - "Cambia il nome del bot da ArtAgent a MircoBot"
   - "Aggiungi nel database un campo 'agenti' nella sezione profilo"

Claude Code modificherà i file, ti mostrerà cosa ha cambiato, e tu potrai dirgli di fare il push su GitHub con:
- "Fai il commit e pusha su GitHub"

Railway si accorge automaticamente del nuovo commit e rideploya il bot.

### Aggiornare il database a mano con Claude Code

Se vuoi modificare il `database.json` direttamente (es. aggiungere retroattivamente molte mostre):

1. Apri Claude Code nella cartella del progetto
2. Dimmi cosa vuoi modificare nel database, es.:
   - "Aggiungi queste 5 mostre a proj_ADAM nel database.json: ..."
   - "Cambia lo stato della candidatura X a 'accettata'"
3. Claude Code aggiorna il file e fa il push
4. Su Railway, usa `/reload` nel bot per ricaricare il template aggiornato nel volume

---

## Risoluzione Problemi

| Problema | Soluzione |
|----------|-----------|
| Il bot non risponde | Controlla i Logs su Railway per errori |
| "Accesso non autorizzato" | Verifica che `MY_TELEGRAM_ID` sia corretto |
| Errore API Anthropic | Verifica la chiave API e che ci sia credito |
| Il deploy fallisce | Controlla che tutti i file siano stati caricati |
| I dati si perdono al redeploy | Verifica che il Volume sia montato su `/data` |
| Il bot si ferma dopo un po' | Railway Hobby plan ha un limite di ore. Controlla i crediti |
| Il backup su GitHub non parte | Verifica `GITHUB_TOKEN` e `GITHUB_REPO` nelle variabili Railway |
| Ho modificato database.json su GitHub ma il bot non lo vede | Usa `/reload` su Telegram |

---

## Struttura dei File

```
art-agent-bot/
├── bot.py              ← Codice principale del bot
├── database.json       ← Template iniziale + backup sincronizzato automaticamente
├── requirements.txt    ← Dipendenze Python
├── Procfile            ← Istruzioni per Railway
├── railway.json        ← Configurazione Railway
└── .gitignore          ← File da ignorare in Git
```

Sul volume Railway (`/data/`):
```
/data/
├── database.json         ← Database "vivo" (questo è quello che conta)
└── database_backup.json  ← Backup automatico pre-modifica
```

---

## Costi Stimati

- **Railway**: piano Hobby a $5/mese (con $5 di crediti inclusi — il bot usa pochissime risorse, Volume da 1GB incluso nel piano)
- **Anthropic API**: circa $0.003 per messaggio con Claude Sonnet — $5 di credito bastano per ~1.500 messaggi
- **Telegram**: gratuito
- **GitHub**: gratuito (repository privato)

**Totale stimato: ~$5/mese** (e probabilmente meno se l'uso è moderato)
