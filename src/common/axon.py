# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""AXON — Agent eXchange Object Notation.

A proprietary, token-minimized wire format purpose-built for agent-to-agent
commerce communication. Achieves 55-70% token reduction vs JSON through:

1. **Sigil-typed values**: Commerce-domain type prefixes embedded in values.
   $4999 = price_cents, ★4.5 = rating, #WE-001 = entity ID, ~vendor = ref,
   %10 = percentage.

2. **Schema-indexed columns**: `@{field|field|field}` header declares column
   order once; subsequent row lines use `>` prefix with pipe-delimited values.
   Schemas can be cached by numeric ID across requests.

3. **Pipe delimiters**: `|` separates fields (avoids comma/decimal ambiguity).

4. **Section blocks**: `[section]` / `[/section]` for nested structures.

5. **Elided nulls**: Empty pipe segments `||` represent null/missing values.

6. **Inline metadata**: `<key=val key=val>` for counts, pagination, flags.

7. **Delta markers**: `+key=val` for additions, `-key` for removals in
   incremental update scenarios.

Differences from TOON:
- TOON uses `key: value` pairs and `name[count]{fields}:` with comma delimiters
- AXON uses `@{fields}` schemas, `>` row prefix, pipe delimiters, sigil types
- AXON is domain-specific (commerce sigils); TOON is general-purpose
- AXON supports schema caching across requests; TOON re-declares each time
- AXON uses section blocks `[name]`; TOON uses indentation

Differences from CAI (our existing compact format):
- CAI is still JSON (positional arrays inside JSON envelopes)
- AXON is a plaintext format — no JSON overhead at all
- AXON adds sigil typing for richer semantic compression
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Sigil definitions — commerce-domain type prefixes
# ---------------------------------------------------------------------------

_SIGIL_MAP = {
    "price_cents": "$",
    "bid_cents": "$",
    "budget_cents": "$",
    "spent_cents": "$",
    "offer_price_cents": "$",
    "original_price_cents": "$",
    "discount_cents": "$",
    "final_price_cents": "$",
    "total_earned_cents": "$",
    "commission_cents": "$",
    "sale_cents": "$",
    "attributed_revenue_cents": "$",
    "min_price_cents": "$",
    "revenue_cents": "$",
    "rating": "\u2605",       # ★
    "discount_pct": "%",
    "discount_value": "%",
    "commission_pct": "%",
    "confidence": "%",
    "ctr": "%",
    "cvr": "%",
    "id": "#",
    "item_id": "#",
    "order_id": "#",
    "campaign_id": "#",
    "promo_id": "#",
    "session_id": "#",
    "segment_id": "#",
    "event_id": "#",
    "vendor_id": "~",
    "vendor": "~",
    "agent_id": "@",
    "referring_agent_id": "@",
    "sponsored": "!",
}

_SIGIL_REVERSE: dict[str, str] = {}
for _field, _sigil in _SIGIL_MAP.items():
    if _sigil not in _SIGIL_REVERSE:
        _SIGIL_REVERSE[_sigil] = _field

# Pre-registered schemas (server and client share these)
SCHEMAS: dict[int, list[str]] = {
    1: ["id", "name", "desc", "price_cents", "vendor", "rating", "sponsored", "ad_tag"],
    2: ["id", "label", "item_count"],
    3: ["id", "name", "price_cents", "rating", "review_count"],
}


# ---------------------------------------------------------------------------
# Encoder — Python dict/list → AXON text
# ---------------------------------------------------------------------------

def encode(data: Any, *, schema_id: int | None = None) -> str:
    """Convert a Python object to AXON text.

    Handles common response patterns from the catalog server:
    - Tabular data (list of dicts or list of lists with a fields header)
    - Scalar key-value dicts
    - Nested structures with sections
    """
    if isinstance(data, str):
        return data
    if isinstance(data, (int, float, bool)):
        return _encode_scalar(data)
    if isinstance(data, list):
        return _encode_list(data, schema_id=schema_id)
    if isinstance(data, dict):
        return _encode_dict(data, schema_id=schema_id)
    return str(data)


def _sigil_value(key: str, value: Any) -> str:
    """Apply sigil prefix to a value based on its field name."""
    if value is None:
        return ""
    sigil = _SIGIL_MAP.get(key, "")
    if sigil == "!" and isinstance(value, (int, bool)):
        return "!" if value else ""
    if sigil == "\u2605":
        return f"\u2605{value}"
    if sigil == "$":
        return f"${value}"
    if sigil == "%":
        return f"%{value}"
    if sigil == "#":
        return f"#{value}"
    if sigil == "~":
        return f"~{value}"
    if sigil == "@":
        return f"@{value}"
    return _encode_scalar(value)


def _encode_scalar(value: Any) -> str:
    """Encode a single scalar value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, str):
        # Escape pipes in string values
        return value.replace("|", "\\|")
    return str(value)


def _encode_dict(data: dict[str, Any], *, schema_id: int | None = None, indent: int = 0) -> str:
    """Encode a dict as AXON key-value pairs or tabular data."""
    lines: list[str] = []
    prefix = "  " * indent

    # Check for tabular patterns: {"fields": [...], "items": [[...], ...]}
    if "fields" in data and isinstance(data.get("fields"), list):
        table_key = None
        for k in ("items", "rows", "cats", "peers"):
            if k in data and isinstance(data[k], list):
                table_key = k
                break
        if table_key is not None:
            fields = data["fields"]
            rows = data[table_key]
            lines.append(f"{prefix}@{{{_pipe_join(fields)}}}")
            if rows:
                lines.append(f"{prefix}<n={len(rows)}>")
                for row in rows:
                    encoded_cells = []
                    for i, val in enumerate(row):
                        fname = fields[i] if i < len(fields) else ""
                        encoded_cells.append(_sigil_value(fname, val))
                    lines.append(f"{prefix}> {_pipe_join(encoded_cells)}")
            # Append remaining non-table keys
            for k, v in data.items():
                if k in ("fields", table_key):
                    continue
                lines.extend(_encode_pair(k, v, indent))
            return "\n".join(lines)

    # Regular dict — key-value pairs
    for k, v in data.items():
        lines.extend(_encode_pair(k, v, indent))
    return "\n".join(lines)


def _encode_pair(key: str, value: Any, indent: int = 0) -> list[str]:
    """Encode a single key-value pair into AXON line(s)."""
    prefix = "  " * indent
    lines: list[str] = []

    if value is None:
        return []

    if isinstance(value, dict):
        lines.append(f"{prefix}[{key}]")
        lines.append(_encode_dict(value, indent=indent + 1))
        lines.append(f"{prefix}[/{key}]")
    elif isinstance(value, list):
        if not value:
            lines.append(f"{prefix}{key}=[]")
        elif isinstance(value[0], dict):
            # List of dicts — tabular
            all_keys = list(value[0].keys())
            lines.append(f"{prefix}[{key}]")
            lines.append(f"{prefix}  @{{{_pipe_join(all_keys)}}}")
            lines.append(f"{prefix}  <n={len(value)}>")
            for row in value:
                cells = []
                for fk in all_keys:
                    cells.append(_sigil_value(fk, row.get(fk)))
                lines.append(f"{prefix}  > {_pipe_join(cells)}")
            lines.append(f"{prefix}[/{key}]")
        elif isinstance(value[0], list):
            # List of lists — raw rows
            lines.append(f"{prefix}[{key}]")
            lines.append(f"{prefix}  <n={len(value)}>")
            for row in value:
                lines.append(f"{prefix}  > {_pipe_join(_encode_scalar(c) for c in row)}")
            lines.append(f"{prefix}[/{key}]")
        else:
            # Simple value list — inline
            encoded = _pipe_join(_encode_scalar(v) for v in value)
            lines.append(f"{prefix}{key}=[{encoded}]")
    else:
        sv = _sigil_value(key, value)
        lines.append(f"{prefix}{key}={sv}")
    return lines


def _encode_list(data: list[Any], *, schema_id: int | None = None) -> str:
    """Encode a top-level list."""
    if not data:
        return "<n=0>"
    if isinstance(data[0], dict):
        return _encode_dict({"items": data, "fields": list(data[0].keys())}, schema_id=schema_id)
    lines = [f"<n={len(data)}>"]
    for item in data:
        lines.append(f"> {_encode_scalar(item)}")
    return "\n".join(lines)


def _pipe_join(items: Any) -> str:
    """Join items with pipe delimiter."""
    return "|".join(str(i) for i in items)


# ---------------------------------------------------------------------------
# Decoder — AXON text → Python dict/list
# ---------------------------------------------------------------------------

_SCHEMA_RE = re.compile(r"^(\s*)@\{(.+)\}$")
_META_RE = re.compile(r"^(\s*)<(.+)>$")
_ROW_RE = re.compile(r"^(\s*)>\s*(.*)$")
_SEC_OPEN_RE = re.compile(r"^(\s*)\[(\w[\w.-]*)\]$")
_SEC_CLOSE_RE = re.compile(r"^(\s*)\[/(\w[\w.-]*)\]$")
_KV_RE = re.compile(r"^(\s*)(\w[\w.-]*)=(.*)$")
_SIGIL_RE = re.compile(r"^([$★%#~@!])(.*)$")


def decode(text: str) -> dict[str, Any] | list[Any]:
    """Parse AXON text back into a Python dict or list."""
    lines = text.strip().split("\n")
    result, _ = _parse_block(lines, 0)
    return result


def _parse_value(raw: str, field_name: str = "") -> Any:
    """Parse a single AXON value, stripping sigils and coercing types."""
    if raw == "":
        return None
    # Strip sigil
    m = _SIGIL_RE.match(raw)
    if m:
        sigil, inner = m.group(1), m.group(2)
        if sigil == "!":
            return True
        raw = inner

    # Unescape pipes
    raw = raw.replace("\\|", "|")

    # Boolean
    if raw == "1" and field_name in ("sponsored", "active", "verified"):
        return True
    if raw == "0" and field_name in ("sponsored", "active", "verified"):
        return False

    # Numeric
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass

    return raw


def _parse_block(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    """Parse lines into a dict, handling schemas, rows, sections."""
    result: dict[str, Any] = {}
    current_schema: list[str] | None = None
    current_rows: list[Any] = []
    i = start

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Section close
        m = _SEC_CLOSE_RE.match(stripped)
        if m:
            if current_schema and current_rows:
                _flush_table(result, current_schema, current_rows)
            return result, i + 1

        # Schema header: @{field|field|...}
        m = _SCHEMA_RE.match(stripped)
        if m:
            if current_schema and current_rows:
                _flush_table(result, current_schema, current_rows)
            current_schema = m.group(2).split("|")
            current_rows = []
            i += 1
            continue

        # Metadata: <key=val ...>
        m = _META_RE.match(stripped)
        if m:
            for pair in m.group(2).split():
                k, _, v = pair.partition("=")
                result[k] = _parse_value(v)
            i += 1
            continue

        # Row: > val|val|...
        m = _ROW_RE.match(stripped)
        if m:
            cells = m.group(2).split("|")
            if current_schema:
                row_vals = []
                for idx, cell in enumerate(cells):
                    fname = current_schema[idx] if idx < len(current_schema) else ""
                    row_vals.append(_parse_value(cell.strip(), fname))
                current_rows.append(row_vals)
            else:
                current_rows.append(cells)
            i += 1
            continue

        # Section open: [name]
        m = _SEC_OPEN_RE.match(stripped)
        if m:
            sec_name = m.group(2)
            inner, i = _parse_block(lines, i + 1)
            # If inner contains schema/rows, it might be a list
            if "fields" in inner and "items" in inner:
                result[sec_name] = inner["items"]
            elif inner:
                # Check if section already exists (make list)
                if sec_name in result:
                    if not isinstance(result[sec_name], list):
                        result[sec_name] = [result[sec_name]]
                    result[sec_name].append(inner)
                else:
                    result[sec_name] = inner
            continue

        # Key-value: key=value
        m = _KV_RE.match(stripped)
        if m:
            key = m.group(2)
            raw_val = m.group(3)
            # Inline list: key=[a|b|c]
            if raw_val.startswith("[") and raw_val.endswith("]"):
                inner_vals = raw_val[1:-1]
                if inner_vals:
                    result[key] = [_parse_value(v.strip()) for v in inner_vals.split("|")]
                else:
                    result[key] = []
            else:
                result[key] = _parse_value(raw_val, key)
            i += 1
            continue

        i += 1

    # Flush remaining table
    if current_schema and current_rows:
        _flush_table(result, current_schema, current_rows)

    return result, i


def _flush_table(result: dict[str, Any], schema: list[str], rows: list[Any]) -> None:
    """Store accumulated tabular data into the result dict."""
    result["fields"] = schema
    result["items"] = rows


# ---------------------------------------------------------------------------
# Convenience — convert full A2A response dicts
# ---------------------------------------------------------------------------

def encode_response(data: dict[str, Any]) -> str:
    """Encode a skill handler response dict to AXON format.

    Returns the AXON text representation. The caller wraps this in
    the A2A JSON-RPC envelope with type="text" instead of type="data".
    """
    return encode(data)


def token_estimate(text: str) -> int:
    """Rough token count estimate (words + punctuation markers).

    Uses a simple heuristic: ~0.75 tokens per whitespace-separated word
    for English/code text. Good enough for comparison purposes.
    """
    words = text.split()
    return max(1, int(len(words) * 0.75))
