from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "workspace", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".md", ".py", ".toml", ".json", ".jsonl", ".yaml", ".yml", ".txt", ".example"}
DENY = {
    "private email domain": re.compile(r"@asst-|@gmail\.com|@icloud\.com", re.IGNORECASE),
    "absolute user path": re.compile(r"/Users/[^/\s]+/|[A-Z]:\\\\Users\\\\", re.IGNORECASE),
    "embedded auth token value": re.compile(
        r"(?:ZM_AUTH_TOKEN|ZX_AUTH_TOKEN)\s*[:=]\s*[\"']?[A-Za-z0-9._-]{32,}",
        re.IGNORECASE,
    ),
    "Italian tax code shape": re.compile(r"\b[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]\b"),
}


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"LICENSE", ".gitignore"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in DENY.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: {label}")
    if findings:
        print("privacy_check=fail")
        print("\n".join(findings))
        return 1
    print("privacy_check=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
