"""pw_extract — vendor price-list extraction.

Takes a price list (photo, PDF, text, or CSV) plus the active product catalog
and returns a structured list of items. Each item has:
  - raw_name: what the vendor called it (full peptide name + strength)
  - pack_size: normalized vials-per-pack integer
  - pack_cost / unit_cost / currency
  - suggested_product_id + suggested_sku + match_confidence
    (LLM's best guess at which of Ben's products this is; admin confirms)

Designed so it never auto-commits matches — everything sits in
`match_status = 'unmatched'` or `'auto'` until the admin clicks Confirm.

Large lists (multi-page PDFs, hundreds of rows) are handled by extracting the
PDF *text* (pypdf) and processing it in chunks — one Claude call per chunk —
then combining. A single call can't emit hundreds of items (output-token cap),
so chunking is what makes a 250-row list work. Scanned/image PDFs and photos
fall back to a single Claude *vision* call. No API key => deterministic regex
fallback so the UI never blows up.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Any

# Per-chunk output budget. ~45 catalog-matched items ≈ 6k tokens; 8k leaves room.
_MAX_TOKENS = 8000
# Text chunking target (lines per chunk) for the text/csv path.
_CHUNK_LINES = 50
_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"


def _pdf_pages(file_bytes: bytes) -> list[str] | None:
    """Extract text per page via pypdf. Returns list of page texts, or None if
    pypdf is unavailable or the PDF has no extractable text (scanned image)."""
    try:
        import pypdf  # type: ignore
    except ImportError:
        return None
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception:
        return None
    if not any(p.strip() for p in pages):
        return None  # scanned/image PDF — let the caller use vision
    return pages


def _chunk_lines(text: str, max_lines: int = _CHUNK_LINES) -> list[str]:
    """Split text into chunks of at most max_lines non-empty lines."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    return ["\n".join(lines[i:i + max_lines]) for i in range(0, len(lines), max_lines)]


def _build_system(product_catalog: list[dict]) -> str:
    catalog_lines = [
        f"  - id={p['id']}  sku={p.get('sku', '?')}  name={(p.get('name') or '')}"
        for p in product_catalog
    ]
    catalog_block = "\n".join(catalog_lines) if catalog_lines else "  (no products in catalog)"
    return (
        "You are extracting peptide vendor price-list rows. Output STRICT JSON only.\n\n"
        "For each row that is a product + price, return one entry. Skip header rows, "
        "column titles, totals, and notes/legends.\n\n"
        "IMPORTANT row rules:\n"
        "- Vendor tables often MERGE the product-name cell across several rows. When a "
        "row has no product name, it belongs to the SAME product as the row above — carry "
        "the product name down. The Cat.No prefix (e.g. SM=Semaglutide, TR=Tirzepatide) "
        "marks the product family.\n"
        "- raw_name MUST be the full peptide name + strength (e.g. 'Semaglutide 5mg'), "
        "never just the strength.\n"
        "- If a row shows TWO prices (e.g. 'less than 10 boxes' and 'more than 10 boxes'), "
        "use the FIRST/standard (smaller-quantity) price as pack_cost, and append "
        "'bulk: $<price>' to match_reasoning.\n"
        "- pack_size = vials per pack/kit (e.g. '10vial/kit' => 10).\n\n"
        "For each entry, propose a match against the catalog below by peptide name + mg "
        "strength. Use suggested_product_id=null when you can't find a confident match — "
        "never guess.\n\n"
        f"PRODUCT CATALOG ({len(product_catalog)} entries):\n{catalog_block}\n\n"
        "Output JSON shape:\n"
        '{ "items": [ {\n'
        '  "raw_name": "<full name + strength>",\n'
        '  "raw_pack_size": "<vendor text, e.g. \'10vial/kit\'>",\n'
        '  "pack_size": <int vials per pack>,\n'
        '  "pack_cost": <float, standard price per pack>,\n'
        '  "unit_cost": <float, pack_cost / pack_size>,\n'
        '  "currency": "<3-letter, default USD>",\n'
        '  "moq": <int or null>,\n'
        '  "suggested_product_id": <int or null, from catalog>,\n'
        '  "suggested_sku": "<sku or null>",\n'
        '  "match_confidence": <float 0..1>,\n'
        '  "match_reasoning": "<one short sentence>"\n'
        "} ] }"
    )


def _call_json(client, model: str, system_prompt: str, user_content) -> tuple[list[dict], str | None]:
    """One Claude call returning (items, error)."""
    try:
        msg = client.messages.create(
            model=model, max_tokens=_MAX_TOKENS, system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        items = parsed.get("items", []) if isinstance(parsed, dict) else []
        return [_clean_item(it) for it in items if isinstance(it, dict)], None
    except json.JSONDecodeError as e:
        return [], f"JSON parse failed: {e}"
    except Exception as e:
        return [], str(e)[:200]


def extract_price_list(
    file_bytes: bytes | None,
    source_type: str,
    raw_text: str | None,
    vendor_name: str,
    product_catalog: list[dict],
) -> dict:
    """Extract structured price items.

    source_type: 'photo' | 'pdf' | 'text' | 'csv'
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        return _fallback(raw_text or "", "anthropic SDK not installed")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _fallback(raw_text or "", "ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = _build_system(product_catalog)

    # Decide path: text chunks (preferred, reliable for big lists) vs vision.
    chunks: list[str] = []
    if source_type == "pdf" and file_bytes:
        pages = _pdf_pages(file_bytes)
        if pages:
            chunks = [p for p in pages if p.strip()]
        else:
            return _extract_vision(client, system_prompt, file_bytes, "pdf", vendor_name)
    elif source_type == "photo" and file_bytes:
        return _extract_vision(client, system_prompt, file_bytes, "photo", vendor_name)
    else:
        chunks = _chunk_lines(raw_text or "")

    if not chunks:
        return _fallback(raw_text or "", "no extractable text found")

    all_items: list[dict] = []
    errors: list[str] = []
    last_product = ""
    for idx, chunk in enumerate(chunks):
        hint = ""
        if last_product:
            hint = (f"\nIf the first rows have no product name, they continue the previous "
                    f"product: '{last_product}'. If a row clearly names a new product, use that.")
        user = (f"Vendor: {vendor_name or '(unspecified)'}\n"
                f"Chunk {idx + 1} of {len(chunks)}:{hint}\n\n{chunk}\n\nReturn strict JSON only.")
        items, err = _call_json(client, _HAIKU, system_prompt, user)
        if err:
            errors.append(f"chunk {idx + 1}: {err}")
        if items:
            all_items.extend(items)
            last_product = items[-1].get("raw_name", "") or last_product

    return {
        "ok": bool(all_items),
        "items": all_items,
        "error": ("; ".join(errors) if errors else None),
        "model": _HAIKU,
        "chunks": len(chunks),
    }


def _extract_vision(client, system_prompt: str, file_bytes: bytes, source_type: str,
                    vendor_name: str) -> dict:
    """Single Claude vision call for photos / scanned (no-text) PDFs."""
    if source_type == "pdf":
        media = {"type": "document", "source": {"type": "base64",
                 "media_type": "application/pdf",
                 "data": base64.b64encode(file_bytes).decode("ascii")}}
    else:
        head = file_bytes[:4]
        mt = "image/jpeg"
        if head.startswith(b"\x89PNG"):
            mt = "image/png"
        elif head.startswith(b"GIF"):
            mt = "image/gif"
        elif head.startswith(b"RIFF"):
            mt = "image/webp"
        media = {"type": "image", "source": {"type": "base64", "media_type": mt,
                 "data": base64.b64encode(file_bytes).decode("ascii")}}
    user_content = [media, {"type": "text", "text": (
        f"Vendor: {vendor_name or '(unspecified)'}\n\n"
        "Extract every priced item from this price list. Return strict JSON only.")}]
    items, err = _call_json(client, _SONNET, system_prompt, user_content)
    return {"ok": bool(items), "items": items, "error": err, "model": _SONNET, "chunks": 1}


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
    """Deterministic regex fallback so the UI doesn't blow up when the LLM is
    unavailable. Best-effort (name, price) pairs; admin maps everything."""
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
            "raw_pack_size": None, "pack_size": None,
            "pack_cost": price, "unit_cost": None, "currency": "USD", "moq": None,
            "suggested_product_id": None, "suggested_sku": None,
            "match_confidence": 0.0,
            "match_reasoning": "(fallback regex — admin must map)",
        })
    return {"ok": False, "items": items, "raw_response": "", "error": reason, "model": "fallback"}
