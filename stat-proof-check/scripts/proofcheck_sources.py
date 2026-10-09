"""Versioned, literal source fragments for a single proof-unit ledger.

Coverage slots are an ordered index, never manuscript line numbers. Every slot
retains its exact physical source line. This deliberately does not expand TeX
macros, conditionals, or inline substitutions.
"""
from __future__ import annotations

from pathlib import Path
import re

VERSION = 1
_hidden_inclusions = {}


def hidden_inclusion_uses(pc, source_files, executable):
    for source in source_files:
        try:
            raw = "\n".join(pc.read_lines(source))
        except pc.TextArtifactReadError:
            # Auxiliary declaration analysis cannot decode this member. The
            # source snapshot, parser warning review, and conservative shared
            # context binding still retain it. Required proof fragments are
            # read by visit() below and must never be skipped here instead.
            continue
        key = (str(source), pc.sha256_text(raw))
        if key not in _hidden_inclusions:
            warnings = []
            pc.warn_definition_body_inclusions(raw, source_name=str(source), warnings=warnings)
            hidden = []
            if warnings:
                scanned = pc.mask_tex_literals_for_definition_scan(raw)
                for declaration in pc.TEX_DEFINITION_COMMAND_RE.finditer(scanned):
                    if not any(pc.DEFINITION_BODY_INCLUSION_RE.search(scanned[first:last])
                               for first, last in pc.tex_definition_body_spans(scanned, declaration)):
                        continue
                    tail = scanned[declaration.end():]
                    command = re.match(r"\s*\{?\s*(\\[A-Za-z@]+)", tail)
                    environment = re.match(r"\s*\{([^}]+)\}", tail)
                    if command:
                        hidden.append(re.escape(command.group(1)) + r"(?![A-Za-z@])")
                    elif environment:
                        hidden.append(r"\\begin\s*\{" + re.escape(environment.group(1)) + r"\}")
            if len(_hidden_inclusions) > 128:
                _hidden_inclusions.clear()
            _hidden_inclusions[key] = hidden
        if any(re.search(pattern, executable) for pattern in _hidden_inclusions[key]):
            raise ValueError("Incomplete included proof: invoked macro or environment hides an inclusion defined in " +
                             str(source) + "; use a reviewed literal source transcription before extraction or review")


def context_files(pc, path, base):
    audit = pc.containing_audit_root(base)
    if audit is not None:
        manifest, errors = pc.load_json_object(audit / "AUDIT_MANIFEST.json", "source manifest")
        if not errors:
            return [pc.resolve_stored_path(row["file"], audit)
                    for row in manifest.get("source_snapshot", {}).get("files", [])
                    if isinstance(row, dict) and isinstance(row.get("file"), str)]
    return pc.discover_source_closure(path)["files"]


def expand(pc, path, start, end, base, *, project_root=None):
    project_root = (project_root or base).resolve()
    rows = []
    fragments = []
    active = []
    visited = set()
    has_inclusion = False
    has_custom_wrapper = False
    aliases = None

    def visit(source, first, last):
        nonlocal has_inclusion, has_custom_wrapper, aliases
        source = source.resolve()
        if source in active:
            raise ValueError("Incomplete included proof: inclusion cycle at " + str(source))
        if source in visited:
            raise ValueError("Incomplete included proof: repeated inclusion of " + str(source) +
                             "; use distinct reviewed source passages so reference occurrences remain unambiguous")
        if len(active) >= 64:
            raise ValueError("Incomplete included proof: inclusion nesting exceeds 64 files")
        lines = pc.read_lines(source)
        if not (1 <= first <= last <= len(lines)):
            raise ValueError(f"Incomplete included proof: invalid source {source}:{first}-{last}")
        active.append(source)
        visited.add(source)
        warnings = []
        masked = pc.mask_structural_tex("\n".join(lines), warnings=warnings,
                                        source_name=pc.relative_or_absolute(source, base)).split("\n")
        hidden_inclusion_uses(pc, context_files(pc, path, base), "\n".join(masked[first - 1:last]))
        # Every row in this visit comes from the same resolved source. Resolve
        # its display identity once instead of repeating filesystem work per line.
        file_value = pc.relative_or_absolute(source, base)
        pending = None
        for number in range(first, last + 1):
            clean = masked[number - 1]
            commands = list(pc.INCLUSION_COMMAND_RE.finditer(clean))
            include = None
            if commands:
                has_inclusion = True
                # One complete literal directive on its own physical line is
                # the supported source form. Retain that line as provenance.
                match = re.fullmatch(r"\s*\\(?:input|include)\s*\{([^{}]+)\}\s*", clean)
                if match is None:
                    match = re.fullmatch(r"\s*\\input\s+([^\s%{}]+)\s*", clean)
                if match is None or len(commands) != 1:
                    raise ValueError(f"Incomplete included proof at {source}:{number}: "
                                     "use one literal \\input{file} or \\include{file} on its own line; "
                                     "inline, dynamic and import substitutions require a reviewed literal transcription")
                raw = match.group(1).strip()
                if any(char in raw for char in ("\\", "#", "~", "$")):
                    raise ValueError(f"Incomplete included proof at {source}:{number}: dynamic inclusion {raw!r}; "
                                     "supply a reviewed literal source path")
                requested = Path(raw)
                if not requested.suffix:
                    requested = requested.with_suffix(".tex")
                candidates = [requested.resolve()] if requested.is_absolute() else [
                    (directory / requested).resolve() for directory in dict.fromkeys((source.parent, project_root))]
                candidates = list(dict.fromkeys(candidate for candidate in candidates if candidate.is_file()))
                if len(candidates) != 1:
                    raise ValueError(f"Incomplete included proof at {source}:{number}: "
                                     f"{'ambiguous' if candidates else 'missing'} literal inclusion {raw!r}; "
                                     "resolve the source path before extracting or reviewing this unit")
                include = candidates[0]
            # Conservative source masking warnings cannot be waived by hashing
            # a wrapper. The caller also records them in inventory discovery.
            if commands and warnings:
                raise ValueError(f"Incomplete included proof at {source}:{number}: " + "; ".join(warnings))
            row = {"line": start + len(rows), "sha256": pc.sha256_text(lines[number - 1]),
                   "text": lines[number - 1], "file": file_value, "source_line": number}
            if include is not None:
                row["include_directive"] = True
            wrapper = re.fullmatch(r"\s*\\(?:begin|end)\s*\{([^}]+)\}(?:\s*\[[^]]*\])?\s*", clean)
            if wrapper and wrapper.group(1) != "proof" and aliases is None:
                readable = pc.readable_source_lines(context_files(pc, path, base), [], base)
                aliases = pc.proof_alias_names(readable) - {"proof"}
            if wrapper and wrapper.group(1) in (aliases or set()):
                row["proof_wrapper"] = True
                has_custom_wrapper = True
            rows.append(row)
            if len(rows) > pc.MAX_UNIT_LINES:
                raise ValueError("Expanded included proof exceeds the maximum source coverage size")
            if pending is None:
                pending = {"file": file_value, "start_line": number, "end_line": number,
                           "sequence_start": row["line"], "sequence_end": row["line"]}
            else:
                pending["end_line"] = number
                pending["sequence_end"] = row["line"]
            if include is not None or number == last:
                pending["sha256"] = pc.source_span_sha256(source, pending["start_line"], pending["end_line"])
                fragments.append(pending)
                pending = None
            if include is not None:
                included_lines = pc.read_lines(include)
                if included_lines:
                    visit(include, 1, len(included_lines))
        active.pop()

    visit(path, start, end)
    return {"version": VERSION, "indexing": "ordered_source_lines",
            "project_root": pc.relative_or_absolute(project_root, base),
            "fragments": fragments, "lines": rows, "has_inclusion": has_inclusion,
            "has_custom_wrapper": has_custom_wrapper}


def lock(pc, ledger, path, start, end, base, *, project_root=None):
    expanded = expand(pc, path, start, end, base, project_root=project_root)
    if not expanded["has_inclusion"] and not expanded["has_custom_wrapper"]:
        return
    ledger["source_fragments"] = {key: value for key, value in expanded.items()
                                  if key not in {"lines", "has_inclusion", "has_custom_wrapper"}}
    ledger["source_lines"] = expanded["lines"]
    ledger["source"]["unit_sha256"] = pc.sha256_text("\n".join(row["text"] for row in expanded["lines"]))
    ledger["source_units"], _ = pc.build_compiled_source_units(ledger, [])


def bounds(ledger):
    source = ledger.get("source") or {}
    first, last = source.get("start_line"), source.get("end_line")
    if "source_fragments" in ledger and isinstance(first, int):
        last = first + len(ledger.get("source_lines") or []) - 1
    return first, last


def location(ledger, unit):
    first, last = unit["lines"]
    if "source_fragments" not in ledger:
        return {"file": ledger["source"]["file"], "start_line": first, "end_line": last}
    start, _ = bounds(ledger)
    rows = ledger["source_lines"][first - start:last - start + 1]
    if not rows or len(rows) != last - first + 1:
        raise ValueError("Source unit is outside the ordered source fragments")
    if not all(isinstance(row, dict) and isinstance(row.get("source_line"), int) for row in rows):
        raise ValueError("Source unit has a malformed original line mapping")
    if any(row.get("file") != rows[0].get("file") or
           row.get("source_line") != rows[0].get("source_line", -1) + offset
           for offset, row in enumerate(rows)):
        raise ValueError("A source group cannot cross an included-source boundary; split it into separate source units")
    return {"file": rows[0]["file"], "start_line": rows[0]["source_line"],
            "end_line": rows[-1]["source_line"]}


def current(pc, ledger, base):
    source = ledger["source"]
    metadata = ledger.get("source_fragments")
    if metadata is not None and (not isinstance(metadata, dict) or metadata.get("version") != VERSION):
        raise ValueError("Unsupported source_fragments version; re-extract the unit and review its complete source")
    path = pc.resolve_stored_path(source["file"], base)
    project = pc.resolve_stored_path(metadata["project_root"], base) if metadata else path.parent
    expanded = expand(pc, path, source["start_line"], source["end_line"], base, project_root=project)
    if expanded["has_inclusion"] and metadata is None:
        raise ValueError("Incomplete included proof: this wrapper-only ledger omits included source; "
                         "re-extract to source_fragments version 1 and re-review all expanded source units")
    if metadata is not None:
        expected = {key: value for key, value in expanded.items() if key not in {"lines", "has_inclusion", "has_custom_wrapper"}}
        if metadata != expected or ledger.get("source_lines") != expanded["lines"]:
            raise ValueError("Included source lock is stale or incomplete; re-extract and re-review the changed source fragments")
    return [row["text"] for row in expanded["lines"]]


def statement_binding_errors(pc, statement, source_base, spans, ledger_base):
    errors = []
    try:
        original = pc.resolve_stored_path(statement["file"], source_base)
        expanded = expand(pc, original, statement["start_line"], statement["end_line"], source_base)
        for fragment in expanded["fragments"]:
            path = pc.resolve_stored_path(fragment["file"], source_base)
            if path == original:
                continue
            if not any(isinstance(span, dict) and
                       pc.resolve_stored_path(str(span.get("file")), ledger_base) == path and
                       span.get("start_line") == fragment["start_line"] and
                       span.get("end_line") == fragment["end_line"] and
                       span.get("sha256") == fragment["sha256"] for span in (spans or [])):
                errors.append(f"Normalized obligation omits included statement source {fragment['file']}:"
                              f"{fragment['start_line']}-{fragment['end_line']}; re-extract and normalize its complete statement")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors
