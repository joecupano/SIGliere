"""Parsing and search over the SigID (sigidwiki) metadata mirror.

The mirror stores one JSON per wiki page, each carrying MediaWiki `wikitext`.
Real signal pages carry a structured infobox:
  {{Unidentified Signal |Frequencies=6115 kHz |Mode=AM |Modulation=8PSK ...}}
Many pages are #REDIRECT stubs and are skipped.
"""

import glob
import json
import os
import re
from typing import Optional

MAX_RESULTS = 50

# Infobox fields we lift out of the wikitext.
_FIELD_KEYS = ["Title", "Frequencies", "Mode", "Modulation", "Bandwidth",
               "Location", "Signal description", "Additional categories"]


def sigid_parse_infobox(wikitext: str) -> dict:
    """Pull |Key=Value pairs out of the {{...Signal...}} infobox. Best-effort:
    the wiki markup is human-entered and irregular, so missing fields are fine."""
    fields = {}
    for key in _FIELD_KEYS:
        # Match |Key = value  up to the next | that begins a field or the }} end.
        m = re.search(r"\|\s*" + re.escape(key) + r"\s*=\s*(.*?)(?=\n\s*\||\}\})",
                      wikitext, re.IGNORECASE | re.DOTALL)
        if m:
            val = m.group(1).strip()
            # Strip simple wiki markup noise.
            val = re.sub(r"\[\[([^\]|]+)\|?[^\]]*\]\]", r"\1", val)  # [[link|txt]]
            val = re.sub(r"'''?", "", val)                            # bold/italic
            if val:
                fields[key] = val
    return fields


def sigid_extract_freqs_hz(freq_str: str) -> list:
    """Best-effort parse of the Frequencies field into Hz values for range
    search. Handles kHz/MHz/GHz; returns [] if nothing parseable."""
    out = []
    if not freq_str:
        return out
    for m in re.finditer(r"([\d.,]+)\s*(k|M|G)?Hz", freq_str, re.IGNORECASE):
        num = m.group(1).replace(",", "")
        try:
            v = float(num)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        mult = {"k": 1e3, "m": 1e6, "g": 1e9, "": 1.0}[unit]
        out.append(v * mult)
    return out


def sigid_load_signals(metadata_dir: str) -> list:
    """Load + parse all non-redirect signal pages into dicts. Returns a
    list of {title, fields, freqs_hz, wikitext}."""
    signals = []
    pattern = os.path.join(metadata_dir, "*.json")
    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        wt = d.get("wikitext", "") or ""
        if wt.strip().upper().startswith("#REDIRECT"):
            continue
        if "Signal" not in wt and "|Frequencies" not in wt:
            # Not a signal infobox page (talk/category/etc.)
            continue
        fields = sigid_parse_infobox(wt)
        title = fields.get("Title") or d.get("title", os.path.basename(path))
        signals.append({
            "title": title,
            "fields": fields,
            "freqs_hz": sigid_extract_freqs_hz(fields.get("Frequencies", "")),
            "wikitext": wt,
        })
    return signals


def sigid_format_signal(sig: dict) -> dict:
    f = sig["fields"]
    return {
        "title": sig["title"],
        "frequencies": f.get("Frequencies"),
        "mode": f.get("Mode"),
        "modulation": f.get("Modulation"),
        "bandwidth": f.get("Bandwidth"),
        "location": f.get("Location"),
        "description": f.get("Signal description"),
    }


def sigid_find_by_name(signals: list, name: str) -> list:
    """Exact title matches first, then case-insensitive substring matches."""
    q = name.strip().lower()
    exact = [s for s in signals if q == s["title"].lower()]
    partial = [s for s in signals if q in s["title"].lower() and s not in exact]
    return (exact + partial)[:MAX_RESULTS]


def sigid_search(
    signals: list,
    keyword: Optional[str] = None,
    near_frequency_hz: Optional[float] = None,
    tolerance_hz: Optional[float] = None,
) -> list:
    """Signals whose text matches keyword and/or that list a frequency near
    near_frequency_hz (default tolerance 100 kHz)."""
    kw = keyword.strip().lower() if keyword else None
    tol = 100_000.0 if tolerance_hz is None else float(tolerance_hz)
    hits = []
    for s in signals:
        if kw:
            hay = " ".join([
                s["fields"].get("Mode", ""), s["fields"].get("Modulation", ""),
                s["fields"].get("Location", ""), s["fields"].get("Signal description", ""),
                s["fields"].get("Additional categories", ""),
            ]).lower()
            if kw not in hay:
                continue
        if near_frequency_hz is not None:
            if not any(abs(f - float(near_frequency_hz)) <= tol for f in s["freqs_hz"]):
                continue
        hits.append(s)
        if len(hits) >= MAX_RESULTS:
            break
    return hits
