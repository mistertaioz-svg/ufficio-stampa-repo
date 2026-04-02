"""
ArtAgent Bot — Assistente Artistico Personale su Telegram
Usa Claude (Anthropic) come motore AI e un file JSON locale come database.
"""

import os
import json
import logging
import re
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
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "database.json"))
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# ── Client Anthropic ─────────────────────────────────────────────────────────
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Helpers database ─────────────────────────────────────────────────────────

def load_database() -> dict:
    """Carica il database JSON dal disco."""
    if DATABASE_PATH.exists():
        with open(DATABASE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    logger.warning("Database non trovato, ne creo uno vuoto.")
    empty = _empty_database()
    save_database(empty)
    return empty


def save_database(data: dict) -> None:
    """Salva il database JSON su disco."""
    with open(DATABASE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Database salvato.")


def _empty_database() -> dict:
    return {
        "biografia": {"breve": "", "estesa": ""},
        "cv_artistico": {
            "mostre_personali": [],
            "mostre_collettive": [],
            "residenze": [],
            "premi_e_riconoscimenti": [],
            "pubblicazioni": [],
            "formazione": [],
        },
        "opere": [],
        "temi_ricerca": [],
        "contatti": {
            "email": "",
            "sito_web": "",
            "instagram": "",
            "altri_social": {},
            "studio": "",
        },
        "note_generali": [],
    }


def database_summary(db: dict) -> str:
    """Restituisce una rappresentazione testuale compatta del database."""
    return json.dumps(db, ensure_ascii=False, indent=2)


# ── Prompt di sistema ────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
Sei l'assistente personale AI di un artista. Il tuo ruolo è:

1. **Conoscere profondamente l'artista**: hai accesso al suo database completo \
(biografia, CV, opere, temi di ricerca, contatti e note). Usalo per rispondere \
in modo informato e personalizzato.

2. **Aggiornare il database**: quando l'artista ti chiede di aggiungere, \
modificare o rimuovere informazioni, rispondi con un blocco JSON di istruzioni \
racchiuso tra i tag <db_update> e </db_update>. Il formato è:
<db_update>
{{
  "action": "add" | "update" | "remove",
  "section": "nome_sezione",
  "data": {{ ... }}
}}
</db_update>
Puoi usare più blocchi <db_update>...</db_update> nella stessa risposta se \
servono più modifiche.

Sezioni valide: biografia, cv_artistico, opere, temi_ricerca, contatti, \
note_generali.

Per "add" ad una lista (es. opere, mostre, temi_ricerca, note_generali), \
"data" è l'elemento da aggiungere.
Per "update" su un campo semplice (es. biografia.breve), "data" contiene \
il percorso e il nuovo valore, es: {{"campo": "breve", "valore": "nuovo testo"}}.
Per "remove" da una lista, "data" contiene un criterio di ricerca, \
es: {{"titolo": "Opera da rimuovere"}}.

3. **Scrivere testi professionali**: su richiesta, genera testi come \
statement artistici, bio per cataloghi, candidature a open call, comunicati \
stampa, ecc. Attingi sempre ai dati reali dell'artista.

4. **Lingua**: rispondi sempre in italiano, a meno che non venga \
esplicitamente richiesto diversamente.

5. **Tono**: professionale ma cordiale, come un collaboratore fidato che \
conosce bene il lavoro dell'artista.

── DATABASE DELL'ARTISTA ──
{database}
── FINE DATABASE ──
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
        # Supporto per sottocampi con punto: "breve", "estesa", ecc.
        target[campo] = valore
        return f"✅ Aggiornato '{section}.{campo}'."
    elif isinstance(target, dict):
        target.update(data)
        return f"✅ Aggiornato '{section}'."
    else:
        return f"⚠️ Non so come aggiornare '{section}' con i dati forniti."


def _handle_remove(db: dict, section: str, data) -> str:
    target = db.get(section)
    if isinstance(target, list):
        # Cerca per match parziale delle chiavi
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

# Cronologia messaggi per contesto conversazionale (in memoria)
conversation_history: list[dict] = []
MAX_HISTORY = 30  # Ultimi N messaggi


def build_messages(user_text: str) -> list[dict]:
    """Costruisce la lista di messaggi per la chiamata Claude."""
    conversation_history.append({"role": "user", "content": user_text})
    # Mantieni solo gli ultimi MAX_HISTORY messaggi
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
        "/reset — Cancella la cronologia della conversazione\n\n"
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

    # Conta elementi
    n_opere = len(db.get("opere", []))
    cv = db.get("cv_artistico", {})
    n_mostre = sum(len(cv.get(k, [])) for k in ("mostre_personali", "mostre_collettive"))
    n_residenze = len(cv.get("residenze", []))
    n_premi = len(cv.get("premi_e_riconoscimenti", []))
    n_temi = len(db.get("temi_ricerca", []))
    n_note = len(db.get("note_generali", []))
    bio_breve = "✅" if db.get("biografia", {}).get("breve") else "❌"
    bio_estesa = "✅" if db.get("biografia", {}).get("estesa") else "❌"

    await update.message.reply_text(
        f"📊 *Riepilogo Database*\n\n"
        f"Bio breve: {bio_breve}\n"
        f"Bio estesa: {bio_estesa}\n"
        f"Opere: {n_opere}\n"
        f"Mostre: {n_mostre}\n"
        f"Residenze: {n_residenze}\n"
        f"Premi: {n_premi}\n"
        f"Temi di ricerca: {n_temi}\n"
        f"Note: {n_note}",
        parse_mode="Markdown",
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    conversation_history.clear()
    await update.message.reply_text("🔄 Cronologia conversazione cancellata.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce ogni messaggio di testo dell'utente."""
    if not is_authorized(update):
        await update.message.reply_text("⛔ Accesso non autorizzato.")
        return

    user_text = update.message.text
    if not user_text:
        return

    # Indica che il bot sta "scrivendo"
    await update.message.chat.send_action("typing")

    # Carica database e costruisci il prompt di sistema
    db = load_database()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(database=database_summary(db))

    # Costruisci la conversazione
    messages = build_messages(user_text)

    try:
        # Chiamata a Claude
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )

        assistant_text = response.content[0].text

        # Applica eventuali aggiornamenti al database
        update_logs = apply_db_updates(assistant_text, db)

        # Rimuovi i tag tecnici dal messaggio mostrato all'utente
        clean_text = strip_db_update_tags(assistant_text)

        # Aggiungi log aggiornamenti se presenti
        if update_logs:
            clean_text += "\n\n" + "\n".join(update_logs)

        # Registra la risposta nella cronologia
        record_assistant(assistant_text)

        # Invia risposta (gestisci messaggi lunghi)
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
        # Cerca un punto di taglio naturale
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

    # Assicurati che il database esista
    if not DATABASE_PATH.exists():
        logger.info("Creo database vuoto: %s", DATABASE_PATH)
        save_database(_empty_database())

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Comandi
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("db", db_command))
    app.add_handler(CommandHandler("reset", reset_command))

    # Messaggi di testo
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Avvia in polling
    logger.info("Bot in ascolto...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
