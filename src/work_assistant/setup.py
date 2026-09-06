from __future__ import annotations

import datetime
from pathlib import Path
import shutil

from work_assistant.config import default_data_dir, load_config


class SetupAborted(RuntimeError):
    pass


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise SetupAborted("setup interrotto") from exc
    return answer or (default or "")


def _ask_valid(prompt: str, default: str | None, validate) -> str:
    while True:
        answer = _ask(prompt, default)
        error = validate(answer)
        if error is None:
            return answer
        print(f"  Non valido: {error} Riprova.")


def _choose(prompt: str, options: list[tuple[str, str]], default: str) -> str:
    print(f"{prompt}")
    for index, (value, label) in enumerate(options, 1):
        print(f"  {index}. {label}")
    default_index = str(next(i for i, (value, _label) in enumerate(options, 1) if value == default))

    def validate(answer: str) -> str | None:
        if answer in [str(i) for i in range(1, len(options) + 1)]:
            return None
        if answer in [value for value, _label in options]:
            return None
        return "scegli un numero dall'elenco."

    answer = _ask_valid("Scelta", default_index, validate)
    if answer.isdigit():
        return options[int(answer) - 1][0]
    return answer


def _yes_no(prompt: str, default_yes: bool) -> bool:
    default = "S" if default_yes else "N"
    answer = _ask(f"{prompt} (s/n)", default).lower()
    return answer.startswith("s")


def _non_empty(answer: str) -> str | None:
    return None if answer else "il valore non può essere vuoto."


def _hostname(answer: str) -> str | None:
    cleaned = answer.strip().lower()
    if not cleaned or "/" in cleaned or " " in cleaned or "://" in cleaned:
        return "scrivi solo il nome host, senza https:// né percorsi (es. mail.example.test)."
    return None


def _existing_file(answer: str) -> str | None:
    if not Path(answer).expanduser().is_file():
        return "file non trovato: controlla il percorso."
    return None


def _existing_dir(answer: str) -> str | None:
    if not Path(answer).expanduser().is_dir():
        return "cartella non trovata: controlla il percorso."
    return None


def _account_name(taken: set[str]):
    def validate(answer: str) -> str | None:
        if not answer or any(char in answer for char in " \t\"'[]"):
            return "usa un nome semplice senza spazi (es. personale, lavoro)."
        if answer in taken:
            return f"l'account {answer!r} esiste già."
        return None

    return validate


TYPES = [
    ("demo", "demo — casella sintetica per provare subito, senza credenziali"),
    ("maildir", "maildir — cartella di posta locale già esportata"),
    ("imap", "imap — casella reale via IMAP (serve una password per le app)"),
    ("zimbra", "zimbra — sessione dal browser via file HAR"),
    ("carbonio", "carbonio — sessione dal browser via file HAR"),
    ("graph", "graph — Exchange Online / Microsoft 365 via OAuth"),
]


def _collect_account(taken: set[str]) -> dict[str, object]:
    kind = _choose("Che tipo di casella vuoi collegare?", TYPES, "demo")
    name = _ask_valid("Nome dell'account", "personale" if not taken else f"account-{len(taken) + 1}", _account_name(taken))
    address = _ask_valid("Indirizzo email", "alex@example.test", _non_empty)
    options: dict[str, object] = {}
    if kind == "demo":
        options["source"] = _ask_valid(
            "File JSONL sintetico", "./examples/demo-mailbox.jsonl", _non_empty
        )
    elif kind == "maildir":
        options["path"] = _ask_valid("Cartella Maildir locale", "", _existing_dir)
    elif kind == "imap":
        options["host"] = _ask_valid("Host IMAP", "imap.example.test", _hostname)
        options["username"] = _ask("Utente IMAP", address)
        options["secret_file"] = _ask_valid("File con la password per le app", "", _existing_file)
    elif kind in {"zimbra", "carbonio"}:
        options["host"] = _ask_valid("Host della webmail", "mail.example.test", _hostname)
    elif kind == "graph":
        options["client_id"] = _ask_valid("Client ID dell'app Entra", "", _non_empty)
        options["tenant"] = _ask("Tenant (common, organizations, id o dominio)", "common")
        options["token_file"] = _ask_valid(
            "Dove salvare i token", str(default_data_dir() / f"{name}.graph.token.json"), _non_empty
        )
    return {"name": name, "provider": kind, "address": address, "options": options}


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _key(name: str) -> str:
    if name and all(char.isalnum() or char in "_-" for char in name):
        return name
    return _quote(name)


def render_config(data_dir: Path, mode: str, accounts: list[dict[str, object]]) -> str:
    lines = [
        "schema_version = 1",
        f"data_dir = {_quote(data_dir.as_posix())}",
        "",
        "[privacy]",
        f"mode = {_quote(mode)}",
        'default_action = "pseudonymize"',
    ]
    for account in accounts:
        lines += [
            "",
            f"[accounts.{_key(str(account['name']))}]",
            f"provider = {_quote(str(account['provider']))}",
            f"address = {_quote(str(account['address']))}",
        ]
        options = account["options"]
        assert isinstance(options, dict)
        for key, value in options.items():
            lines.append(f"{_key(key)} = {_quote(str(value))}")
    return "\n".join(lines) + "\n"


PRIVACY_OPTIONS = [
    ("all", "protetta — pseudonimizza tutti i mittenti (consigliata)"),
    ("selective", "selettiva — regole per mittente (per esperti)"),
    ("off", "aperta — nessun filtro; il modello può vedere tutto"),
]


def run_setup(config_path: Path, *, demo: bool = False) -> dict[str, object]:
    print("Work Assistant — configurazione guidata.")
    if demo:
        return _run_demo(config_path)
    print("In tre passi: riservatezza, caselle, prova. Nessun segreto viene mai stampato.")
    print(f"Cartella dati: {default_data_dir()} (fuori dal progetto, al sicuro).")
    mode = _choose("Livello di riservatezza verso gli agenti?", PRIVACY_OPTIONS, "all")
    accounts: list[dict[str, object]] = []
    taken: set[str] = set()
    while True:
        account = _collect_account(taken)
        accounts.append(account)
        taken.add(str(account["name"]))
        if not _yes_no("Aggiungere un'altra casella?", False):
            break
    _write_config(config_path, default_data_dir(), mode, accounts)
    config = load_config(config_path)
    report = _smoke_test(config, accounts)
    _print_next_steps(config_path, accounts, report)
    return {"created": str(config_path), "accounts": [str(a["name"]) for a in accounts], **report}


def _write_config(config_path: Path, data_dir: Path, mode: str, accounts: list[dict[str, object]]) -> None:
    if config_path.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = config_path.with_name(f"{config_path.name}.bak.{stamp}")
        shutil.copy2(config_path, backup)
        print(f"Configurazione esistente salvata in {backup}.")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_config(data_dir, mode, accounts), encoding="utf-8")
    load_config(config_path)
    print(f"Configurazione scritta in {config_path} e verificata.")


def _smoke_test(config, accounts: list[dict[str, object]]) -> dict[str, object]:
    from work_assistant.service import WorkAssistant, available_providers

    available = set(available_providers())
    synced: list[str] = []
    pending: list[dict[str, str]] = []
    for account in accounts:
        name = str(account["name"])
        provider = str(account["provider"])
        if provider not in available:
            pending.append({"account": name, "next": _install_hint(provider)})
            continue
        if provider in {"zimbra", "carbonio"}:
            pending.append(
                {
                    "account": name,
                    "next": (
                        f"esporta il file HAR dal browser, poi esegui: "
                        f"work-assistant --config {config.path} import-zimbra-har "
                        f"--account {name} --har /percorso/locale/session.har"
                    ),
                }
            )
            continue
        if provider == "graph":
            pending.append(
                {
                    "account": name,
                    "next": (
                        "installa l'adapter (python -m pip install ./adapters/graph), poi esegui: "
                        f"work-assistant-graph-login --config {config.path} --account {name}"
                    ),
                }
            )
            continue
        try:
            result = WorkAssistant(config).sync(name)
            synced.append(f"{name} ({result['observed']} messaggi)")
        except Exception as exc:
            pending.append({"account": name, "next": f"controllo fallito: {exc}"})
    verify: dict[str, object] = {}
    if synced:
        verify = dict(WorkAssistant(config).archive.verify())
    print(f"Sincronizzati: {', '.join(synced) if synced else 'nessuno'}.")
    return {"synced": synced, "pending": pending, "verify": verify}


def _install_hint(provider: str) -> str:
    if provider in {"zimbra", "carbonio"}:
        return "installa un adapter compatibile (vedi docs/PROVIDER_ADAPTERS.md)"
    if provider == "graph":
        return "installa l'adapter con: python -m pip install ./adapters/graph"
    return f"adapter {provider!r} non disponibile"


def _print_next_steps(config_path: Path, accounts: list[dict[str, object]], report: dict[str, object]) -> None:
    for item in report.get("pending", []):
        assert isinstance(item, dict)
        print(f"  → {item['account']}: {item['next']}")
    print("Comandi utili:")
    print(f"  work-assistant --config {config_path} doctor")
    print(f"  work-assistant --config {config_path} mcp-setup --client codex")


def _run_demo(config_path: Path) -> dict[str, object]:
    from work_assistant.service import WorkAssistant

    accounts: list[dict[str, object]] = [
        {
            "name": "personal",
            "provider": "demo",
            "address": "alex@example.test",
            "options": {"source": "./examples/demo-mailbox.jsonl"},
        }
    ]
    _write_config(config_path, default_data_dir(), "all", accounts)
    config = load_config(config_path)
    app = WorkAssistant(config)
    try:
        result = app.sync("personal")
    except Exception as exc:
        print(f"Demo non avviata: {exc}")
        print("Esegui setup dalla cartella del progetto oppure indica una fonte esistente con: setup")
        return {"created": str(config_path), "synced": [], "pending": [str(exc)]}
    verify = app.archive.verify()
    print(f"Demo pronta: {result['observed']} messaggi sintetici, archivio {verify['sqlite']}.")
    print(f"Prova: work-assistant --config {config_path} list")
    return {"created": str(config_path), "synced": ["personal"], "verify": dict(verify)}
