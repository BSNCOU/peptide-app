"""pw_extract — vendor price-list extraction.

Takes a price list (photo, text, or CSV) plus the active product catalog
and returns a structured list of items. Each item has:
  - raw_name: what the vendor called it
  - pack_size: normalized vials-per-pack integer
  - pack_cost / unit_cost / currency
  - suggested_product_id + suggested_sku + match_confidence
    (LLM's best guess at which of Ben's products this is; admin confirms)

Designed so it never auto-commits matches. The downstream API persists
the extraction but everything sits in `match_status = 'unmatched'` or
`'auto'` until the admin clicks Confirm in the review UI.

Uses Claude (Anthropic) — vision-capable for photos, text-only for
typed lists. Falls back to a deterministic best-effort if no API key.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any


def _model_for(source_type: str) -> str:
    # Sonnet for vision (better at messy WhatsApp photos), Haiku for
    # plain text (cheaper, plenty accurate).
    if source_type in ("photo", "pdf"):
        return "claude-sonnet-4-6"
    return "claude-haiku-4-5-20251001"


def extract_price_list(
    file_bytes: bytes | None,
    source_type: str,
    raw_text: str | None,
    vendor_name: str,
    product_catalog: list[dict],
) -> dict:
    """Extract structured price items.

    source_type: 'photo' | 'pdf' | 'text' | 'csv'
    file_bytes:  for photo/pdf, the raw bytes
    raw_text:    for text/csv, the pasted content
    product_catalog: [{id, sku, name}, ...] — what to match against
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        return _fallback(raw_text or "", "anthropic SDK not installed")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _fallback(raw_text or "", "ANTHROPIC_API_KEY not set")

    catalog_lines = [
        f"  - id={p['id']}  sku={p.get('sku', '?')}  name={(p.get('name') or '')}"
        for p in product_catalog
    ]
    catalog_block = "\n".join(catalog_lines) if catalog_lines else "  (no products in catalog)"

    system_prompt = (
        "You are extracting peptide vendor price-list items. Output STRICT JSON only.\n\n"
        "For each line/row that looks like a peptide product + price, return one entry. "
        "Skip vendor headers, totals, terms-and-conditions text, etc.\n\n"
        "For each entry, also propose a match against the product catalog below. "
        "Match by peptide name + mg strength (e.g. 'BPC-157 10mg' matches the catalog "
        "entry whose name contains 'BPC' and '10mg'). Use suggested_product_id=null when "
        "you genuinely can't find a match — never guess.\n\n"
        f"PRODUCT CATALOG ({len(product_catalog)} entries):\n{catalog_block}\n\n"
        "Output JSON shape:\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        '      "raw_name":           "<vendor text verbatim, e.g. \'BPC-157 10mg\'>",\n'
        '      "raw_pack_size":      "<vendor text, e.g. \'10 vials/box\'>",\n'
        '      "pack_size":          <int, normalized — vials per pack>,\n'
        '      "pack_cost":          <float, vendor price per pack>,\n'
        '      "unit_cost":          <float, pack_cost / pack_size>,\n'
        '      "currency":           "<3-letter code, default USD>",\n'
        '      "moq":                <int or null, minimum order qty>,\n'
        '      "suggested_product_id":  <int or null, from catalog>,\n'
        '      "suggested_sku":         "<sku or null>",\n'
        '      "match_confidence":      <float 0..1>,\n'
        '      "match_reasoning":       "<one short sentence>"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    user_content: list[dict] = []
    if source_type in ("photo", "pdf") and file_bytes:
        media_type = "image/jpeg"
        if source_type == "pdf":
            # PDF passthrough — Claude Sonnet handles application/pdf
            media_type = "application/pdf"
            user_content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(file_bytes).decode("ascii"),
                },
            })
        else:
            # photo: try to sniff content type from the first bytes
            head = file_bytes[:4]
            if head.startswith(b"\x89PNG"):
                media_type = "image/png"
            elif head.startswith(b"\xff\xd8"):
                media_type = "image/jpeg"
            elif head.startswith(b"GIF"):
                media_type = "image/gif"
            elif head.startswith(b"RIFF"):
                media_type = "image/webp"
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(file_bytes).decode("ascii"),
                },
            })
        user_content.append({
            "type": "text",
            "text": (
                f"Vendor: {vendor_name or '(unspecified)'}\n\n"
                "Extract every priced item from this price list. Return the strict JSON only."
            ),
        })
    else:
        # text/csv path
        body = (raw_text or "")[:8000]
        user_content.append({
            "type": "text",
            "text": (
                f"Vendor: {vendor_name or '(unspecified)'}\n\n"
                f"Price list text:\n{body}\n\n"
                "Extract every priced item. Return the strict JSON only."
            ),
        })

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_model_for(source_type),
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = msg.content[0].text.strip()
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        items = parsed.get("items", []) if isinstance(parsed, dict) else []
        # Server-side sanity-clean each item
        items = [_clean_item(it) for it in items if isinstance(it, dict)]
        return {"ok": True, "items": items, "raw_response": raw[:5000], "model": _model_for(source_type)}
    except json.JSONDecodeError as e:
        return {"ok": False, "items": [], "error": f"JSON parse failed: {e}", "raw_response": cleaned[:2000] if 'cleaned' in locals() else ""}
    except Exception as e:
        return {"ok": False, "items": [], "error": str(e)[:300], "raw_response": ""}


def _clean_item(it: dict) -> dict:
    """Coerce LLM output into the shape we persist. Strip nonsense, clamp ranges."""
    def f(key, default=None):
        v = it.get(key)
        if v in ("", None):
            return default
        try:
            return float(v)
        except Exception:
            return default

    def i(key, default=None):
        v = it.get(key)
        if v in ("", None):
            return default
        try:
            return int(round(float(v)))
        except Exception:
            return default

    raw_name = (it.get("raw_name") or "").strip()[:200]
    raw_pack = (it.get("raw_pack_size") or "").strip()[:80]
    pack_size = i("pack_size")
    pack_cost = f("pack_cost")
    unit_cost = f("unit_cost")
    # Derive unit_cost if missing
    if unit_cost is None and pack_cost and pack_size and pack_size > 0:
        unit_cost = round(pack_cost / pack_size, 4)
    currency = (it.get("currency") or "USD").strip().upper()[:3] or "USD"
    moq = i("moq")
    sp_id = i("suggested_product_id")
    sp_sku = (it.get("suggested_sku") or "").strip()[:80] or None
    conf_raw = f("match_confidence", 0.0) or 0.0
    confidence = max(0.0, min(1.0, conf_raw))
    return {
        "raw_name": raw_name,
        "raw_pack_size": raw_pack,
        "pack_size": pack_size,
        "pack_cost": pack_cost,
        "unit_cost": unit_cost,
        "currency": currency,
        "moq": moq,
        "suggested_product_id": sp_id,
        "suggested_sku": sp_sku,
        "match_confidence": confidence,
        "match_reasoning": (it.get("match_reasoning") or "")[:300],
    }


_LINE_PAT = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9\-\s/]+?)\s+"
    r"(?:[\$£€])?\s*(?P<price>\d+(?:\.\d{1,2})?)\s*"
    r"(?:/?\s*(?P<unit>vial|vial[s]?|pack|box|pc[s]?|bottle[s]?))?"
)


def _fallback(text: str, reason: str) -> dict:
    """Deterministic regex fallback so the UI doesn't blow up when the
    LLM is unavailable. Strictly best-effort — extracts (name, price) pairs
    from each line and leaves suggested_product_id null for admin to map."""
    items = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_PAT.search(line)
        if not m:
            continue
        try:
            price = float(m.group("price"))
        except ValueError:
            continue
        items.append({
            "raw_name": (m.group("name") or "").strip()[:200],
            "raw_pack_size": None,
            "pack_size": None,
            "pack_cost": price,
            "unit_cost": None,
            "currency": "USD",
            "moq": None,
            "suggested_product_id": None,
            "suggested_sku": None,
            "match_confidence": 0.0,
            "match_reasoning": "(fallback regex — admin must map)",
        })
    return {
        "ok": False,
        "items": items,
        "raw_response": "",
        "error": reason,
        "model": "fallback",
    }
