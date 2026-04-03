"""
ArtAgent Bot — Assistente Artistico Personale su Telegram
Usa Claude (Anthropic) come motore AI e un file JSON persistente come database.
Il database viene salvato su un Railway Volume per sopravvivere ai redeploy.
"""

import os
import json
import logging
import re
import shutil
import base64
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

import anthropic
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Configurazione ───────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
MY_TELEGRAM_ID = int(os.environ["MY_TELEGRAM_ID"])
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# ── Percorsi database ────────────────────────────────────────────────────────
# Il volume Railway viene montato su /data.
# Il database "vivo" sta nel volume; il file nella repo è solo il template iniziale.
VOLUME_DIR = Path(os.environ.get("VOLUME_PATH", "/data"))
DATABASE_PATH = VOLUME_DIR / "database.json"
BACKUP_PATH = VOLUME_DIR / "database_backup.json"
TEMPLATE_PATH = Path("database.json")  # template nella repo

# ── GitHub sync (opzionale) ───────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")   # formato: "username/repo"
GITHUB_DB_PATH = os.environ.get("GITHUB_DB_PATH", "database.json")  # percorso nel repo

# ── Client Anthropic ─────────────────────────────────────────────────────────
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Helpers database ─────────────────────────────────────────────────────────

def _empty_database() -> dict:
    return {
        "profilo": {
            "nome": "",
            "nome_arte": "",
            "citta": "",
            "discipline": "",
            "sito_web": "",
            "email": "",
            "instagram": "",
        },
        "biografia": {
            "statement": "",
            "bio": "",
            "identita_artistica": "",
        },
        "cv_artistico": {
            "formazione": [],
            "mostre": [],
            "residenze": [],
            "premi_e_riconoscimenti": [],
            "grants": [],
        },
        "opere": [],
        "temi_ricerca": [],
        "lavori": [],
        "candidature": [],
    }


def init_database() -> None:
    """
    Inizializza il database sul volume persistente.
    - Se il volume ha già un database → lo usa (dati preservati tra i deploy).
    - Se il volume è vuoto ma la repo ha un template → lo copia nel volume.
    - Se non esiste nulla → crea un database vuoto.
    """
    VOLUME_DIR.mkdir(parents=True, exist_ok=True)

    if DATABASE_PATH.exists():
        logger.info("Database trovato sul volume: %s", DATABASE_PATH)
        return

    if TEMPLATE_PATH.exists():
        logger.info("Copio template nel volume: %s → %s", TEMPLATE_PATH, DATABASE_PATH)
        shutil.copy2(TEMPLATE_PATH, DATABASE_PATH)
        return

    logger.info("Nessun database trovato, creo database vuoto su volume.")
    save_database(_empty_database())


def load_database() -> dict:
    """Carica il database JSON dal volume persistente."""
    try:
        with open(DATABASE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Errore caricamento database: %s — ricreo vuoto.", e)
        empty = _empty_database()
        save_database(empty)
        return empty


def _push_to_github(data: dict) -> bool:
    """
    Fa il push del database.json aggiornato su GitHub via API REST.
    Richiede GITHUB_TOKEN e GITHUB_REPO nelle variabili d'ambiente.
    Non blocca se fallisce — logga solo un warning.

    Il backup viene scritto sul branch 'data' (non 'main') per evitare
    che Railway triggeri un redeploy ad ogni aggiornamento del database.
    """
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False

    # Branch dedicato ai backup del database: Railway non lo osserva
    # e non scatta nessun redeploy.
    BACKUP_BRANCH = os.environ.get("GITHUB_DATA_BRANCH", "data")

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "ArtAgent-Bot",
    }

    base = f"https://api.github.com/repos/{GITHUB_REPO}"

    # 1. Assicurati che il branch 'data' esista; se non c'è, crealo da 'main'
    try:
        req = urllib.request.Request(
            f"{base}/git/refs/heads/{BACKUP_BRANCH}", headers=headers
        )
        with urllib.request.urlopen(req, timeout=10):
            pass  # branch già esistente
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Recupera lo SHA dell'ultimo commit su main per creare il branch
            try:
                req = urllib.request.Request(
                    f"{base}/git/refs/heads/main", headers=headers
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    main_sha = json.loads(resp.read())["object"]["sha"]
                payload = {"ref": f"refs/heads/{BACKUP_BRANCH}", "sha": main_sha}
                req = urllib.request.Request(
                    f"{base}/git/refs",
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10):
                    logger.info("Branch '%s' creato su GitHub.", BACKUP_BRANCH)
            except Exception as ex:
                logger.warning("Impossibile creare branch '%s': %s", BACKUP_BRANCH, ex)
                return False
        else:
            logger.warning("GitHub branch check fallito (%s): %s", e.code, e.reason)
            return False
    except Exception as e:
        logger.warning("GitHub branch check errore: %s", e)
        return False

    # 2. Recupera lo SHA attuale del file sul branch 'data' (necessario per aggiornarlo)
    api_url = f"{base}/contents/{GITHUB_DB_PATH}?ref={BACKUP_BRANCH}"
    sha = ""
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            sha = json.loads(resp.read()).get("sha", "")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            logger.warning("GitHub GET fallito (%s): %s", e.code, e.reason)
            return False
    except Exception as e:
        logger.warning("GitHub GET errore: %s", e)
        return False

    # 3. Scrivi il file sul branch 'data'
    content_b64 = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {
        "message": f"auto-backup database {timestamp}",
        "content": content_b64,
        "branch": BACKUP_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        req = urllib.request.Request(
            f"{base}/contents/{GITHUB_DB_PATH}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            logger.info("Database pushato su GitHub branch '%s' (HTTP %s).", BACKUP_BRANCH, status)
            return status in (200, 201)
    except Exception as e:
        logger.warning("GitHub PUT fallito: %s", e)
        return False


def save_database(data: dict) -> None:
    """
    Salva il database JSON sul volume persistente.
    Prima crea un backup del file precedente per sicurezza.
    Se GITHUB_TOKEN e GITHUB_REPO sono configurati, fa il push su GitHub.
    """
    VOLUME_DIR.mkdir(parents=True, exist_ok=True)

    # Backup automatico prima di sovrascrivere
    if DATABASE_PATH.exists():
        try:
            shutil.copy2(DATABASE_PATH, BACKUP_PATH)
        except Exception as e:
            logger.warning("Backup fallito: %s", e)

    # Scrivi su file temporaneo poi rinomina (scrittura atomica)
    tmp_path = DATABASE_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(DATABASE_PATH)

    logger.info("Database salvato su volume: %s", DATABASE_PATH)

    # Sync su GitHub in background (non blocca, non crasha se fallisce)
    try:
        _push_to_github(data)
    except Exception as e:
        logger.warning("Sync GitHub non riuscito: %s", e)


def database_summary(db: dict) -> str:
    """Restituisce una rappresentazione testuale compatta del database."""
    return json.dumps(db, ensure_ascii=False, indent=2)


# ── Prompt di sistema ────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
Sei ArtAgent, l'assistente personale di Mirco Tiozzo (nome d'arte: Mirqotio).

Non sei un assistente generico: sei qualcuno che conosce Mirco profondamente, \
lo ascolta nel tempo e lo aiuta a vedersi con più chiarezza come artista \
e come persona.

═══ CHI È MIRCO ═══
Mirco Tiozzo è un artista e creative technologist basato a Milano. \
New media artist, AI artist, sperimentatore di nuove forme di comunicazione. \
Crede nella tecnologia come forza empowering e democratica — con stupore \
costante, mai presunzione. Vulnerabile, determinato, curioso. L'arte connette, \
non spiega. Il dubbio non è debolezza. Non c'è differenza tra arte personale \
e lavoro per clienti: tutto è espressione.

═══ COME SCRIVI ═══
Letture di vissuto, non liste di fatti. Tecnologia come scelta artistica \
consapevole. Calore umano, non freddezza tecnica. Italiano sempre, \
a meno che Mirco non chieda diversamente.

═══ COSA FAI ═══

1. **Conosci Mirco**: hai accesso al suo database completo (profilo, bio, \
CV, opere, mostre, temi di ricerca, note). Usalo per rispondere come qualcuno \
che lo conosce davvero — non come un motore di ricerca.

2. **Aggiorni il database**: quando Mirco ti dice qualcosa di nuovo su di sé, \
il suo lavoro, una mostra, un'opera, un contatto — tu lo salvi. \
Rispondi con un blocco JSON di istruzioni racchiuso tra i tag \
<db_update> e </db_update>:
<db_update>
{{
  "action": "add" | "update" | "remove",
  "section": "nome_sezione",
  "data": {{ ... }}
}}
</db_update>
Puoi usare più blocchi nella stessa risposta se servono più modifiche.

Sezioni valide: profilo, biografia, cv_artistico, opere, temi_ricerca, lavori, candidature.

Per "add" ad una lista (es. opere, mostre, temi_ricerca, lavori, candidature), \
"data" è l'elemento da aggiungere.
Per "add" ad una sottosezione lista dentro un dizionario (es. cv_artistico.mostre), \
"data" deve includere "sottosezione": "mostre" più i campi dell'elemento.
Per "update" su un campo di una sezione dizionario (es. biografia.statement), "data" contiene \
il percorso e il nuovo valore: {{"campo": "statement", "valore": "nuovo testo"}}.
Per "update" di un elemento dentro una lista (es. opere, lavori, candidature), \
"data" deve contenere "match" (criterio per trovare l'elemento) e "updates" \
(campi da aggiornare): {{"match": {{"titolo": "Nome opera"}}, "updates": {{"stato": "inviata"}}}}.
Per "remove" da una lista, "data" contiene un criterio di ricerca: \
{{"titolo": "Opera da rimuovere"}}.

3. **Scrivi testi professionali**: statement artistici, bio per cataloghi, \
candidature a open call, comunicati stampa, lettere motivazionali. \
Attingi sempre dai dati reali di Mirco — scrivi come se lo conoscessi, \
perché lo conosci.

4. **Salva proattivamente**: se Mirco ti racconta qualcosa di rilevante \
(una nuova mostra, un progetto, un cambiamento) e non ti dice esplicitamente \
"salva", salvalo comunque. Sei il suo archivio vivente.

5. **Candidature e open call**: la sezione "candidature" serve per tracciare \
le candidature in corso. Ogni candidatura ha: titolo, ente, scadenza, stato \
(in preparazione / inviata / accettata / rifiutata), e note. Quando Mirco \
ti dice "ho mandato la candidatura a X" oppure "devo candidarmi a Y entro Z", \
salva nella sezione candidature.

6. **Opere vs Lavori**: "opere" sono i progetti artistici personali \
(proj_ADAM, Simbolica-mente, ecc.). "lavori" sono le commissions e i \
progetti commerciali (projection mapping, live visuals per clienti, ecc.). \
Quando scrivi per open call o festival, usa le opere. \
Quando prepari un portfolio commerciale o rispondi a un brand, usa i lavori. \
Se Mirco ti racconta un nuovo progetto, chiedi se è un'opera o un lavoro \
— oppure deducilo dal contesto (se c'è un cliente, è un lavoro).

7. **Links e risorse**: le opere, i lavori e il profilo hanno campi "links" per \
cartelle Google Drive, video, foto, documentazione. Quando Mirco ti chiede \
"mandami il link delle foto di proj_ADAM", cerca nel campo links dell'opera \
corrispondente. Se il link non c'è ancora, diglielo e chiedi se vuole aggiungerlo.

═══ DATABASE DI MIRCO ═══
{database}
═══ FINE DATABASE ═══
"""


# ── Logica di aggiornamento database ────────────────────────────────────────

def apply_db_updates(response_text: str, db: dict) -> list[str]:
    """
    Cerca blocchi <db_update>...</db_update> nella risposta di Claude,
    applica le modifiche al database e restituisce un log delle operazioni.
    """
    pattern = re.compile(r"<db_update>\s*(\{.*?\})\s*</db_update>", re.DOTALL)
    matches = pattern.findall(response_text)
    logs: list[str] = []

    for raw in matches:
        try:
            instruction = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Impossibile decodificare istruzione DB: %s", raw)
            logs.append("⚠️ Errore nel parsing di un aggiornamento.")
            continue

        action = instruction.get("action", "")
        section = instruction.get("section", "")
        data = instruction.get("data", {})

        try:
            if action == "add":
                logs.append(_handle_add(db, section, data))
            elif action == "update":
                logs.append(_handle_update(db, section, data))
            elif action == "remove":
                logs.append(_handle_remove(db, section, data))
            else:
                logs.append(f"⚠️ Azione sconosciuta: {action}")
        except Exception as e:
            logger.exception("Errore applicando aggiornamento DB")
            logs.append(f"⚠️ Errore: {e}")

    if logs:
        save_database(db)

    return logs


def _handle_add(db: dict, section: str, data) -> str:
    target = db.get(section)
    if isinstance(target, list):
        if isinstance(data, dict):
            data.setdefault("data_inserimento", datetime.now().strftime("%Y-%m-%d"))
        target.append(data)
        return f"✅ Aggiunto elemento a '{section}'."
    elif isinstance(target, dict):
        # Per sottosezioni che sono liste (es. cv_artistico.mostre_personali)
        sub = data.get("sottosezione") or data.get("campo")
        if sub and sub in target and isinstance(target[sub], list):
            entry = {k: v for k, v in data.items() if k not in ("sottosezione", "campo")}
            entry.setdefault("data_inserimento", datetime.now().strftime("%Y-%m-%d"))
            target[sub].append(entry)
            return f"✅ Aggiunto elemento a '{section}.{sub}'."
        else:
            target.update(data)
            return f"✅ Aggiornato '{section}' con nuovi campi."
    else:
        return f"⚠️ Sezione '{section}' non trovata."


def _handle_update(db: dict, section: str, data) -> str:
    target = db.get(section)
    if target is None:
        return f"⚠️ Sezione '{section}' non trovata."

    campo = data.get("campo", "")
    valore = data.get("valore", data.get("value", ""))

    if isinstance(target, dict) and campo:
        # Aggiorna un sotto-campo di una sezione dizionario
        # Supporta campi annidati con punto: "sottosezione.campo"
        parts = campo.split(".", 1)
        if len(parts) == 2 and parts[0] in target and isinstance(target[parts[0]], dict):
            target[parts[0]][parts[1]] = valore
            return f"✅ Aggiornato '{section}.{campo}'."
        target[campo] = valore
        return f"✅ Aggiornato '{section}.{campo}'."
    elif isinstance(target, dict):
        target.update(data)
        return f"✅ Aggiornato '{section}'."
    elif isinstance(target, list):
        # Aggiorna un elemento in una lista trovandolo per "match" e applicando "updates"
        match_criteria = data.get("match", {})
        updates = data.get("updates", {})
        if not match_criteria or not updates:
            # Fallback: se non c'è match/updates, prova campo/valore su tutti gli elementi
            if campo:
                updated = 0
                for item in target:
                    if isinstance(item, dict) and _matches(item, match_criteria or data):
                        item[campo] = valore
                        updated += 1
                if updated:
                    return f"✅ Aggiornato {updated} elemento/i in '{section}'."
            return f"⚠️ Non so come aggiornare '{section}' con i dati forniti."
        updated = 0
        for item in target:
            if isinstance(item, dict) and _matches(item, match_criteria):
                item.update(updates)
                updated += 1
        if updated:
            return f"✅ Aggiornato {updated} elemento/i in '{section}'."
        return f"⚠️ Nessun elemento trovato in '{section}' con i criteri specificati."
    else:
        return f"⚠️ Non so come aggiornare '{section}' con i dati forniti."


def _handle_remove(db: dict, section: str, data) -> str:
    target = db.get(section)
    if isinstance(target, list):
        before = len(target)
        db[section] = [
            item for item in target
            if not _matches(item, data)
        ]
        removed = before - len(db[section])
        return f"✅ Rimossi {removed} elementi da '{section}'." if removed else f"⚠️ Nessun elemento trovato in '{section}'."
    elif isinstance(target, dict):
        sub = data.get("sottosezione") or data.get("campo")
        if sub and sub in target and isinstance(target[sub], list):
            criteria = {k: v for k, v in data.items() if k not in ("sottosezione", "campo")}
            before = len(target[sub])
            target[sub] = [item for item in target[sub] if not _matches(item, criteria)]
            removed = before - len(target[sub])
            return f"✅ Rimossi {removed} elementi da '{section}.{sub}'." if removed else f"⚠️ Nessun elemento trovato."
    return f"⚠️ Non so come rimuovere da '{section}'."


def _matches(item, criteria: dict) -> bool:
    """Verifica se un elemento corrisponde ai criteri (match parziale, case-insensitive)."""
    if not isinstance(item, dict):
        return str(item).lower() == str(criteria).lower()
    for key, value in criteria.items():
        if key in item and str(value).lower() in str(item[key]).lower():
            return True
    return False


def strip_db_update_tags(text: str) -> str:
    """Rimuove i blocchi <db_update>...</db_update> dal testo mostrato all'utente."""
    return re.sub(r"<db_update>.*?</db_update>", "", text, flags=re.DOTALL).strip()


# ── Gestione conversazione ──────────────────────────────────────────────────

conversation_history: list[dict] = []
MAX_HISTORY = 30


def build_messages(user_text: str) -> list[dict]:
    """Costruisce la lista di messaggi per la chiamata Claude."""
    conversation_history.append({"role": "user", "content": user_text})
    if len(conversation_history) > MAX_HISTORY:
        del conversation_history[: len(conversation_history) - MAX_HISTORY]
    return list(conversation_history)


def record_assistant(text: str) -> None:
    conversation_history.append({"role": "assistant", "content": text})
    if len(conversation_history) > MAX_HISTORY:
        del conversation_history[: len(conversation_history) - MAX_HISTORY]


# ── Handlers Telegram ────────────────────────────────────────────────────────

def is_authorized(update: Update) -> bool:
    return update.effective_user.id == MY_TELEGRAM_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("⛔ Accesso non autorizzato.")
        return
    await update.message.reply_text(
        "🎨 *Ciao! Sono il tuo assistente artistico.*\n\n"
        "Posso aiutarti con:\n"
        "• Consultare e aggiornare il tuo profilo artistico\n"
        "• Scrivere statement, bio, candidature, comunicati stampa\n"
        "• Rispondere a domande sulla tua pratica artistica\n\n"
        "Scrivimi quello che ti serve!",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "📖 *Comandi disponibili:*\n\n"
        "/start — Messaggio di benvenuto\n"
        "/help — Questa guida\n"
        "/db — Mostra un riepilogo del database\n"
        "/export — Scarica il database come file JSON\n"
        "/reset — Cancella la cronologia della conversazione\n"
        "/reload — Ricarica il database dal template della repo\n\n"
        "*Come usarmi:*\n"
        "Scrivimi in linguaggio naturale. Esempi:\n"
        "• _\"Scrivi una bio di 100 parole per un catalogo\"_\n"
        "• _\"Aggiungi la mostra X alla galleria Y nel 2024\"_\n"
        "• _\"Prepara un testo per una open call su tema Z\"_\n"
        "• _\"Quali sono i miei temi di ricerca?\"_",
        parse_mode="Markdown",
    )


async def db_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    db = load_database()

    n_opere = len(db.get("opere", []))
    cv = db.get("cv_artistico", {})
    n_mostre = len(cv.get("mostre", []))
    n_residenze = len(cv.get("residenze", []))
    n_premi = len(cv.get("premi_e_riconoscimenti", []))
    n_formazione = len(cv.get("formazione", []))
    n_temi = len(db.get("temi_ricerca", []))
    n_lavori = len(db.get("lavori", []))
    n_candidature = len(db.get("candidature", []))
    statement = "✅" if db.get("biografia", {}).get("statement") else "❌"
    bio = "✅" if db.get("biografia", {}).get("bio") else "❌"
    identita = "✅" if db.get("biografia", {}).get("identita_artistica") else "❌"
    nome = db.get("profilo", {}).get("nome_arte", "Artista")

    await update.message.reply_text(
        f"📊 *Database di {nome}*\n\n"
        f"Statement: {statement}\n"
        f"Bio: {bio}\n"
        f"Identità artistica: {identita}\n"
        f"Opere: {n_opere}\n"
        f"Mostre: {n_mostre}\n"
        f"Formazione: {n_formazione}\n"
        f"Residenze: {n_residenze}\n"
        f"Premi: {n_premi}\n"
        f"Temi di ricerca: {n_temi}\n"
        f"Lavori: {n_lavori}\n"
        f"Candidature: {n_candidature}",
        parse_mode="Markdown",
    )


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Invia il database come file JSON su Telegram."""
    if not is_authorized(update):
        return
    if DATABASE_PATH.exists():
        await update.message.reply_document(
            document=open(DATABASE_PATH, "rb"),
            filename=f"database_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            caption="📦 Ecco il tuo database artistico aggiornato.",
        )
    else:
        await update.message.reply_text("⚠️ Database non trovato.")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    conversation_history.clear()
    await update.message.reply_text("🔄 Cronologia conversazione cancellata.")


async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forza la ricopia del database template dalla repo al volume."""
    if not is_authorized(update):
        return
    if TEMPLATE_PATH.exists():
        # Backup del database attuale prima di sovrascrivere
        if DATABASE_PATH.exists():
            shutil.copy2(DATABASE_PATH, BACKUP_PATH)
        shutil.copy2(TEMPLATE_PATH, DATABASE_PATH)
        conversation_history.clear()
        await update.message.reply_text(
            "🔄 Database ricaricato dal template della repo.\n"
            "Il database precedente è stato salvato come backup."
        )
    else:
        await update.message.reply_text("⚠️ Template non trovato nella repo.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce ogni messaggio di testo dell'utente."""
    if not is_authorized(update):
        await update.message.reply_text("⛔ Accesso non autorizzato.")
        return

    user_text = update.message.text
    if not user_text:
        return

    await update.message.chat.send_action("typing")

    db = load_database()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(database=database_summary(db))
    messages = build_messages(user_text)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )

        assistant_text = response.content[0].text

        # Applica aggiornamenti al database (salvati sul volume persistente)
        update_logs = apply_db_updates(assistant_text, db)

        clean_text = strip_db_update_tags(assistant_text)

        if update_logs:
            clean_text += "\n\n" + "\n".join(update_logs)

        record_assistant(assistant_text)

        await send_long_message(update, clean_text)

    except anthropic.APIError as e:
        logger.error("Errore API Anthropic: %s", e)
        await update.message.reply_text(
            f"❌ Errore nella comunicazione con Claude: {e.message}"
        )
    except Exception as e:
        logger.exception("Errore inatteso")
        await update.message.reply_text(f"❌ Errore inatteso: {e}")


async def send_long_message(update: Update, text: str) -> None:
    """Telegram ha un limite di 4096 caratteri per messaggio."""
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await update.message.reply_text(text)
        return

    parts = []
    while text:
        if len(text) <= MAX_LEN:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, MAX_LEN)
        if cut == -1:
            cut = text.rfind(". ", 0, MAX_LEN)
        if cut == -1:
            cut = MAX_LEN
        parts.append(text[: cut + 1])
        text = text[cut + 1 :]

    for part in parts:
        if part.strip():
            await update.message.reply_text(part.strip())


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """Avvia il bot."""
    logger.info("Avvio ArtAgent Bot...")
    logger.info("Volume path: %s", VOLUME_DIR)
    logger.info("Database path: %s", DATABASE_PATH)

    # Inizializza il database sul volume persistente
    init_database()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Comandi
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("db", db_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("reload", reload_command))

    # Messaggi di testo
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Avvia in polling
    logger.info("Bot in ascolto...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
