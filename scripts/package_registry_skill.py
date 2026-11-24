#!/usr/bin/env python3
"""Google Cloud Skill Registry ZIP packager and payload validator (Lab 4).

Builds a deterministic `.zip` archive from a skill directory and validates ALL
official Google Cloud Skill Registry payload validation rules from:
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry

All 16 atomic checks enforced (11 ZIP-level + 5 SKILL.md-level):
  01. Valid, non-corrupt ZIP archive with complete header metadata
  02. ZIP archive is not empty
  03. ZIP archive contains <= 10,000 items
  04. No entry path contains `..` or starts with `/` or `\\`
  05. Zero symbolic links (in source tree or ZIP external attributes)
  06. Zero duplicate file or folder names in the ZIP
  07. Total uncompressed size <= 500 MB (<= 10 MB total & <= 1 MB/file with `--agent-registry`)
  08. Compression ratio <= 100 (zip-bomb protection)
  09. Directory nesting depth <= 8 levels
  10. ZIP contains `SKILL.md` (directly at root recommended / enforced with `--agent-registry`)
  11. Compressed ZIP archive size <= 10 MB (<= 1 MB with `--agent-registry`)
  12. `SKILL.md` contains valid YAML frontmatter AND non-empty Markdown content
  13. Frontmatter `name`: present, <= 64 chars, `[a-z0-9-]`, no leading/trailing `-`
  14. Frontmatter `description`: present and <= 1,024 chars
  15. Frontmatter `license` (if present): <= 1,024 chars
  16. `SKILL.md` Markdown instruction body <= 500,000 chars

Supports `--dry-run` (packages in memory and executes every check without writing
a file to disk) and `--validate-zip` (validates an existing `.zip` archive).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import stat
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

MAX_ZIP_ITEMS = 10_000
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB (Vertex AI Skill Registry)
MAX_COMPRESSED_ZIP_BYTES = 10 * 1024 * 1024  # 10 MB (Vertex AI Skill Registry)
MAX_COMPRESSION_RATIO = 100.0
MAX_FOLDER_DEPTH = 8
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1_024
MAX_LICENSE_CHARS = 1_024
MAX_INSTRUCTIONS_CHARS = 500_000

# Stricter limits for Agent Registry Standalone Skills (`agentregistry.googleapis.com/v1`)
AGENT_REGISTRY_MAX_ZIP_BYTES = 1 * 1024 * 1024  # 1 MB compressed
AGENT_REGISTRY_MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024  # 10 MB total uncompressed
AGENT_REGISTRY_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB per file when scanning enabled

SKILL_NAME_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
EXCLUDED_NAMES: frozenset[str] = frozenset({".DS_Store", "__pycache__", ".git", ".pytest_cache"})


@dataclass
class CheckResult:
    """Outcome of a single atomic validation check."""

    rule_id: str
    passed: bool
    detail: str


@dataclass
class PackageReport:
    """Aggregated validation report across all 16 Skill Registry checks."""

    source: str
    output_zip: str | None
    dry_run: bool
    agent_registry_mode: bool
    compressed_bytes: int = 0
    uncompressed_bytes: int = 0
    item_count: int = 0
    checks: list[CheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _parse_yaml_fallback(raw_yaml: str) -> dict[str, Any]:
    """Stdlib YAML frontmatter fallback parser when PyYAML is unavailable."""
    data: dict[str, Any] = {}
    lines = raw_yaml.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line or line.startswith((" ", "\t")):
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        val = rest.strip()
        if val in {">", ">-", "|", "|-"}:
            folded = val.startswith(">")
            block: list[str] = []
            i += 1
            base_indent: int | None = None
            while i < len(lines):
                sub = lines[i]
                if sub.strip() == "":
                    block.append("")
                    i += 1
                    continue
                indent = len(sub) - len(sub.lstrip(" "))
                if indent == 0:
                    break
                if base_indent is None:
                    base_indent = indent
                block.append(sub[min(indent, base_indent) :])
                i += 1
            while block and block[-1] == "":
                block.pop()
            if folded:
                data[key] = " ".join(part.strip() for part in block if part.strip())
            else:
                data[key] = "\n".join(block).strip()
            continue
        if val and val[0] not in {"'", '"'}:
            val = re.sub(r"\s+#.*$", "", val).strip()
        elif len(val) >= 2 and val[0] == val[-1]:
            val = val[1:-1]
        data[key] = val
        i += 1
    return data


def _parse_skill_md(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and Markdown body from `SKILL.md`."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Missing opening '---' YAML frontmatter delimiter.")
    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("Missing closing '---' YAML frontmatter delimiter.")

    raw_yaml = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        parsed = _parse_yaml_fallback(raw_yaml)
    else:
        try:
            parsed = yaml.safe_load(raw_yaml)
        except yaml.YAMLError as exc:
            raise ValueError(f"Malformed YAML frontmatter: {exc}") from exc
        if not isinstance(parsed, dict):
            raise TypeError("YAML frontmatter did not deserialize to a mapping.")

    return parsed, body


def _scan_source_symlinks(skill_dir: Path) -> list[str]:
    """Detect any symlinks inside the source directory before zipping."""
    symlinks: list[str] = []
    for root, dirs, files in os.walk(skill_dir, followlinks=False):
        root_path = Path(root)
        # Skip excluded directories without recursing into them
        kept_dirs: list[str] = []
        for d in dirs:
            if d in EXCLUDED_NAMES:
                continue
            d_path = root_path / d
            if d_path.is_symlink():
                symlinks.append(d_path.relative_to(skill_dir).as_posix())
            else:
                kept_dirs.append(d)
        dirs[:] = kept_dirs

        for f in files:
            if f in EXCLUDED_NAMES or f.endswith(".pyc"):
                continue
            f_path = root_path / f
            if f_path.is_symlink():
                symlinks.append(f_path.relative_to(skill_dir).as_posix())
    return symlinks


def build_zip_bytes(skill_dir: Path) -> bytes:
    """Pack a skill directory deterministically into an in-memory ZIP archive."""
    buf = io.BytesIO()
    entries: list[tuple[Path, str]] = []
    for root, dirs, files in os.walk(skill_dir, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_NAMES and not (Path(root) / d).is_symlink())
        for filename in sorted(files):
            if filename in EXCLUDED_NAMES or filename.endswith(".pyc"):
                continue
            full_path = Path(root) / filename
            if full_path.is_symlink():
                continue
            rel_posix = full_path.relative_to(skill_dir).as_posix()
            entries.append((full_path, rel_posix))

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for full_path, rel_posix in sorted(entries, key=lambda item: item[1]):
            zinfo = zipfile.ZipInfo(filename=rel_posix, date_time=(2026, 1, 1, 0, 0, 0))
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            file_mode = 0o100755 if os.access(full_path, os.X_OK) else 0o100644
            zinfo.external_attr = file_mode << 16
            zf.writestr(
                zinfo,
                full_path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            )

    return buf.getvalue()


def _entry_folder_depth(entry_name: str, is_dir: bool) -> int:
    """Compute folder nesting depth inside a ZIP archive (root file = 0)."""
    clean = entry_name.replace("\\", "/").rstrip("/")
    if not clean:
        return 0
    parts = [p for p in PurePosixPath(clean).parts if p not in {"", "."}]
    return len(parts) if is_dir else max(0, len(parts) - 1)


def validate_zip_payload(
    zip_bytes: bytes,
    *,
    source_label: str,
    expected_dir_name: str | None = None,
    source_symlinks: list[str] | None = None,
    output_zip: str | None = None,
    dry_run: bool = False,
    agent_registry_mode: bool = False,
) -> PackageReport:
    """Validate an in-memory ZIP payload against all 16 Skill Registry rules."""
    report = PackageReport(
        source=source_label,
        output_zip=output_zip,
        dry_run=dry_run,
        agent_registry_mode=agent_registry_mode,
        compressed_bytes=len(zip_bytes),
    )

    def add_check(rule_id: str, passed: bool, detail: str) -> None:
        report.checks.append(CheckResult(rule_id=rule_id, passed=passed, detail=detail))

    # Rule 01: Proper ZIP archive
    buf = io.BytesIO(zip_bytes)
    if not zipfile.is_zipfile(buf):
        add_check("R01_valid_zip", False, "Payload is not a valid ZIP archive.")
        return report
    buf.seek(0)
    try:
        zf = zipfile.ZipFile(buf, mode="r")
        bad_member = zf.testzip()
        if bad_member is not None:
            add_check("R01_valid_zip", False, f"Corrupt ZIP member CRC: {bad_member!r}.")
            zf.close()
            return report
        add_check("R01_valid_zip", True, "Valid ZIP archive with verified CRCs and central directory.")
    except (zipfile.BadZipFile, OSError) as exc:
        add_check("R01_valid_zip", False, f"Failed to open ZIP archive: {exc}")
        return report

    with zf:
        infos = zf.infolist()
        report.item_count = len(infos)

        # Rule 02: Non-empty ZIP
        add_check(
            "R02_non_empty_zip",
            len(infos) > 0,
            f"Archive contains {len(infos)} item(s)." if infos else "ZIP archive is empty.",
        )

        # Rule 03: <= 10,000 items
        items_ok = len(infos) <= MAX_ZIP_ITEMS
        add_check(
            "R03_max_items_10000",
            items_ok,
            f"Item count {len(infos):,} <= {MAX_ZIP_ITEMS:,}."
            if items_ok
            else f"Item count {len(infos):,} exceeds limit of {MAX_ZIP_ITEMS:,} items.",
        )

        # Rule 04: Safe relative paths (no `..` anywhere in entry name, no leading `/` or `\`)
        bad_paths: list[str] = []
        for info in infos:
            name = info.filename
            if name.startswith(("/", "\\")) or ".." in name:
                bad_paths.append(name)
        add_check(
            "R04_no_path_traversal_or_absolute",
            not bad_paths,
            "All archive paths are safe relative paths."
            if not bad_paths
            else f"Unsafe archive paths detected: {bad_paths[:5]}",
        )

        # Rule 05: Zero symbolic links (source tree + ZIP external_attr)
        zip_symlinks = [
            info.filename
            for info in infos
            if stat.S_ISLNK((info.external_attr >> 16) & 0o170000)
        ]
        all_symlinks = list(source_symlinks or []) + zip_symlinks
        add_check(
            "R05_no_symlinks",
            not all_symlinks,
            "Zero symbolic links found."
            if not all_symlinks
            else f"Symbolic links are forbidden: {all_symlinks[:5]}",
        )

        # Rule 06: Zero duplicate file or folder names
        seen_names: set[str] = set()
        duplicates: list[str] = []
        for info in infos:
            normalized = info.filename.replace("\\", "/").rstrip("/")
            if normalized in seen_names:
                duplicates.append(info.filename)
            seen_names.add(normalized)
        add_check(
            "R06_no_duplicate_names",
            not duplicates,
            "Zero duplicate file or folder names."
            if not duplicates
            else f"Duplicate ZIP entries detected: {duplicates[:5]}",
        )

        # Rule 07: Uncompressed size <= 500 MB (and optional Agent Registry 10 MB / 1 MB per file)
        total_uncompressed = sum(info.file_size for info in infos)
        report.uncompressed_bytes = total_uncompressed
        max_single_file = max((info.file_size for info in infos), default=0)
        if agent_registry_mode:
            uncompressed_ok = (
                total_uncompressed <= AGENT_REGISTRY_MAX_UNCOMPRESSED_BYTES
                and max_single_file <= AGENT_REGISTRY_MAX_FILE_BYTES
            )
            if total_uncompressed > AGENT_REGISTRY_MAX_UNCOMPRESSED_BYTES:
                detail_r07 = (
                    f"Total uncompressed size {total_uncompressed:,} bytes exceeds Agent Registry "
                    f"scanning limit of {AGENT_REGISTRY_MAX_UNCOMPRESSED_BYTES:,} bytes (10 MB)."
                )
            elif max_single_file > AGENT_REGISTRY_MAX_FILE_BYTES:
                detail_r07 = (
                    f"Largest file ({max_single_file:,} bytes) exceeds Agent Registry per-file "
                    f"scanning limit of {AGENT_REGISTRY_MAX_FILE_BYTES:,} bytes (1 MB)."
                )
            else:
                detail_r07 = (
                    f"Total uncompressed size {total_uncompressed:,} bytes <= "
                    f"{AGENT_REGISTRY_MAX_UNCOMPRESSED_BYTES:,} bytes (10 MB) and largest file "
                    f"{max_single_file:,} bytes <= {AGENT_REGISTRY_MAX_FILE_BYTES:,} bytes (1 MB)."
                )
        else:
            uncompressed_ok = total_uncompressed <= MAX_UNCOMPRESSED_BYTES
            detail_r07 = (
                f"Total uncompressed size {total_uncompressed:,} bytes <= "
                f"{MAX_UNCOMPRESSED_BYTES:,} bytes (500 MB)."
                if uncompressed_ok
                else f"Total uncompressed size {total_uncompressed:,} bytes exceeds limit of "
                f"{MAX_UNCOMPRESSED_BYTES:,} bytes (500 MB)."
            )
            if (
                total_uncompressed > AGENT_REGISTRY_MAX_UNCOMPRESSED_BYTES
                or max_single_file > AGENT_REGISTRY_MAX_FILE_BYTES
            ):
                report.warnings.append(
                    "Uncompressed payload exceeds Agent Registry scanning limits (10 MB total / 1 MB per file)."
                )
        add_check("R07_max_uncompressed_size", uncompressed_ok, detail_r07)

        # Rule 08: Compression ratio <= 100 (zip-bomb protection)
        total_compressed_entries = sum(info.compress_size for info in infos)
        overall_ratio = (
            (total_uncompressed / total_compressed_entries) if total_compressed_entries > 0 else 0.0
        )
        worst_file_ratio = 0.0
        worst_file = ""
        for info in infos:
            if info.compress_size > 0 and info.file_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > worst_file_ratio:
                    worst_file_ratio = ratio
                    worst_file = info.filename
        ratio_ok = overall_ratio <= MAX_COMPRESSION_RATIO and worst_file_ratio <= MAX_COMPRESSION_RATIO
        add_check(
            "R08_max_compression_ratio_100",
            ratio_ok,
            f"Compression ratio ok (overall={overall_ratio:.2f}x, max_file={worst_file_ratio:.2f}x <= 100x)."
            if ratio_ok
            else f"Zip-bomb ratio limit exceeded: overall={overall_ratio:.2f}x, "
            f"worst={worst_file!r} ({worst_file_ratio:.2f}x > 100x).",
        )

        # Rule 09: Folder nesting <= 8 levels deep
        max_depth = 0
        deep_entries: list[str] = []
        for info in infos:
            depth = _entry_folder_depth(info.filename, info.is_dir())
            max_depth = max(max_depth, depth)
            if depth > MAX_FOLDER_DEPTH:
                deep_entries.append(f"{info.filename} (depth={depth})")
        add_check(
            "R09_max_folder_depth_8",
            not deep_entries,
            f"Max folder nesting depth {max_depth} <= {MAX_FOLDER_DEPTH}."
            if not deep_entries
            else f"Directory nesting exceeds 8 levels: {deep_entries[:5]}",
        )

        # Rule 10: Contains SKILL.md
        skill_md_candidates = [
            info.filename
            for info in infos
            if not info.is_dir() and PurePosixPath(info.filename.replace("\\", "/")).name == "SKILL.md"
        ]
        root_skill_md_candidates = [
            name
            for name in skill_md_candidates
            if PurePosixPath(name.replace("\\", "/")).as_posix() == "SKILL.md"
        ]
        has_root_skill_md = bool(root_skill_md_candidates)
        skill_md_ok = has_root_skill_md if agent_registry_mode else bool(skill_md_candidates)
        if skill_md_candidates and not has_root_skill_md:
            report.warnings.append(
                f"SKILL.md found at {skill_md_candidates[0]!r} rather than ZIP root "
                "(Agent Registry requires SKILL.md directly at archive root)."
            )
        selected_skill_md = (
            root_skill_md_candidates[0]
            if has_root_skill_md
            else (skill_md_candidates[0] if skill_md_candidates else "")
        )
        add_check(
            "R10_contains_skill_md",
            skill_md_ok,
            f"Found SKILL.md ({selected_skill_md})."
            if skill_md_ok
            else "Archive does not contain required root-level SKILL.md."
            if agent_registry_mode
            else "Archive does not contain a SKILL.md file.",
        )

        # Rule 11: Compressed ZIP archive size <= 10 MB (<= 1 MB with --agent-registry)
        zip_size_limit = AGENT_REGISTRY_MAX_ZIP_BYTES if agent_registry_mode else MAX_COMPRESSED_ZIP_BYTES
        zip_size_label = "1 MB" if agent_registry_mode else "10 MB"
        zip_size_ok = len(zip_bytes) <= zip_size_limit
        if not agent_registry_mode and len(zip_bytes) > AGENT_REGISTRY_MAX_ZIP_BYTES:
            report.warnings.append(
                f"ZIP size ({len(zip_bytes):,} bytes) exceeds Agent Registry 1 MB compressed limit "
                "(still valid for Vertex AI Skill Registry 10 MB limit)."
            )
        add_check(
            "R11_max_zip_size",
            zip_size_ok,
            f"Compressed ZIP size {len(zip_bytes):,} bytes <= {zip_size_limit:,} bytes ({zip_size_label})."
            if zip_size_ok
            else f"Compressed ZIP size {len(zip_bytes):,} bytes exceeds limit of "
            f"{zip_size_limit:,} bytes ({zip_size_label}).",
        )

        # Rules 12-16: SKILL.md content & frontmatter validation
        if not skill_md_candidates:
            for rid in (
                "R12_skill_md_frontmatter_and_body",
                "R13_frontmatter_name",
                "R14_frontmatter_description",
                "R15_frontmatter_license",
                "R16_instructions_max_500k",
            ):
                add_check(rid, False, "Skipped because SKILL.md is missing.")
            return report

        target_skill_md = selected_skill_md
        try:
            skill_md_text = zf.read(target_skill_md).decode("utf-8")
            frontmatter, body = _parse_skill_md(skill_md_text)
        except (UnicodeDecodeError, ValueError, TypeError, KeyError, OSError) as exc:
            add_check("R12_skill_md_frontmatter_and_body", False, f"SKILL.md parse error: {exc}")
            for rid in (
                "R13_frontmatter_name",
                "R14_frontmatter_description",
                "R15_frontmatter_license",
                "R16_instructions_max_500k",
            ):
                add_check(rid, False, "Blocked by invalid SKILL.md YAML frontmatter.")
            return report

        # Rule 12: Valid YAML frontmatter AND non-empty Markdown content
        has_body = bool(body.strip())
        add_check(
            "R12_skill_md_frontmatter_and_body",
            has_body,
            "SKILL.md has valid YAML frontmatter and non-empty Markdown body."
            if has_body
            else "SKILL.md is missing Markdown instruction content after YAML frontmatter.",
        )

        # Rule 13: Frontmatter `name`
        name = frontmatter.get("name")
        name_issues: list[str] = []
        if not isinstance(name, str) or not name.strip():
            name_issues.append("missing or empty")
        else:
            name_clean = name.strip()
            if len(name_clean) > MAX_NAME_CHARS:
                name_issues.append(f"length {len(name_clean)} > {MAX_NAME_CHARS}")
            if not SKILL_NAME_REGEX.match(name_clean):
                name_issues.append("must contain only [a-z0-9-] and not start/end with '-'")
            if "--" in name_clean:
                report.warnings.append(
                    f"Frontmatter 'name' ({name_clean!r}) contains consecutive hyphens '--' "
                    "(rejected by ADK local SkillToolset loader)."
                )
            if name_clean.startswith("gcp-"):
                report.warnings.append(
                    f"Frontmatter 'name' ({name_clean!r}) starts with reserved 'gcp-' prefix "
                    "(Skill Registry forbids creating SKILL_IDs starting with 'gcp-')."
                )
            if expected_dir_name and name_clean != expected_dir_name:
                report.warnings.append(
                    f"Frontmatter 'name' ({name_clean!r}) differs from folder name "
                    f"({expected_dir_name!r}); ADK local loader requires exact match."
                )
        add_check(
            "R13_frontmatter_name",
            not name_issues,
            f"Valid frontmatter name {name!r}."
            if not name_issues
            else f"Invalid frontmatter 'name': {'; '.join(name_issues)}.",
        )

        # Rule 14: Frontmatter `description` (required, <= 1024 chars)
        desc = frontmatter.get("description")
        desc_ok = isinstance(desc, str) and bool(desc.strip()) and len(desc.strip()) <= MAX_DESCRIPTION_CHARS
        desc_len = len(desc.strip()) if isinstance(desc, str) else 0
        add_check(
            "R14_frontmatter_description",
            desc_ok,
            f"Valid frontmatter description ({desc_len} chars <= {MAX_DESCRIPTION_CHARS})."
            if desc_ok
            else f"Frontmatter 'description' missing or exceeds {MAX_DESCRIPTION_CHARS} chars (got {desc_len}).",
        )

        # Rule 15: Frontmatter `license` (optional, <= 1024 chars)
        lic = frontmatter.get("license")
        if lic is None:
            add_check("R15_frontmatter_license", True, "Optional frontmatter 'license' omitted.")
        else:
            lic_ok = isinstance(lic, str) and len(lic) <= MAX_LICENSE_CHARS
            lic_len = len(lic) if isinstance(lic, str) else -1
            add_check(
                "R15_frontmatter_license",
                lic_ok,
                f"Valid frontmatter 'license' ({lic_len} chars <= {MAX_LICENSE_CHARS})."
                if lic_ok
                else f"Frontmatter 'license' must be a string <= {MAX_LICENSE_CHARS} chars.",
            )

        # Rule 16: SKILL.md Markdown instructions <= 500,000 chars
        body_len = len(body)
        body_ok = body_len <= MAX_INSTRUCTIONS_CHARS
        add_check(
            "R16_instructions_max_500k",
            body_ok,
            f"Markdown instructions length {body_len:,} chars <= {MAX_INSTRUCTIONS_CHARS:,} chars."
            if body_ok
            else f"Markdown instructions length {body_len:,} chars exceeds limit of "
            f"{MAX_INSTRUCTIONS_CHARS:,} chars.",
        )

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Package and validate a skill folder against all 16 Google Cloud Skill Registry rules.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to the skill directory (or an existing .zip file with --validate-zip).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Destination .zip file path (default: dist/<skill_name>.zip; ignored with --dry-run).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Package in memory and run all 16 validation checks without writing a .zip file.",
    )
    parser.add_argument(
        "--validate-zip",
        action="store_true",
        help="Validate an existing .zip archive instead of packaging a directory.",
    )
    parser.add_argument(
        "--agent-registry",
        action="store_true",
        help="Also enforce stricter Agent Registry Standalone Skill caps (<=1 MB zip, <=10 MB unzipped, <=1 MB/file, root SKILL.md).",
    )
    parser.add_argument("--json", action="store_true", help="Output structured JSON report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    source: Path = args.source

    if args.validate_zip or (source.is_file() and source.suffix.lower() == ".zip"):
        if not source.is_file():
            print(f"ERROR: ZIP archive not found: {source}", file=sys.stderr)
            return 1
        zip_bytes = source.read_bytes()
        report = validate_zip_payload(
            zip_bytes,
            source_label=str(source),
            output_zip=str(source),
            dry_run=True,
            agent_registry_mode=args.agent_registry,
        )
    else:
        if not source.is_dir():
            print(f"ERROR: Skill directory not found: {source}", file=sys.stderr)
            return 1
        resolved_source = source.resolve()
        source_dir_name = resolved_source.name or "skill"
        source_symlinks = _scan_source_symlinks(resolved_source)
        zip_bytes = build_zip_bytes(resolved_source)
        output_path = args.output or (Path("dist") / f"{source_dir_name}.zip")
        report = validate_zip_payload(
            zip_bytes,
            source_label=str(source),
            expected_dir_name=resolved_source.name or None,
            source_symlinks=source_symlinks,
            output_zip=None if args.dry_run else str(output_path),
            dry_run=args.dry_run,
            agent_registry_mode=args.agent_registry,
        )
        if report.passed and not args.dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(zip_bytes)

    if args.json:
        print(json.dumps(asdict(report) | {"passed": report.passed}, indent=2))
        return 0 if report.passed else 1

    print(f"Skill Registry Validation Report — {report.source}")
    print(
        f"Mode: {'dry-run' if report.dry_run else 'package'} | "
        f"Profile: {'Agent Registry + Skill Registry' if report.agent_registry_mode else 'Vertex AI Skill Registry'} | "
        f"Items: {report.item_count} | Zip: {report.compressed_bytes:,} B | Unzipped: {report.uncompressed_bytes:,} B"
    )
    print("-" * 72)
    for chk in report.checks:
        tag = "PASS" if chk.passed else "FAIL"
        print(f"  [{tag}] {chk.rule_id}: {chk.detail}")
    for warn in report.warnings:
        print(f"  [WARN] {warn}")
    print("-" * 72)
    passed_count = sum(1 for c in report.checks if c.passed)
    print(f"Result: {passed_count}/{len(report.checks)} atomic checks passed.")
    if report.passed and not report.dry_run and report.output_zip:
        print(f"Wrote validated archive: {report.output_zip}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
