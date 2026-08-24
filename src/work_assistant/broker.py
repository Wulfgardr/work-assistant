from __future__ import annotations

import json
import hashlib
from multiprocessing.connection import Client, Connection, Listener
import os
from pathlib import Path
import queue
import secrets
import tempfile
import threading
import time
from typing import Any

from work_assistant.config import AppConfig, load_config
from work_assistant.onboarding import onboarding_status
from work_assistant.privacy import PrivacyError, Pseudonymizer
from work_assistant.service import WorkAssistant


class BrokerError(RuntimeError):
    pass


AUTH_ACCEPT_WORKERS = 4
HANDLER_WORKERS = 16
REQUEST_IDLE_TIMEOUT = 1.0
CLIENT_CONNECT_SLOTS = 8
_CLIENT_CONNECT_SEMAPHORE = threading.BoundedSemaphore(CLIENT_CONNECT_SLOTS)


def _project_root(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if any((candidate / marker).exists() for marker in (".git", "AGENTS.md", "pyproject.toml")):
            return candidate
    return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_broker_storage(config: AppConfig) -> None:
    """Fail closed when protected broker data sits inside an agent workspace."""
    if config.privacy.mode == "off" or config.unsafe_allow_workspace_data:
        return
    workspace = _project_root(config.path.parent)
    if workspace is None:
        return
    protected_paths = [config.data_dir]
    if config.privacy.entities_path is not None:
        protected_paths.append(config.privacy.entities_path)
    if any(_is_within(path.resolve(), workspace.resolve()) for path in protected_paths):
        raise BrokerError(
            "protected broker data must be outside the agent workspace; "
            "set unsafe_allow_workspace_data=true only for an explicit unsafe demo"
        )


class SafeBroker:
    """Trusted boundary: raw data enters here and never leaves through dispatch."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.app = WorkAssistant(config)
        self.privacy = Pseudonymizer(config.privacy, config.data_dir)

    def dispatch(self, operation: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        if operation == "accounts":
            return [
                {
                    "name": item.name,
                    "provider": item.provider,
                    "address": (
                        self.privacy.protect_address(item.address)
                        if self.config.privacy.mode != "off"
                        else item.address
                    ),
                }
                for item in self.config.accounts.values()
            ]
        if operation == "onboarding_status":
            result = onboarding_status(self.config)
            if self.config.privacy.mode != "off":
                for account in result["accounts"]:
                    account["address"] = self.privacy.protect_address(str(account["address"]))
            return result
        if operation == "sync":
            return self.app.sync(str(args["account"]))
        if operation == "list":
            rows = self.app.archive.list_messages(args.get("account"), int(args.get("limit", 20)))
            return [self.privacy.protect_summary(row) for row in rows]
        if operation == "get":
            message_id = self.privacy.restore_reference(str(args["message_id"]))
            message = self.app.archive.get_message(str(args["account"]), message_id)
            return self.privacy.protect_message(message) if message else {"error": "message_not_found"}
        if operation == "draft_candidate":
            recipients = self.privacy.restore_addresses([str(value) for value in args.get("to", [])])
            subject = self.privacy.restore_text(str(args.get("subject", "")))
            body = self.privacy.restore_text(str(args.get("body", "")))
            draft_id = self.app.archive.create_draft_candidate(
                str(args["account"]),
                recipients,
                subject,
                body,
                self.privacy.restore_reference(str(args["in_reply_to"]))
                if args.get("in_reply_to")
                else None,
            )
            return {"draft_candidate_id": draft_id, "status": "local_candidate", "sent": False}
        if operation == "local_artifact":
            kind = str(args.get("kind", ""))
            title = self.privacy.restore_text(str(args.get("title", "")))
            body = self.privacy.restore_text(str(args.get("body", "")))
            artifact_id = self.app.archive.create_local_artifact(kind, title, body)
            return {
                "local_artifact_id": artifact_id,
                "kind": kind,
                "status": "stored_locally",
                "clear_content_returned": False,
            }
        if operation == "knowledge":
            view = self.app.archive.build_knowledge_view()
            contacts = []
            for item in view["contacts"]:
                copy = dict(item)
                decision = self.privacy.policy.decide(str(copy["address"]))
                if decision.action == "pseudonymize":
                    copy["address"] = self.privacy.protect_address(str(copy["address"]))
                copy["_privacy_action"] = decision.action
                contacts.append(copy)
            return {**view, "contacts": contacts, "privacy_mode": self.config.privacy.mode}
        if operation == "verify":
            return self.app.archive.verify()
        if operation == "privacy_status":
            return self.privacy.status()
        raise BrokerError("unsupported broker operation")


MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


def _handle_connection(connection: Connection, broker: SafeBroker) -> None:
    try:
        if not connection.poll(REQUEST_IDLE_TIMEOUT):
            return
        raw = connection.recv_bytes(MAX_REQUEST_BYTES)
        try:
            request = json.loads(raw.decode("utf-8"))
            result = broker.dispatch(str(request["operation"]), request.get("arguments"))
            response = {"ok": True, "result": result}
        except (BrokerError, PrivacyError, KeyError, TypeError, ValueError) as exc:
            response = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        except Exception:
            response = {"ok": False, "error": "internal_error", "message": "broker operation failed"}
        encoded = json.dumps(response, ensure_ascii=False).encode()
        if len(encoded) > MAX_RESPONSE_BYTES:
            encoded = json.dumps(
                {"ok": False, "error": "response_too_large", "message": "broker response exceeds the size limit"}
            ).encode()
        connection.send_bytes(encoded)
    finally:
        connection.close()


def _accept_connections(
    listener: Listener,
    accepted: queue.Queue[Connection],
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        try:
            connection = listener.accept()
        except (OSError, EOFError):
            return
        while not stop.is_set():
            try:
                accepted.put(connection, timeout=0.2)
                break
            except queue.Full:
                continue
        else:
            connection.close()


def _handle_connections(
    accepted: queue.Queue[Connection],
    broker: SafeBroker,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        try:
            connection = accepted.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            _handle_connection(connection, broker)
        finally:
            accepted.task_done()


def default_broker_address(config: AppConfig) -> str:
    suffix = hashlib.sha256(str(config.path).encode()).hexdigest()[:16]
    if os.name == "nt":
        return rf"\\.\pipe\work-assistant-{suffix}"
    runtime_root = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    return str(runtime_root / f"work-assistant-{os.getuid()}" / f"{suffix}.sock")


def default_auth_path(config: AppConfig) -> Path:
    return config.data_dir / "secrets" / "broker.auth"


def _load_or_create_auth_key(path: Path) -> bytes:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, secrets.token_hex(32).encode() + b"\n")
        finally:
            os.close(descriptor)
    key = path.read_bytes().strip()
    if len(key) < 32:
        raise BrokerError("broker authentication key is invalid")
    return key


def run_broker(
    config_path: str,
    address: str | None = None,
    auth_file: str | None = None,
) -> None:
    config = load_config(config_path)
    validate_broker_storage(config)
    endpoint = address or default_broker_address(config)
    auth_path = Path(auth_file).expanduser().resolve() if auth_file else default_auth_path(config)
    auth_key = _load_or_create_auth_key(auth_path)
    socket_path = Path(endpoint) if os.name != "nt" else None
    if socket_path is not None:
        parent_existed = socket_path.parent.exists()
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed:
            os.chmod(socket_path.parent, 0o700)
    client = BrokerClient(endpoint, auth_path, timeout=0.2)
    if socket_path is not None and socket_path.exists():
        try:
            client.call("privacy_status")
        except Exception:
            socket_path.unlink()
        else:
            raise BrokerError("a broker is already running on this endpoint")
    family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
    listener = Listener(endpoint, family=family, backlog=HANDLER_WORKERS, authkey=auth_key)
    if socket_path is not None:
        os.chmod(socket_path, 0o600)
    broker = SafeBroker(config)
    stop = threading.Event()
    accepted: queue.Queue[Connection] = queue.Queue(maxsize=HANDLER_WORKERS)
    workers = [
        threading.Thread(
            target=_accept_connections,
            args=(listener, accepted, stop),
            daemon=True,
            name=f"broker-accept-{index}",
        )
        for index in range(AUTH_ACCEPT_WORKERS)
    ]
    workers.extend(
        threading.Thread(
            target=_handle_connections,
            args=(accepted, broker, stop),
            daemon=True,
            name=f"broker-handler-{index}",
        )
        for index in range(HANDLER_WORKERS)
    )
    for worker in workers:
        worker.start()
    try:
        while True:
            stop.wait(60)
    finally:
        stop.set()
        listener.close()
        if socket_path is not None and socket_path.exists():
            socket_path.unlink()


class BrokerClient:
    def __init__(self, address: str | Path, auth_file: str | Path, timeout: float = 30):
        self.address = str(address)
        self.auth_file = Path(auth_file)
        self.timeout = timeout

    def call(self, operation: str, **arguments: Any) -> Any:
        payload = json.dumps({"operation": operation, "arguments": arguments}).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise BrokerError("broker request exceeds the size limit")
        started = time.monotonic()
        if not _CLIENT_CONNECT_SEMAPHORE.acquire(timeout=self.timeout):
            raise BrokerError("privacy broker connection capacity is exhausted")
        result: queue.Queue[Connection | BaseException] = queue.Queue(maxsize=1)
        expired = threading.Event()

        def connect() -> None:
            try:
                family = "AF_PIPE" if self.address.startswith("\\\\.\\pipe\\") else "AF_UNIX"
                connection = Client(
                    self.address,
                    family=family,
                    authkey=self.auth_file.read_bytes().strip(),
                )
                if expired.is_set():
                    connection.close()
                else:
                    result.put(connection)
            except BaseException as exc:
                if not expired.is_set():
                    result.put(exc)
            finally:
                _CLIENT_CONNECT_SEMAPHORE.release()

        threading.Thread(target=connect, daemon=True, name="broker-client-connect").start()
        try:
            connected = result.get(timeout=self.timeout)
        except queue.Empty as exc:
            expired.set()
            raise BrokerError("privacy broker connection timed out") from exc
        if isinstance(connected, BaseException):
            if isinstance(connected, (OSError, EOFError)):
                raise BrokerError("privacy broker is unavailable; no raw fallback was used") from connected
            raise BrokerError("privacy broker authentication failed") from connected
        connection = connected
        try:
            remaining = self.timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise BrokerError("privacy broker request timed out")
            try:
                connection.send_bytes(payload)
                if not connection.poll(remaining):
                    raise BrokerError("privacy broker response timed out")
                raw = connection.recv_bytes(MAX_RESPONSE_BYTES)
            finally:
                connection.close()
        except (OSError, EOFError) as exc:
            raise BrokerError("privacy broker is unavailable; no raw fallback was used") from exc
        response = json.loads(raw.decode("utf-8"))
        if not response.get("ok"):
            raise BrokerError(f"{response.get('error')}: {response.get('message')}")
        return response.get("result")
