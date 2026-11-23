#!/usr/bin/env python3
r"""Standalone Antigravity / Agent Skills validator for `.agents/skills/`.

Checks every skill directory under the target root (default: ``.agents/skills``):
1. Valid YAML frontmatter (`---` ... `---`) and non-empty Markdown body.
2. `name`: lowercase kebab-case (`a-z`, `0-9`, `-`, no leading/trailing/consecutive
   hyphens), length <= 64 chars, and matches the parent skill directory name.
3. `description`: declared with YAML folded block scalar `>-`, rendered length
   < 1024 chars, and explicitly includes both `Use when` and `Don't use for`.
4. `SKILL.md` line budget: strictly <= 450 lines (hard fail > 800 lines; fails
   > 450 lines by default for production workshop skills unless `--allow-soft-limit`).
5. Relative link integrity: every relative link in `SKILL.md` resolves to an
   existing file inside the skill directory, zero orphan `references/*.md` files
   exist, and zero 2-hop links between `references/*.md` files exist.
6. Portability guard: rejects hardcoded workstation paths (`/home/<user>/`,
   `/Users/`, `C:\Users\`) anywhere in `SKILL.md` or `references/**/*.md`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

NAME_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
USE_WHEN_REGEX = re.compile(r"\buse\s+when\b", re.IGNORECASE)
DONT_USE_FOR_REGEX = re.compile(r"\bdon['’]t\s+use\s+for\b", re.IGNORECASE)
DESCRIPTION_FOLDED_REGEX = re.compile(r"^description\s*:\s*>-\s*(?:#.*)?$", re.MULTILINE)
MARKDOWN_LINK_REGEX = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_SCHEME_REGEX = re.compile(r"^(?:https?|mailto|ftp|tel|data):", re.IGNORECASE)
WORKSTATION_PATH_REGEX = re.compile(
    r"(?:/home/[^/\s]+/|/Users/[^/\s]+/|C:\\\\?Users\\\\?)", re.IGNORECASE
)


@dataclass
class SkillValidationReport:
    """Validation result for a single skill directory."""

    skill_dir: str
    skill_name: str
    line_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    linked_references: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def _parse_yaml_frontmatter_fallback(raw_yaml: str) -> dict[str, Any]:
    """Minimal stdlib YAML frontmatter parser used if PyYAML is not installed."""
    data: dict[str, Any] = {}
    lines = raw_yaml.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" not in line or line.startswith((" ", "\t")):
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        value_part = rest.strip()

        if value_part in {">", ">-", "|", "|-"}:
            folded = value_part.startswith(">")
            block_lines: list[str] = []
            i += 1
            base_indent: int | None = None
            while i < len(lines):
                sub = lines[i]
                if sub.strip() == "":
                    block_lines.append("")
                    i += 1
                    continue
                indent = len(sub) - len(sub.lstrip(" "))
                if indent == 0:
                    break
                if base_indent is None:
                    base_indent = indent
                block_lines.append(sub[min(indent, base_indent) :])
                i += 1
            while block_lines and block_lines[-1] == "":
                block_lines.pop()
            if folded:
                paragraphs: list[str] = []
                current: list[str] = []
                for bl in block_lines:
                    if bl == "":
                        if current:
                            paragraphs.append(" ".join(current))
                            current = []
                    else:
                        current.append(bl.strip())
                if current:
                    paragraphs.append(" ".join(current))
                data[key] = "\n\n".join(paragraphs).strip()
            else:
                data[key] = "\n".join(block_lines).strip()
            continue

        # Strip unquoted inline comments
        if value_part and value_part[0] not in {"'", '"'}:
            value_part = re.sub(r"\s+#.*$", "", value_part).strip()
        elif len(value_part) >= 2 and value_part[0] == value_part[-1]:
            value_part = value_part[1:-1]
        data[key] = value_part
        i += 1

    return data


def parse_frontmatter(text: str) -> tuple[str, dict[str, Any], str]:
    """Split a Markdown document into (raw_frontmatter, parsed_dict, body)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must begin with YAML frontmatter delimited by '---'.")

    closing_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing_idx = idx
            break
    if closing_idx is None:
        raise ValueError("SKILL.md YAML frontmatter is missing its closing '---' delimiter.")

    raw_yaml = "\n".join(lines[1:closing_idx])
    body = "\n".join(lines[closing_idx + 1 :])

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        parsed = _parse_yaml_frontmatter_fallback(raw_yaml)
    else:
        try:
            parsed = yaml.safe_load(raw_yaml)
        except yaml.YAMLError as exc:
            raise ValueError(f"Malformed YAML frontmatter: {exc}") from exc
        if not isinstance(parsed, dict):
            raise TypeError("YAML frontmatter must deserialize to a key-value mapping.")

    return raw_yaml, parsed, body


def strip_code_regions(markdown_text: str) -> str:
    """Remove fenced code blocks and inline code spans before scanning Markdown links."""
    out_lines: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    for line in markdown_text.splitlines():
        stripped = line.lstrip()
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match:
            token = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_char = token[0]
                fence_len = len(token)
                continue
            if token[0] == fence_char and len(token) >= fence_len and stripped.strip() == token:
                in_fence = False
                continue
        if not in_fence:
            cleaned = re.sub(r"`[^`]*`", "", line)
            out_lines.append(cleaned)

    return "\n".join(out_lines)


def extract_relative_links(markdown_text: str) -> list[str]:
    """Extract normalized relative file targets from Markdown links."""
    cleaned = strip_code_regions(markdown_text)
    targets: list[str] = []
    for match in MARKDOWN_LINK_REGEX.finditer(cleaned):
        raw_target = match.group(1).strip()
        if not raw_target:
            continue
        if raw_target.startswith("<") and ">" in raw_target:
            raw_target = raw_target[1 : raw_target.index(">")].strip()
        else:
            raw_target = raw_target.split()[0].strip()
        if not raw_target or raw_target.startswith("#") or EXTERNAL_SCHEME_REGEX.match(raw_target):
            continue
        path_only = raw_target.split("#", 1)[0].split("?", 1)[0].strip()
        if path_only:
            targets.append(unquote(path_only))
    return targets


def validate_skill_dir(
    skill_dir: Path,
    *,
    max_lines: int = 450,
    hard_max_lines: int = 800,
    allow_soft_limit: bool = False,
) -> SkillValidationReport:
    """Validate a single skill directory against all production workshop rules."""
    report = SkillValidationReport(
        skill_dir=str(skill_dir),
        skill_name=skill_dir.name,
    )
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        report.errors.append("Missing required SKILL.md file.")
        return report

    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    report.line_count = len(lines)

    # 1. Line budget check
    if report.line_count > hard_max_lines:
        report.errors.append(
            f"SKILL.md has {report.line_count} lines (exceeds hard limit of {hard_max_lines} lines)."
        )
    elif report.line_count > max_lines:
        msg = (
            f"SKILL.md has {report.line_count} lines (exceeds production limit of "
            f"{max_lines} lines; move deep material into references/*.md)."
        )
        if allow_soft_limit:
            report.warnings.append(msg)
        else:
            report.errors.append(msg)

    # 2. YAML frontmatter + Markdown body check
    try:
        raw_yaml, frontmatter, body = parse_frontmatter(text)
    except (ValueError, TypeError) as exc:
        report.errors.append(f"Invalid YAML frontmatter: {exc}")
        return report

    if not body.strip():
        report.errors.append("SKILL.md Markdown instruction body is empty.")

    # 3. Frontmatter `name` rules
    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        report.errors.append("Frontmatter 'name' is missing or empty.")
    else:
        name = name.strip()
        if len(name) > 64:
            report.errors.append(f"Frontmatter 'name' ({len(name)} chars) exceeds 64 chars.")
        if not NAME_REGEX.match(name):
            report.errors.append(
                f"Frontmatter 'name' ({name!r}) must be lowercase kebab-case [a-z0-9-] "
                "with no leading, trailing, or consecutive hyphens."
            )
        if name != skill_dir.name:
            report.errors.append(
                f"Frontmatter 'name' ({name!r}) must match parent directory name ({skill_dir.name!r})."
            )

    # 4. Frontmatter `description` rules (`>-`, <1024 chars, `Use when` + `Don't use for`)
    description = frontmatter.get("description")
    if not DESCRIPTION_FOLDED_REGEX.search(raw_yaml):
        report.errors.append(
            "Frontmatter 'description' must use YAML folded block scalar syntax (`description: >-`)."
        )
    if not isinstance(description, str) or not description.strip():
        report.errors.append("Frontmatter 'description' is missing or empty.")
    else:
        desc_clean = description.strip()
        if len(desc_clean) >= 1024:
            report.errors.append(
                f"Frontmatter 'description' ({len(desc_clean)} chars) must be < 1024 chars."
            )
        if not USE_WHEN_REGEX.search(desc_clean):
            report.errors.append("Frontmatter 'description' must include a 'Use when' trigger clause.")
        if not DONT_USE_FOR_REGEX.search(desc_clean):
            report.errors.append(
                "Frontmatter 'description' must include a \"Don't use for\" boundary clause "
                "(prevents co-trigger shadowing)."
            )

    # 5. Relative links in SKILL.md -> must exist and stay within skill_dir
    skill_root_resolved = skill_dir.resolve()
    references_root = (skill_dir / "references").resolve()
    linked_ref_paths: set[Path] = set()

    for rel_target in extract_relative_links(body):
        resolved_target = (skill_dir / rel_target).resolve()
        try:
            resolved_target.relative_to(skill_root_resolved)
        except ValueError:
            report.errors.append(
                f"Relative link {rel_target!r} in SKILL.md escapes the skill directory."
            )
            continue

        if not resolved_target.exists():
            report.errors.append(f"Broken relative link in SKILL.md: {rel_target!r} (file not found).")
            continue

        try:
            rel_to_refs = resolved_target.relative_to(references_root)
            linked_ref_paths.add(resolved_target)
            report.linked_references.append(f"references/{rel_to_refs.as_posix()}")
        except ValueError:
            pass

    # 6. Zero orphan references/*.md files + 7. Zero 2-hop reference links
    if references_root.is_dir():
        ref_files = sorted(references_root.rglob("*.md"))
        for ref_file in ref_files:
            ref_resolved = ref_file.resolve()
            rel_display = ref_resolved.relative_to(skill_root_resolved).as_posix()
            if ref_resolved not in linked_ref_paths:
                report.errors.append(
                    f"Orphan reference file {rel_display!r} is not linked from SKILL.md."
                )

            ref_text = ref_file.read_text(encoding="utf-8")
            for nested_target in extract_relative_links(ref_text):
                nested_resolved = (ref_file.parent / nested_target).resolve()
                try:
                    nested_resolved.relative_to(references_root)
                    report.errors.append(
                        f"2-hop reference link forbidden: {rel_display!r} links to "
                        f"{nested_target!r} inside references/. Keep all reference links 1-hop from SKILL.md."
                    )
                    continue
                except ValueError:
                    pass

                # Also verify non-reference relative links resolve cleanly
                try:
                    nested_resolved.relative_to(skill_root_resolved)
                    if not nested_resolved.exists():
                        report.errors.append(
                            f"Broken relative link {nested_target!r} inside {rel_display!r}."
                        )
                except ValueError:
                    report.errors.append(
                        f"Relative link {nested_target!r} inside {rel_display!r} escapes the skill directory."
                    )

    # 8. Portability guard: reject hardcoded workstation paths in SKILL.md and references/**/*.md
    md_files_to_scan = [skill_md]
    if references_root.is_dir():
        md_files_to_scan.extend(sorted(references_root.rglob("*.md")))
    for md_file in md_files_to_scan:
        rel_md = md_file.resolve().relative_to(skill_root_resolved).as_posix()
        for line_no, line in enumerate(md_file.read_text(encoding="utf-8").splitlines(), start=1):
            match = WORKSTATION_PATH_REGEX.search(line)
            if match:
                report.errors.append(
                    f"Hardcoded workstation path {match.group(0)!r} found in {rel_md}:{line_no}. "
                    "Use repo-relative paths instead."
                )

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate all Antigravity workshop skills under .agents/skills/.",
    )
    parser.add_argument(
        "skills_root",
        nargs="?",
        type=Path,
        default=Path(".agents/skills"),
        help="Directory containing skill subfolders (default: .agents/skills).",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=450,
        help="Production SKILL.md line limit (default: 450).",
    )
    parser.add_argument(
        "--hard-max-lines",
        type=int,
        default=800,
        help="Hard SKILL.md line cap (default: 800).",
    )
    parser.add_argument(
        "--allow-soft-limit",
        action="store_true",
        help="Treat 451..800 line SKILL.md files as warnings instead of failures.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Exit 0 even if no skill directories are found under skills_root.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    skills_root: Path = args.skills_root

    if not skills_root.is_dir():
        print(f"ERROR: Skills directory not found: {skills_root}", file=sys.stderr)
        return 1

    skill_dirs = sorted(
        p for p in skills_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if not skill_dirs:
        if args.allow_empty:
            print(f"INFO: No skill folders found under {skills_root}.")
            return 0
        print(f"ERROR: No skill folders found under {skills_root}.", file=sys.stderr)
        return 1

    reports = [
        validate_skill_dir(
            skill_dir,
            max_lines=args.max_lines,
            hard_max_lines=args.hard_max_lines,
            allow_soft_limit=args.allow_soft_limit,
        )
        for skill_dir in skill_dirs
    ]

    all_passed = all(r.passed for r in reports)

    if args.json:
        print(
            json.dumps(
                {
                    "skills_root": str(skills_root),
                    "passed": all_passed,
                    "skills_checked": len(reports),
                    "reports": [asdict(r) | {"passed": r.passed} for r in reports],
                },
                indent=2,
            )
        )
        return 0 if all_passed else 1

    for report in reports:
        status = "PASS" if report.passed else "FAIL"
        print(
            f"[{status}] {report.skill_name} "
            f"({report.line_count} lines, {len(report.linked_references)} refs)"
        )
        for warning in report.warnings:
            print(f"  WARN: {warning}")
        for error in report.errors:
            print(f"  ERROR: {error}")

    passed_count = sum(1 for r in reports if r.passed)
    print(f"\nSkill validation summary: {passed_count}/{len(reports)} passed.")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
