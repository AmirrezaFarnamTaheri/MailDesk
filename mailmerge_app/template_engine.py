from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import date
from email.utils import parseaddr
from typing import Mapping

# Deliberately tiny, non-executable template language.
# {{Field}}, {{Field|fallback}}, {{#if Field}}...{{/if}}
PLACEHOLDER_RE = re.compile(r"{{\s*(?!#if\b|/if\b)([^{}]+?)\s*}}")
IF_RE = re.compile(r"{{\s*#if\s+([^{}]+?)\s*}}(.*?){{\s*/if\s*}}", re.DOTALL)
LOCAL_ATOM_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclass(slots=True)
class RenderedText:
    text: str
    unresolved: list[str]
    blank_values: list[str]


def placeholders(text: str) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for match in IF_RE.finditer(text or ""):
        key = _split_expression(match.group(1))[0]
        if key not in seen:
            seen.add(key)
            output.append(key)
    for match in PLACEHOLDER_RE.finditer(text or ""):
        key = _split_expression(match.group(1))[0]
        if key not in seen:
            seen.add(key)
            output.append(key)
    return output


def render_text(
    text: str,
    row: Mapping[str, object],
    row_number: int | None = None,
    *,
    escape_values: bool = False,
) -> RenderedText:
    unresolved: list[str] = []
    blank_values: list[str] = []
    special = {
        "_row": "" if row_number is None else str(row_number),
        "_today": date.today().isoformat(),
    }

    def get_value(expression: str, *, for_condition: bool = False) -> tuple[str, str]:
        key, fallback = _split_expression(expression)
        if key in special:
            value = special[key]
        elif key not in row:
            if not for_condition:
                unresolved.append(key)
            return fallback, key
        else:
            value = "" if row[key] is None else str(row[key])
        if not value.strip():
            if fallback:
                value = fallback
            elif not for_condition:
                blank_values.append(key)
        if escape_values and not for_condition:
            value = html.escape(value, quote=True)
        return value, key

    rendered = text or ""
    # Each replacement removes a complete non-nested conditional block, so this
    # loop always makes progress and has no need for an arbitrary block-count cap.
    # Nested conditionals are intentionally outside this tiny template language.
    while True:
        match = IF_RE.search(rendered)
        if not match:
            break
        value, _ = get_value(match.group(1), for_condition=True)
        rendered = rendered[: match.start()] + (match.group(2) if value.strip() else "") + rendered[match.end() :]

    def replace(match: re.Match[str]) -> str:
        key, fallback = _split_expression(match.group(1))
        if key not in special and key not in row and not fallback:
            unresolved.append(key)
            return match.group(0)
        value, _ = get_value(match.group(1))
        return value

    rendered = PLACEHOLDER_RE.sub(replace, rendered)
    return RenderedText(rendered, sorted(set(unresolved)), sorted(set(blank_values)))


def html_to_text(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</div\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).replace("\r\n", "\n").strip()


def split_addresses(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[;,\n]+", value) if part.strip()]


def is_valid_email(address: str) -> bool:
    # MailDesk intentionally accepts only a conservative RFC 5322 dot-atom local
    # part. Display-name forms and quoted local parts are rejected so spreadsheet
    # cells have one unambiguous address representation.
    if not address or any(ch.isspace() for ch in address) or len(address) > 254:
        return False
    _, parsed = parseaddr(address)
    if parsed != address:
        return False
    local, sep, domain = parsed.rpartition("@")
    if not sep or not local or len(local.encode("utf-8")) > 64:
        return False
    if not LOCAL_ATOM_RE.fullmatch(local):
        return False
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        return False
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if len(ascii_domain) > 253:
        return False
    labels = ascii_domain.split(".")
    return all(DOMAIN_LABEL_RE.fullmatch(label) is not None for label in labels)


def _canonical_hash(parts: list[object]) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def message_fingerprint(
    mode: str,
    account: str,
    to: str,
    cc: str,
    bcc: str,
    subject: str,
    body: str,
    body_html: str = "",
    attachments: list[str] | None = None,
) -> str:
    fields = [
        mode,
        account.lower().strip(),
        to.lower().strip(),
        cc.lower().strip(),
        bcc.lower().strip(),
        subject,
        body,
        body_html,
        ",".join(sorted(attachments or [])),
    ]
    if not any("|" in field for field in fields):
        # Preserve the original v0.2 fingerprint byte-for-byte for the common case
        # so successful operations recorded by older builds still prevent duplicate
        # sends after upgrade. Only historically ambiguous delimiter-containing
        # messages move to the versioned, length-aware encoding below.
        return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()
    encoded = "v2:" + json.dumps(fields, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def batch_fingerprint(messages: list[Mapping[str, object]]) -> str:
    parts: list[str] = []
    for item in messages:
        existing = str(item.get("fingerprint") or "")
        if existing:
            parts.append(existing)
            continue
        parts.append(
            _canonical_hash(
                [
                    str(item.get("row_number", "")),
                    str(item.get("to", "")).lower().strip(),
                    str(item.get("cc", "")).lower().strip(),
                    str(item.get("bcc", "")).lower().strip(),
                    str(item.get("subject", "")),
                    str(item.get("body", "")),
                    str(item.get("body_html", "")),
                    sorted(str(x) for x in (item.get("attachments") or [])),
                ]
            )
        )
    return _canonical_hash(parts)


def _split_expression(expression: str) -> tuple[str, str]:
    raw = expression.strip()
    if "|" not in raw:
        return raw, ""
    key, fallback = raw.split("|", 1)
    return key.strip(), fallback
