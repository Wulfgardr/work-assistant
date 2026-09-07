from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from html.parser import HTMLParser
import shutil
import subprocess
from typing import Protocol


class AttachmentNotAvailable(RuntimeError):
    """Raised when an adapter cannot supply attachment bytes."""


class NeedsOcr(RuntimeError):
    """Raised when a document has no usable text layer and needs OCR."""


@dataclass(frozen=True)
class ExtractionResult:
    """Derived, regenerable text view of one attachment.

    Only derived text is ever cached or returned. Source bytes stay with the
    provider and never cross the broker boundary.
    """

    status: str
    text: str = ""
    extractor: str | None = None
    truncated: bool = False
    detail: str | None = None


STATUSES = frozenset(
    {
        "ok",
        "empty",
        "unsupported",
        "needs_ocr",
        "ocr_unavailable",
        "ocr_not_configured",
        "provider_unsupported",
        "message_not_synced",
        "attachment_not_found",
        "too_large",
        "failed",
        "disabled",
    }
)


class Extractor(Protocol):
    """Provider-independent document-to-text capability."""

    name: str

    def supports(self, *, content_type: str, filename: str) -> bool: ...
    def extract(self, data: bytes, *, content_type: str, filename: str) -> str: ...


def is_ocr_extractor(extractor: Extractor) -> bool:
    """Third-party OCR adapters opt into the fallback with `is_ocr = True`."""
    return bool(getattr(extractor, "is_ocr", False))


class PageRenderer(Protocol):
    """Optional local document-page renderer (e.g. PDF to image per page)."""

    name: str

    def supports(self, *, content_type: str, filename: str) -> bool: ...
    def available(self) -> bool: ...
    def render(self, data: bytes, *, max_pages: int) -> list[bytes]: ...


_RENDERERS: list[PageRenderer] = []


def register_renderer(renderer: PageRenderer) -> None:
    _RENDERERS.append(renderer)


def registered_renderers() -> list[PageRenderer]:
    return list(_RENDERERS)


def unregister_renderer(name: str) -> None:
    global _RENDERERS
    _RENDERERS = [item for item in _RENDERERS if item.name != name]


class PdftoppmRenderer:
    """Optional local PDF renderer using the system `pdftoppm` binary.

    No network access and no new Python dependency. Registered only when the
    binary is present on PATH. Rendered pages are processed in memory and the
    temporary input file is removed immediately after rendering.
    """

    name = "pdftoppm"

    def supports(self, *, content_type: str, filename: str) -> bool:
        base = content_type.split(";")[0].strip().lower()
        return base == "application/pdf" or filename.lower().endswith(".pdf")

    def available(self) -> bool:
        return shutil.which("pdftoppm") is not None

    def render(self, data: bytes, *, max_pages: int) -> list[bytes]:
        from pathlib import Path as _Path
        import tempfile as _tempfile

        executable = shutil.which("pdftoppm")
        if executable is None:
            raise AttachmentNotAvailable("pdftoppm is not installed")
        pages = max(1, max_pages)
        with _tempfile.TemporaryDirectory(prefix="work-assistant-render-") as directory:
            source = _Path(directory) / "source.pdf"
            source.write_bytes(data)
            completed = subprocess.run(
                [executable, "-png", "-r", "200", "-f", "1", "-l", str(pages), str(source), str(_Path(directory) / "page")],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=180,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"pdftoppm failed: {completed.stderr.decode()[:200]}")
            return [path.read_bytes() for path in sorted(_Path(directory).glob("page-*.png"))]


_EXTRACTORS: list[Extractor] = []
_DEFAULTS_REGISTERED = False


def register_extractor(extractor: Extractor) -> None:
    _EXTRACTORS.append(extractor)


def registered_extractors() -> list[Extractor]:
    return list(_EXTRACTORS)


def unregister_extractor(name: str) -> None:
    global _EXTRACTORS
    _EXTRACTORS = [item for item in _EXTRACTORS if item.name != name]


def _match(patterns: tuple[str, ...], value: str) -> bool:
    normalized = value.strip().lower()
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


class PlainTextExtractor:
    """Stdlib-only extractor for textual attachments. Always available."""

    name = "builtin-text"
    SUPPORTED_TYPES = (
        "text/*",
        "application/json",
        "application/*+json",
        "application/*+xml",
        "application/javascript",
        "application/csv",
    )
    SUPPORTED_SUFFIXES = (".txt", ".md", ".csv", ".json", ".log", ".eml")
    EXCLUDED_TYPES = {"text/html", "application/xhtml+xml"}
    EXCLUDED_SUFFIXES = (".html", ".htm", ".xhtml")

    def supports(self, *, content_type: str, filename: str) -> bool:
        base = content_type.split(";")[0].strip().lower()
        lowered = filename.lower()
        if base in self.EXCLUDED_TYPES or lowered.endswith(self.EXCLUDED_SUFFIXES):
            return False
        if _match(self.SUPPORTED_TYPES, content_type.split(";")[0].strip()):
            return True
        return lowered.endswith(self.SUPPORTED_SUFFIXES)

    def extract(self, data: bytes, *, content_type: str, filename: str) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, ValueError):
                continue
        raise ValueError("no usable text decoding")


class _HtmlStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class HtmlExtractor:
    """Stdlib-only HTML to text fallback. Always available."""

    name = "builtin-html"

    def supports(self, *, content_type: str, filename: str) -> bool:
        base = content_type.split(";")[0].strip().lower()
        return base in {"text/html", "application/xhtml+xml"} or filename.lower().endswith(
            (".html", ".htm", ".xhtml")
        )

    def extract(self, data: bytes, *, content_type: str, filename: str) -> str:
        text = PlainTextExtractor().extract(data, content_type=content_type, filename=filename)
        stripper = _HtmlStripper()
        stripper.feed(text)
        return "".join(stripper.parts)


class AnyDocExtractor:
    """Optional extractor backed by Firecrawl AnyDoc (`pip install '.[attachments]'`).

    Converts office documents, EPUB, RTF, CSV and text-based PDFs to Markdown
    locally. Image-only documents raise a needs-OCR signal instead of failing.
    """

    name = "anydoc"
    SUPPORTED_TYPES = (
        "application/pdf",
        "application/msword",
        "application/vnd.*",
        "application/rtf",
        "application/epub+zip",
        "text/csv",
        "application/csv",
    )
    SUPPORTED_SUFFIXES = (
        ".pdf",
        ".doc",
        ".docx",
        ".docm",
        ".ppt",
        ".pps",
        ".pot",
        ".pptx",
        ".pptm",
        ".ppsx",
        ".ppsm",
        ".xls",
        ".xlsx",
        ".xlsm",
        ".xlsb",
        ".odt",
        ".ods",
        ".odp",
        ".rtf",
        ".epub",
        ".csv",
    )

    def supports(self, *, content_type: str, filename: str) -> bool:
        if _match(self.SUPPORTED_TYPES, content_type.split(";")[0].strip()):
            return True
        return filename.lower().endswith(self.SUPPORTED_SUFFIXES)

    def extract(self, data: bytes, *, content_type: str, filename: str) -> str:
        try:
            import anydoc
        except ImportError as exc:
            raise AttachmentNotAvailable("anydoc is not installed") from exc
        hint = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        try:
            if hint:
                try:
                    return str(anydoc.to_markdown_bytes(data, hint))
                except Exception:
                    pass
            return str(anydoc.to_markdown_bytes(data))
        except Exception as exc:
            message = str(exc).lower()
            if "image" in message or "scanned" in message or "unsupported" in message:
                raise NeedsOcr(str(exc)) from exc
            raise


@dataclass
class OcrConfig:
    mode: str = "auto"
    languages: str = "auto"


class TesseractOcrExtractor:
    """Optional local OCR fallback using the system `tesseract` binary.

    No network access and no new Python dependency: `tesseract` reads image
    bytes from stdin and writes recognized text to stdout. Registered only
    when the binary is present on PATH.
    """

    name = "tesseract-ocr"
    is_ocr = True
    SUPPORTED_TYPES = ("image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp")
    SUPPORTED_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")

    def __init__(self, languages: str = "auto") -> None:
        self.languages = self._resolve_languages(languages)

    @staticmethod
    def tesseract_available() -> bool:
        return shutil.which("tesseract") is not None

    @staticmethod
    def installed_languages() -> list[str]:
        executable = shutil.which("tesseract")
        if executable is None:
            return []
        completed = subprocess.run(
            [executable, "--list-langs"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            return []
        lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
        return [line.strip() for line in lines[1:] if line.strip()]

    @classmethod
    def _resolve_languages(cls, requested: str) -> str:
        if requested != "auto":
            return requested
        installed = cls.installed_languages()
        if "ita" in installed and "eng" in installed:
            return "ita+eng"
        if "eng" in installed:
            return "eng"
        return installed[0] if installed else "eng"

    def supports(self, *, content_type: str, filename: str) -> bool:
        if not self.tesseract_available():
            return False
        if _match(self.SUPPORTED_TYPES, content_type.split(";")[0].strip()):
            return True
        return filename.lower().endswith(self.SUPPORTED_SUFFIXES)

    def extract(self, data: bytes, *, content_type: str, filename: str) -> str:
        executable = shutil.which("tesseract")
        if executable is None:
            raise AttachmentNotAvailable("tesseract is not installed")
        completed = subprocess.run(
            [executable, "stdin", "stdout", "-l", self.languages],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"tesseract failed: {completed.stderr.decode()[:200]}")
        return completed.stdout.decode("utf-8", errors="replace")


def ensure_default_extractors(ocr: OcrConfig | None = None) -> None:
    """Register bundled and optional extractors exactly once (idempotent)."""
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    _DEFAULTS_REGISTERED = True
    register_extractor(PlainTextExtractor())
    register_extractor(HtmlExtractor())
    try:
        import anydoc  # noqa: F401

        register_extractor(AnyDocExtractor())
    except ImportError:
        pass
    config = ocr or OcrConfig()
    if config.mode != "off" and TesseractOcrExtractor.tesseract_available():
        register_extractor(TesseractOcrExtractor(config.languages))
    renderer = PdftoppmRenderer()
    if config.mode != "off" and renderer.available():
        register_renderer(renderer)


def reset_extractors_for_tests() -> None:
    global _EXTRACTORS, _RENDERERS, _DEFAULTS_REGISTERED
    _EXTRACTORS = []
    _RENDERERS = []
    _DEFAULTS_REGISTERED = False


@dataclass
class PipelineLimits:
    max_bytes: int = 32 * 1024 * 1024
    max_chars: int = 20000
    max_pages: int = 10


def _ocr_extractors() -> list[Extractor]:
    return [item for item in _EXTRACTORS if is_ocr_extractor(item)]


def _truncate(result: ExtractionResult, max_chars: int) -> ExtractionResult:
    if result.status != "ok" or len(result.text) <= max_chars:
        return result
    return ExtractionResult(
        status=result.status,
        text=result.text[:max_chars],
        extractor=result.extractor,
        truncated=True,
        detail=result.detail,
    )


def _render_and_ocr(
    data: bytes, *, filename: str, content_type: str, max_pages: int
) -> ExtractionResult | None:
    """Render document pages locally and OCR them. Returns None when unavailable."""
    renderer = next(
        (
            item
            for item in _RENDERERS
            if item.available() and item.supports(content_type=content_type, filename=filename)
        ),
        None,
    )
    ocr = next(
        (
            item
            for item in _ocr_extractors()
            if item.supports(content_type="image/png", filename="page.png")
        ),
        None,
    )
    if renderer is None or ocr is None:
        return None
    try:
        pages = renderer.render(data, max_pages=max(1, max_pages))[: max(1, max_pages)]
    except Exception as exc:
        return ExtractionResult(status="failed", extractor=renderer.name, detail=str(exc)[:300])
    if not pages:
        return ExtractionResult(status="empty", extractor=renderer.name)
    transcripts: list[str] = []
    for index, page in enumerate(pages):
        try:
            transcripts.append(
                ocr.extract(page, content_type="image/png", filename=f"page-{index + 1}.png").strip()
            )
        except Exception as exc:
            return ExtractionResult(status="failed", extractor=ocr.name, detail=str(exc)[:300])
    joined = "\n\n".join(
        f"[page {index + 1}]\n{text}" for index, text in enumerate(transcripts)
    ).strip()
    if not joined:
        return ExtractionResult(status="empty", extractor=f"{renderer.name}+{ocr.name}")
    return ExtractionResult(
        status="ok",
        text=joined,
        extractor=f"{renderer.name}+{ocr.name}",
        detail=f"{len(pages)} page(s) rendered locally and transcribed",
    )


def extract_attachment_text(
    data: bytes,
    *,
    filename: str,
    content_type: str,
    limits: PipelineLimits | None = None,
    ocr_mode: str = "auto",
) -> ExtractionResult:
    """Extract derived text from attachment bytes without network access."""
    resolved = limits or PipelineLimits()
    if len(data) > resolved.max_bytes:
        return ExtractionResult(
            status="too_large",
            detail=f"attachment exceeds the {resolved.max_bytes} byte local limit",
        )
    if not data:
        return ExtractionResult(status="empty")
    normalized_type = (content_type or "application/octet-stream").split(";")[0].strip()
    ocr_candidates = [
        item
        for item in _ocr_extractors()
        if ocr_mode != "off" and item.supports(content_type=normalized_type, filename=filename)
    ]
    candidates = [item for item in _EXTRACTORS if not is_ocr_extractor(item)]
    candidates.extend(ocr_candidates)
    needed_ocr = False
    for extractor in candidates:
        if not extractor.supports(content_type=normalized_type, filename=filename):
            continue
        try:
            text = extractor.extract(data, content_type=normalized_type, filename=filename)
        except NeedsOcr:
            needed_ocr = True
            continue
        except AttachmentNotAvailable as exc:
            return ExtractionResult(status="unsupported", extractor=extractor.name, detail=str(exc))
        except Exception as exc:
            return ExtractionResult(status="failed", extractor=extractor.name, detail=str(exc)[:300])
        cleaned = text.strip()
        if not cleaned:
            return ExtractionResult(status="empty", extractor=extractor.name)
        truncated = len(cleaned) > resolved.max_chars
        return ExtractionResult(
            status="ok",
            text=cleaned[: resolved.max_chars],
            extractor=extractor.name,
            truncated=truncated,
        )
    if ocr_mode != "off":
        chained = _render_and_ocr(
            data,
            filename=filename,
            content_type=normalized_type,
            max_pages=resolved.max_pages,
        )
        if chained is not None:
            return _truncate(chained, resolved.max_chars)
        if needed_ocr and _ocr_extractors():
            return ExtractionResult(
                status="needs_ocr",
                detail="no text layer; no local renderer/OCR pair covers this document",
            )
    if needed_ocr:
        return ExtractionResult(
            status="ocr_unavailable",
            detail="no text layer and no local OCR extractor is available",
        )
    if ocr_mode == "off":
        return ExtractionResult(
            status="ocr_not_configured", detail="OCR is disabled by configuration"
        )
    return ExtractionResult(
        status="unsupported", detail="no registered extractor supports this attachment"
    )


def describe_capabilities() -> dict[str, object]:
    extractors: list[dict[str, object]] = []
    for extractor in _EXTRACTORS:
        info: dict[str, object] = {"name": extractor.name}
        if extractor.name == "tesseract-ocr":
            info["backend"] = "system tesseract binary"
            info["languages"] = getattr(extractor, "languages", "eng")
        if extractor.name == "anydoc":
            try:
                import anydoc

                info["backend"] = str(getattr(anydoc, "__version__", "installed"))
            except ImportError:
                info["backend"] = "not installed"
        extractors.append(info)
    ocr_names = [item.name for item in _EXTRACTORS if is_ocr_extractor(item)]
    renderers = [
        {"name": item.name, "available": item.available()} for item in _RENDERERS
    ]
    pdf_renderer_ready = any(
        item.available()
        and item.supports(content_type="application/pdf", filename="scan.pdf")
        for item in _RENDERERS
    )
    return {
        "extractors": extractors,
        "ocr_available": bool(ocr_names),
        "ocr_extractors": ocr_names,
        "renderers": renderers,
        "pdf_ocr_available": pdf_renderer_ready and bool(ocr_names),
        "notes": [
            "only derived text is cached and returned; source bytes never cross the broker",
            "image-only documents without a text layer need the local OCR fallback",
            "hosted OCR services are out of scope: they would disclose content to a third party",
        ],
    }
