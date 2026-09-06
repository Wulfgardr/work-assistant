from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "work-assistant"
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _load_yaml():
    try:
        import yaml
    except ImportError:
        return None
    return yaml


def _failures() -> list[str]:
    problems: list[str] = []
    skill_file = SKILL / "SKILL.md"
    if not skill_file.is_file():
        return ["skills/work-assistant/SKILL.md is missing"]
    text = skill_file.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if match is None:
        problems.append("SKILL.md requires YAML frontmatter between --- markers")
        return problems
    yaml = _load_yaml()
    if yaml is None:
        problems.append("pyyaml is required to validate skill metadata (pip install '.[dev]')")
        return problems
    frontmatter = yaml.safe_load(match.group(1)) or {}
    for key in ("name", "description"):
        if not str(frontmatter.get(key) or "").strip():
            problems.append(f"SKILL.md frontmatter requires a non-empty {key!r}")
    references = [SKILL / "references" / "onboarding.md", SKILL / "references" / "privacy.md"]
    for reference in references:
        if not reference.is_file():
            problems.append(f"{reference.relative_to(ROOT)} is missing")
    checked = {skill_file, *references}
    for document in checked:
        if not document.is_file():
            continue
        body = FRONTMATTER_RE.sub("", document.read_text(encoding="utf-8"), count=1)
        for target in LINK_RE.findall(body):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            candidate = (document.parent / target.split("#")[0]).resolve()
            try:
                candidate.relative_to(ROOT)
            except ValueError:
                problems.append(f"{document.relative_to(ROOT)} links outside the repository: {target}")
                continue
            if not candidate.is_file():
                problems.append(f"{document.relative_to(ROOT)} links to missing file: {target}")
    agents = SKILL / "agents"
    if agents.is_dir():
        for entry in sorted(agents.iterdir()):
            if entry.suffix not in {".yaml", ".yml"}:
                problems.append(f"{entry.relative_to(ROOT)} must be a YAML file")
                continue
            try:
                yaml.safe_load(entry.read_text(encoding="utf-8"))
            except Exception as exc:
                problems.append(f"{entry.relative_to(ROOT)} is not valid YAML: {exc}")
    return problems


def main() -> int:
    problems = _failures()
    if problems:
        print("skill_check=fail")
        print("\n".join(problems))
        return 1
    print("skill_check=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
