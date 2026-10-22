"""The YAML subset the case template uses — stdlib only, no PyYAML.

Top-level `key: value`; values are scalars, `[a, b]`, `{k: v, ...}`; a key with
no value may be followed by a block list whose items are scalars, flow maps
(`- { due_at: ..., status: done }`) or indented block maps. `# comments` are
dropped. Anything else is a FrontmatterError naming the line — the file is
reported as invalid, never half-read.
"""
from __future__ import annotations

from typing import Any


class FrontmatterError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if ch in "\"'" and quote in (None, ch):
            quote = None if quote else ch
        elif ch == "#" and quote is None and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def _split(inner: str) -> list[str]:
    parts, depth, quote, cur = [], 0, None, ""
    for ch in inner:
        if ch in "\"'" and quote in (None, ch):
            quote = None if quote else ch
        elif quote is None and ch in "[{":
            depth += 1
        elif quote is None and ch in "]}":
            depth -= 1
        elif quote is None and depth == 0 and ch == ",":
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    return [p.strip() for p in parts + [cur] if p.strip()]


def _pair(s: str) -> tuple[str, Any]:
    k, sep, v = s.partition(":")
    if not sep or not k.strip():
        raise FrontmatterError(f"expected 'key: value', got {s!r}")
    return k.strip(), value(v.strip())


def value(s: str) -> Any:
    if s in ("", "~", "null"):
        return None
    if s[0] in "\"'" and s[-1] == s[0] and len(s) > 1:
        return s[1:-1]
    if s[0] == "[" and s[-1] == "]":
        return [value(p) for p in _split(s[1:-1])]
    if s[0] == "{" and s[-1] == "}":
        return dict(_pair(p) for p in _split(s[1:-1]))
    if s in ("true", "false"):
        return s == "true"
    return int(s) if s.lstrip("-").isdigit() else s


def parse(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("no frontmatter (the file must start with ---)")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise FrontmatterError("frontmatter not closed with ---") from None
    out: dict[str, Any] = {}
    key, block, listing = None, None, False
    for n, raw in enumerate(lines[1:end], 2):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        s, indented = line.strip(), line[0].isspace()
        try:
            if not indented:
                key, v = _pair(s)
                out[key], block, listing = v, None, v is None
            elif s.startswith("- ") and listing:
                item, block = s[2:].strip(), None
                if ":" in item and item[0] not in "{[\"'":
                    block = dict([_pair(item)])
                    item_value: Any = block
                else:
                    item_value = value(item)
                out[key] = (out[key] or []) + [item_value]
            elif block is not None:
                k, v = _pair(s)
                block[k] = v
            else:
                raise FrontmatterError("unexpected indentation")
        except FrontmatterError as e:
            raise FrontmatterError(f"line {n}: {e}") from None
    return out
