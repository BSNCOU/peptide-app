"""qa.py — Vendor Qualification & QC blueprint for The Peptide Wizard.

Phase 1A — vendor CRUD + status history. Questionnaire upload + AI scoring
land in Phase 1B (separate PR).

Isolation rules:
  - Mounted at /admin/qa/ — staff-only via existing @admin_required
  - All DB tables prefixed `qa_` (qa_vendors, qa_vendor_status_history)
  - Customer-facing routes are NOT touched — this module only adds new endpoints
  - Feature flag QA_ENABLED env var: when "false", blueprint registration is
    a no-op so the app behaves identically to pre-QA

Disable in production:
    Set QA_ENABLED=false in Railway env vars; redeploy. Routes return 404.
"""

import json
import os
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session

# We import these from app.py at registration time, not at module-load,
# to avoid circular imports. See register_qa_blueprint() at bottom.
_get_db = None
_admin_required = None
_is_postgres = None
_send_email = None


# ── Phase 1B: Vendor Qualification Questionnaire (VQQ) ─────────────────────

VQQ_QUESTIONS = [
    ("manufacturer_or_trading", "Are you a manufacturer with your own production facility, or a trading company? If trading, who is your primary manufacturer?"),
    ("gmp_certifications", "What GMP / cGMP / ISO certifications do you currently hold? Please provide cert numbers and issuing bodies. Attach copies if possible."),
    ("qa_qc_capabilities", "Describe your in-house QA / QC department. How many staff, what are their qualifications?"),
    ("analytical_equipment", "What analytical equipment do you have in-house? (HPLC, LC-MS, ICP-MS, Karl Fischer, GC, NMR, etc.) Please list each and its age."),
    ("years_producing_peptides", "How many years has your company been producing peptides specifically (not general fine chemicals)?"),
    ("export_history", "Which countries have you exported peptides to? Approximately how many international customers are you currently serving?"),
    ("purification_methods", "What purification methods do you use? (Prep HPLC, ion exchange, lyophilization, etc.) What purity grades can you guarantee?"),
    ("endotoxin_controls", "What endotoxin control measures are in place during synthesis and purification? What testing method do you use? (LAL, rFC, etc.)"),
    ("residual_solvent_controls", "How do you control and verify residual solvents? Provide typical levels for acetonitrile, DMF, methanol, DCM in your products."),
    ("batch_traceability", "Describe your batch traceability system. Can you provide a complete chain of custody from raw materials to finished product?"),
    ("stability_testing", "Do you perform stability testing on your peptides? Under what conditions? Can you provide stability data?"),
    ("raw_chromatograms", "Can you provide raw HPLC chromatograms (not just 'conforms' COAs) for every batch?"),
    ("references", "Can you provide references from current customers? Pharmaceutical companies, research labs, etc.? (Names + contact info, with their permission.)"),
]


def build_vqq_email_html(vendor_name, contact_name=None):
    """Render the VQQ as a clean HTML email body."""
    intro = (
        f"<p>Dear {contact_name or vendor_name},</p>"
        "<p>Thank you for your interest in becoming a qualified peptide supplier "
        "for The Peptide Wizard (NH Chemicals LLC). To complete the initial "
        "qualification step, please answer the following 13 questions in as much "
        "detail as possible and reply directly to this email.</p>"
        "<p>The responses you provide will determine whether we proceed to the "
        "sample-testing phase. We value detail and verifiability — please attach "
        "supporting documents (cert copies, equipment lists, prior COAs with raw "
        "chromatograms) wherever applicable.</p>"
        "<hr>"
    )
    body = ""
    for i, (key, question) in enumerate(VQQ_QUESTIONS, 1):
        body += f"<p><strong>{i}. {question}</strong><br><em>(Your response here)</em></p>"
    closer = (
        "<hr>"
        "<p>Please reply within 14 days. If we have not received your response by then, "
        "we will follow up once before closing your application.</p>"
        "<p>Best regards,<br>The Peptide Wizard QA Team<br>NH Chemicals LLC</p>"
    )
    return intro + body + closer


SCORING_RUBRIC = [
    ("documentation_quality", 10, "Are answers complete, organized, and supported with attachments where claimed?"),
    ("technical_competency", 10, "Are the answers technically accurate and specific, vs vague generic boilerplate?"),
    ("qa_maturity", 10, "Is there evidence of a real QA function — staff, procedures, training, internal audits?"),
    ("gmp_evidence", 10, "Are GMP/ISO claims backed by verifiable cert numbers + issuing bodies?"),
    ("analytical_capabilities", 10, "Real in-house lab vs sending samples out vs no analytical capability?"),
    ("responsiveness", 10, "If we have email exchange history, how prompt + clear are their replies?"),
    ("traceability_systems", 10, "Can they describe batch chain-of-custody concretely, with batch number examples?"),
    ("consistency_of_answers", 10, "Do answers internally agree? Do any responses contradict each other or their public site?"),
    ("communication_professionalism", 10, "Real contact name + business domain email vs anonymous gmail? Professional tone?"),
    ("export_experience", 10, "Have they actually exported to other countries? Can they name customers/regions?"),
]

SCORE_REDUCTIONS = {
    "reused_coa_formatting": -10,
    "missing_analytical_methods": -10,
    "conforms_only_data": -10,
    "no_raw_chromatograms": -15,
    "broker_indicators": -10,
    "inconsistent_lot_numbering": -10,
    "vague_qa_responses": -10,
}


def score_questionnaire_response(response_text, vendor_name=""):
    """Score a vendor's VQQ response using Claude (via anthropic SDK) or fall
    back to a deterministic rule-of-thumb if Claude isn't available.

    Returns dict with: score (0-100), breakdown, deficiencies, recommended_status, raw_ai_response."""
    try:
        import anthropic
    except ImportError:
        return _fallback_score(response_text)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _fallback_score(response_text)

    # Build scoring prompt
    rubric_text = "\n".join(
        f"  - {cat} (max {pts} pts): {desc}"
        for cat, pts, desc in SCORING_RUBRIC
    )
    redflags_text = "\n".join(f"  - {k}: {v} pts" for k, v in SCORE_REDUCTIONS.items())

    system_prompt = (
        "You are a senior pharmaceutical-quality auditor evaluating a peptide-supplier "
        "questionnaire response. Score it objectively and return STRICT JSON. "
        "Do not invent information; only score what's actually present in the response.\n\n"
        "Scoring rubric (0-100 total across 10 categories, 10 points each):\n"
        f"{rubric_text}\n\n"
        "Auto-deductions if any red flags are clearly present:\n"
        f"{redflags_text}\n\n"
        "Output STRICT JSON with this exact shape:\n"
        "{\n"
        '  "score": <int 0-100>,\n'
        '  "breakdown": {<category_key>: <int 0-10>, ...},\n'
        '  "deductions_applied": [{"flag": <str>, "points": <int>, "reason": <str>}],\n'
        '  "deficiencies": [<short string of what they need to fix or clarify>, ...],\n'
        '  "strengths": [<short string>, ...],\n'
        '  "recommended_status": <"REJECTED" | "CONDITIONAL_REVIEW" | "APPROVED_FOR_SAMPLE_TESTING">,\n'
        '  "reasoning": <2-3 sentences explaining the overall decision>\n'
        "}\n\n"
        "Status thresholds: <60 = REJECTED, 60-79 = CONDITIONAL_REVIEW, 80+ = APPROVED_FOR_SAMPLE_TESTING."
    )

    user_prompt = (
        f"Vendor: {vendor_name or '(unspecified)'}\n\n"
        f"Their VQQ response (verbatim):\n\n{response_text[:8000]}\n\n"
        "Score this response."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = msg.content[0].text.strip()
        # Strip code-fences if Claude wrapped the JSON
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        result["raw_ai_response"] = text[:3000]
        return result
    except Exception as e:
        fallback = _fallback_score(response_text)
        fallback["raw_ai_response"] = f"AI scoring failed ({e}); used rule-of-thumb fallback."
        return fallback


def _fallback_score(response_text):
    """Deterministic rule-of-thumb score when AI isn't available.
    Just based on response length + keyword presence. NOT a real score —
    intended only so the system doesn't crash when ANTHROPIC_API_KEY missing."""
    text_lower = (response_text or "").lower()
    score = 40
    if len(response_text) > 1000: score += 10
    if len(response_text) > 3000: score += 10
    if "gmp" in text_lower: score += 5
    if "hplc" in text_lower or "lc-ms" in text_lower: score += 5
    if "iso" in text_lower: score += 5
    if "endotoxin" in text_lower: score += 5
    if "chromatogram" in text_lower: score += 5
    if "stability" in text_lower: score += 5
    score = min(score, 100)
    if score < 60:
        rec = "REJECTED"
    elif score < 80:
        rec = "CONDITIONAL_REVIEW"
    else:
        rec = "APPROVED_FOR_SAMPLE_TESTING"
    return {
        "score": score,
        "breakdown": {},
        "deductions_applied": [],
        "deficiencies": ["AI scoring unavailable — manual review recommended."],
        "strengths": [],
        "recommended_status": rec,
        "reasoning": "Fallback heuristic score. Not a substitute for AI or human review.",
    }


# ── Status enum ─────────────────────────────────────────────────────────────

VENDOR_STATUSES = (
    "PROSPECT",
    "QUESTIONNAIRE_SENT",
    "QUESTIONNAIRE_RETURNED",
    "CONDITIONAL_REVIEW",
    "APPROVED_FOR_SAMPLE_TESTING",
    "PENDING_ANALYTICAL_TESTING",
    "ACTIVE_APPROVED_VENDOR",
    "DO_NOT_USE",
    "REJECTED",
    "LEGACY_PRE_QA",  # for vendors back-filled from existing PO supplier_name
)


# ── Schema bootstrap (idempotent) ───────────────────────────────────────────

def init_qa_tables(c, using_postgres, auto_id):
    """Create QA tables if missing. Called from main app's init_db().
    auto_id is the DB-flavor-specific PK type ("INTEGER PRIMARY KEY AUTOINCREMENT"
    on sqlite, "SERIAL PRIMARY KEY" on postgres) per existing app pattern."""
    c.execute(f'''CREATE TABLE IF NOT EXISTS qa_vendors (
        id {auto_id},
        company_name TEXT NOT NULL,
        contact_name TEXT,
        whatsapp_number TEXT,
        whatsapp_normalized TEXT,
        email TEXT,
        website TEXT,
        country TEXT,
        manufacturer_or_trading_company TEXT,
        source_of_lead TEXT,
        status TEXT NOT NULL DEFAULT 'PROSPECT',
        score INTEGER,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )''')

    c.execute(f'''CREATE TABLE IF NOT EXISTS qa_vendor_status_history (
        id {auto_id},
        vendor_id INTEGER NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        changed_by_user_id INTEGER,
        reason TEXT,
        changed_at TEXT NOT NULL
    )''')

    c.execute(f'''CREATE TABLE IF NOT EXISTS qa_vqq_responses (
        id {auto_id},
        vendor_id INTEGER NOT NULL,
        response_text TEXT NOT NULL,
        score INTEGER,
        breakdown_json TEXT,
        deficiencies_json TEXT,
        strengths_json TEXT,
        deductions_json TEXT,
        recommended_status TEXT,
        ai_reasoning TEXT,
        raw_ai_response TEXT,
        scored_at TEXT,
        uploaded_at TEXT NOT NULL,
        uploaded_by_user_id INTEGER
    )''')

    # Phase 2: sample submissions + Purdue work orders
    c.execute(f'''CREATE TABLE IF NOT EXISTS qa_sample_submissions (
        id {auto_id},
        vendor_id INTEGER NOT NULL,
        peptide_name TEXT NOT NULL,
        peptide_sku TEXT,
        lot_number TEXT,
        received_date TEXT NOT NULL,
        storage_location TEXT,
        supplier_coa_path TEXT,
        raw_chromatogram_path TEXT,
        sample_photos_json TEXT,
        notes TEXT,
        status TEXT NOT NULL DEFAULT 'RECEIVED',
        created_at TEXT NOT NULL,
        created_by_user_id INTEGER
    )''')

    c.execute(f'''CREATE TABLE IF NOT EXISTS qa_purdue_work_orders (
        id {auto_id},
        vendor_id INTEGER NOT NULL,
        sample_id INTEGER NOT NULL,
        peptide_name TEXT NOT NULL,
        lot_number TEXT,
        requested_tests_json TEXT,
        acceptance_spec_version TEXT DEFAULT 'v1.0',
        submitted_at TEXT,
        submitted_to_email TEXT DEFAULT 'ngou@purdue.edu',
        status TEXT NOT NULL DEFAULT 'DRAFT',
        results_path TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        created_by_user_id INTEGER
    )''')

    # Phase 3 (2026-06-09): vendor price lists — one upload per row, items per
    # extracted line. Drives PO autofill and cross-vendor price ranking.
    c.execute(f'''CREATE TABLE IF NOT EXISTS qa_vendor_price_lists (
        id {auto_id},
        vendor_id INTEGER NOT NULL,
        effective_date TEXT,                            -- ISO date when this list goes into effect
        source_type TEXT,                               -- 'photo' | 'pdf' | 'text' | 'csv' | 'manual'
        source_filename TEXT,
        source_storage_path TEXT,                       -- relative path under uploads/price_lists/
        notes TEXT,
        raw_extracted_json TEXT,                        -- LLM's raw output, for re-parse if mapping breaks
        status TEXT NOT NULL DEFAULT 'pending',         -- pending | confirmed | rejected | superseded
        created_at TEXT NOT NULL,
        created_by_user_id INTEGER,
        confirmed_at TEXT,
        confirmed_by_user_id INTEGER
    )''')

    c.execute(f'''CREATE TABLE IF NOT EXISTS qa_vendor_price_items (
        id {auto_id},
        price_list_id INTEGER NOT NULL,
        vendor_id INTEGER NOT NULL,                     -- denormalized for fast cross-vendor queries
        raw_name TEXT NOT NULL,                         -- what the vendor called it ("BPC-157 10mg")
        raw_pack_size TEXT,                             -- as parsed text
        pack_size INTEGER,                              -- normalized integer (vials per pack)
        product_id INTEGER,                             -- nullable FK; set when matched
        match_status TEXT NOT NULL DEFAULT 'unmatched', -- unmatched | auto | admin_confirmed | admin_override | new_product
        match_confidence REAL DEFAULT 0,                -- 0..1 from LLM
        unit_cost REAL,                                 -- price per single vial
        pack_cost REAL,                                 -- vendor's quoted price per pack
        currency TEXT DEFAULT 'USD',
        moq INTEGER,                                    -- minimum order quantity if vendor specified
        notes TEXT,
        created_at TEXT NOT NULL
    )''')

    c.execute("CREATE INDEX IF NOT EXISTS idx_qa_vendors_status ON qa_vendors(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qa_vqq_vendor ON qa_vqq_responses(vendor_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qa_status_history_vendor ON qa_vendor_status_history(vendor_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qa_samples_vendor ON qa_sample_submissions(vendor_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qa_work_orders_vendor ON qa_purdue_work_orders(vendor_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qa_price_lists_vendor ON qa_vendor_price_lists(vendor_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qa_price_items_list ON qa_vendor_price_items(price_list_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qa_price_items_lookup ON qa_vendor_price_items(vendor_id, product_id)")
    # Unique index on normalized phone (partial — allows NULL/blank for email-only vendors)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_vendors_whatsapp_unique "
              "ON qa_vendors(whatsapp_normalized) WHERE whatsapp_normalized IS NOT NULL AND whatsapp_normalized != ''")

    # ── 2026-06-14 vendor foundation migrations ──────────────────────────────
    # vendor_type distinguishes suppliers (default) from testing labs so labs
    # can be modeled as vendors without polluting the PO supplier dropdown.
    # phone is a plain contact number distinct from whatsapp; address is needed
    # for shipping samples to testing labs (Feature #4).
    qa_vendor_migrations = [
        ("qa_vendors", "vendor_type TEXT DEFAULT 'supplier'"),
        ("qa_vendors", "phone TEXT"),
        ("qa_vendors", "address TEXT"),
    ]
    for tbl, col_def in qa_vendor_migrations:
        if using_postgres:
            try:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col_def}")
            except Exception as e:
                print(f"Note: {tbl}.{col_def}: {e}")
        else:
            try:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_def}")
            except Exception:
                pass  # already exists
    # Backfill any pre-existing rows that came in as NULL (SQLite ADD COLUMN with
    # DEFAULT backfills, but be explicit so the supplier filter is reliable).
    try:
        c.execute("UPDATE qa_vendors SET vendor_type='supplier' WHERE vendor_type IS NULL OR vendor_type=''")
    except Exception:
        pass


def normalize_phone(raw):
    """Normalize a phone number to digits-only with optional leading +.
    Returns empty string for empty/None input.

    Examples:
      '+86 138-1234-5678'   -> '+8613812345678'
      '(86) 138.1234.5678'  -> '+8613812345678' (assumes country code starts with non-zero)
      '8613812345678'        -> '+8613812345678' (assumes E.164 if 11+ digits)
      '13812345678'          -> '13812345678' (10-11 digit numbers preserved as-is — could be local)
    """
    if not raw:
        return ""
    raw = str(raw).strip()
    # Strip everything that's not a digit or +
    import re as _re
    cleaned = _re.sub(r"[^\d+]", "", raw)
    if not cleaned:
        return ""
    # If starts with 00 (international prefix), replace with +
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    # If looks like an international number (11+ digits, no +) add +
    if not cleaned.startswith("+") and len(cleaned) >= 11:
        cleaned = "+" + cleaned
    return cleaned


# ── Helpers ─────────────────────────────────────────────────────────────────

def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _row_to_dict(row):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def _record_status_change(conn, vendor_id, from_status, to_status, user_id, reason):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO qa_vendor_status_history "
        "(vendor_id, from_status, to_status, changed_by_user_id, reason, changed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (vendor_id, from_status, to_status, user_id, reason or "", _now_iso()),
    )
    conn.commit()


# ── Blueprint ───────────────────────────────────────────────────────────────

qa_bp = Blueprint("qa", __name__, url_prefix="/admin/qa", template_folder="templates")


@qa_bp.route("/", methods=["GET"])
def qa_home():
    """Land at /admin/qa — quick dashboard."""
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    conn = _get_db()
    counts = {}
    cur = conn.cursor()
    for s in VENDOR_STATUSES:
        cur.execute("SELECT COUNT(*) FROM qa_vendors WHERE status=?", (s,))
        row = cur.fetchone()
        counts[s] = (row[0] if not hasattr(row, "keys") else row[0]) or 0
    conn.close()
    return render_template("qa/home.html", counts=counts, statuses=VENDOR_STATUSES)


@qa_bp.route("/vendors", methods=["GET"])
def vendors_list():
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    status_filter = request.args.get("status", "").strip()
    conn = _get_db()
    cur = conn.cursor()
    if status_filter and status_filter in VENDOR_STATUSES:
        cur.execute(
            "SELECT id, company_name, whatsapp_number, country, status, score, updated_at, vendor_type "
            "FROM qa_vendors WHERE status=? ORDER BY updated_at DESC",
            (status_filter,),
        )
    else:
        cur.execute(
            "SELECT id, company_name, whatsapp_number, country, status, score, updated_at, vendor_type "
            "FROM qa_vendors ORDER BY updated_at DESC"
        )
    rows = cur.fetchall()
    conn.close()
    vendors = [_row_to_dict(r) for r in rows]
    return render_template(
        "qa/vendors_list.html",
        vendors=vendors,
        statuses=VENDOR_STATUSES,
        active_filter=status_filter,
    )


@qa_bp.route("/vendors/new", methods=["GET", "POST"])
def vendor_new():
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    if request.method == "GET":
        return render_template("qa/vendor_new.html")

    # POST
    data = request.form if request.form else (request.get_json() or {})
    company_name = (data.get("company_name") or "").strip()
    if not company_name:
        return jsonify({"error": "company_name is required"}), 400

    whatsapp_raw = (data.get("whatsapp_number") or "").strip()
    whatsapp_norm = normalize_phone(whatsapp_raw)

    vendor_type = (data.get("vendor_type") or "supplier").strip().lower()
    if vendor_type not in ("supplier", "testing_lab"):
        vendor_type = "supplier"

    # Pre-check uniqueness so we can give a friendly error before the DB constraint fires
    conn = _get_db()
    cur = conn.cursor()
    if whatsapp_norm:
        cur.execute(
            "SELECT id, company_name FROM qa_vendors WHERE whatsapp_normalized = ?",
            (whatsapp_norm,),
        )
        existing = cur.fetchone()
        if existing:
            existing_dict = _row_to_dict(existing)
            conn.close()
            return jsonify({
                "error": f"A vendor with this phone already exists: "
                         f"#{existing_dict['id']} {existing_dict['company_name']}",
                "existing_vendor_id": existing_dict["id"],
            }), 409

    now = _now_iso()
    cur.execute(
        "INSERT INTO qa_vendors "
        "(company_name, contact_name, whatsapp_number, whatsapp_normalized, phone, address, email, website, country, "
        " manufacturer_or_trading_company, source_of_lead, vendor_type, status, notes, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROSPECT', ?, ?, ?)",
        (
            company_name,
            (data.get("contact_name") or "").strip() or None,
            whatsapp_raw or None,
            whatsapp_norm or None,
            (data.get("phone") or "").strip() or None,
            (data.get("address") or "").strip() or None,
            (data.get("email") or "").strip() or None,
            (data.get("website") or "").strip() or None,
            (data.get("country") or "").strip() or None,
            (data.get("manufacturer_or_trading_company") or "").strip() or None,
            (data.get("source_of_lead") or "").strip() or None,
            vendor_type,
            (data.get("notes") or "").strip() or None,
            now,
            now,
        ),
    )
    conn.commit()

    # Get the new id (sqlite vs postgres)
    new_id = None
    try:
        new_id = cur.lastrowid
    except Exception:
        pass
    if not new_id:
        cur.execute("SELECT id FROM qa_vendors WHERE company_name=? ORDER BY id DESC LIMIT 1", (company_name,))
        r = cur.fetchone()
        new_id = r[0] if r else None

    if new_id:
        _record_status_change(conn, new_id, None, "PROSPECT", session.get("user_id"), "vendor created")
    conn.close()

    if request.is_json:
        return jsonify({"ok": True, "vendor_id": new_id})
    return jsonify({"ok": True, "vendor_id": new_id, "redirect": f"/admin/qa/vendors/{new_id}"})


@qa_bp.route("/vendors/by_phone", methods=["GET"])
def vendor_by_phone():
    """Look up vendor by phone number — handy when you're in WhatsApp and want
    to jump straight to that vendor's record. Accepts any format; normalizes
    internally."""
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    raw = request.args.get("n", "").strip()
    norm = normalize_phone(raw)
    if not norm:
        return jsonify({"error": "Phone number required (?n=<number>)"}), 400
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM qa_vendors WHERE whatsapp_normalized = ?", (norm,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": f"No vendor with phone {norm}", "normalized": norm}), 404
    vid = row[0] if not hasattr(row, "keys") else row["id"]
    if request.is_json:
        return jsonify({"ok": True, "vendor_id": vid, "normalized_phone": norm})
    # Browser request → redirect to vendor detail
    from flask import redirect as _redirect
    return _redirect(f"/admin/qa/vendors/{vid}")


@qa_bp.route("/vendors/<int:vendor_id>", methods=["GET"])
def vendor_detail(vendor_id):
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM qa_vendors WHERE id=?", (vendor_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Vendor not found"}), 404
    vendor = _row_to_dict(row)

    cur.execute(
        "SELECT from_status, to_status, reason, changed_at "
        "FROM qa_vendor_status_history WHERE vendor_id=? ORDER BY id DESC",
        (vendor_id,),
    )
    history = [_row_to_dict(r) for r in cur.fetchall()]

    # Pull latest VQQ response if any
    cur.execute(
        "SELECT id, score, recommended_status, ai_reasoning, deficiencies_json, "
        "strengths_json, breakdown_json, uploaded_at "
        "FROM qa_vqq_responses WHERE vendor_id=? ORDER BY id DESC LIMIT 1",
        (vendor_id,),
    )
    latest_vqq_row = cur.fetchone()
    latest_vqq = None
    if latest_vqq_row:
        latest_vqq = _row_to_dict(latest_vqq_row)
        for k in ("deficiencies_json", "strengths_json", "breakdown_json"):
            try:
                latest_vqq[k.replace("_json", "")] = json.loads(latest_vqq.get(k) or "[]")
            except Exception:
                latest_vqq[k.replace("_json", "")] = []

    # Phase 2: pull samples for this vendor
    cur.execute(
        "SELECT id, peptide_name, peptide_sku, lot_number, received_date, status, created_at "
        "FROM qa_sample_submissions WHERE vendor_id=? ORDER BY id DESC",
        (vendor_id,),
    )
    samples = [_row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return render_template(
        "qa/vendor_detail.html",
        vendor=vendor,
        history=history,
        statuses=VENDOR_STATUSES,
        latest_vqq=latest_vqq,
        samples=samples,
    )


@qa_bp.route("/vendors/<int:vendor_id>/edit", methods=["GET", "POST"])
def vendor_edit(vendor_id):
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM qa_vendors WHERE id=?", (vendor_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Vendor not found"}), 404
    vendor = _row_to_dict(row)

    if request.method == "GET":
        conn.close()
        return render_template("qa/vendor_edit.html", vendor=vendor)

    # POST — update editable fields
    data = request.form if request.form else (request.get_json() or {})
    company_name = (data.get("company_name") or "").strip()
    if not company_name:
        conn.close()
        return jsonify({"error": "company_name is required"}), 400

    whatsapp_raw = (data.get("whatsapp_number") or "").strip()
    whatsapp_norm = normalize_phone(whatsapp_raw)
    vendor_type = (data.get("vendor_type") or vendor.get("vendor_type") or "supplier").strip().lower()
    if vendor_type not in ("supplier", "testing_lab"):
        vendor_type = "supplier"

    # If the phone changed, make sure it doesn't collide with a different vendor
    if whatsapp_norm and whatsapp_norm != (vendor.get("whatsapp_normalized") or ""):
        cur.execute(
            "SELECT id, company_name FROM qa_vendors WHERE whatsapp_normalized=? AND id<>?",
            (whatsapp_norm, vendor_id),
        )
        clash = cur.fetchone()
        if clash:
            clash_d = _row_to_dict(clash)
            conn.close()
            return jsonify({
                "error": f"Another vendor already uses this phone: "
                         f"#{clash_d['id']} {clash_d['company_name']}",
            }), 409

    cur.execute(
        "UPDATE qa_vendors SET company_name=?, contact_name=?, whatsapp_number=?, whatsapp_normalized=?, "
        "phone=?, address=?, email=?, website=?, country=?, manufacturer_or_trading_company=?, "
        "source_of_lead=?, vendor_type=?, notes=?, updated_at=? WHERE id=?",
        (
            company_name,
            (data.get("contact_name") or "").strip() or None,
            whatsapp_raw or None,
            whatsapp_norm or None,
            (data.get("phone") or "").strip() or None,
            (data.get("address") or "").strip() or None,
            (data.get("email") or "").strip() or None,
            (data.get("website") or "").strip() or None,
            (data.get("country") or "").strip() or None,
            (data.get("manufacturer_or_trading_company") or "").strip() or None,
            (data.get("source_of_lead") or "").strip() or None,
            vendor_type,
            (data.get("notes") or "").strip() or None,
            _now_iso(),
            vendor_id,
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "vendor_id": vendor_id, "redirect": f"/admin/qa/vendors/{vendor_id}"})


@qa_bp.route("/vendors/<int:vendor_id>/delete", methods=["POST"])
def vendor_delete(vendor_id):
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, company_name FROM qa_vendors WHERE id=?", (vendor_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Vendor not found"}), 404

    # Refuse to delete a vendor that's referenced elsewhere — would orphan POs,
    # samples, or price lists. Each lookup is guarded in case a table is absent.
    blockers = []
    for label, sql in (
        ("purchase order(s)", "SELECT COUNT(*) FROM purchase_orders WHERE vendor_id=?"),
        ("sample(s)", "SELECT COUNT(*) FROM qa_sample_submissions WHERE vendor_id=?"),
        ("price list(s)", "SELECT COUNT(*) FROM qa_vendor_price_lists WHERE vendor_id=?"),
    ):
        try:
            cur.execute(sql, (vendor_id,))
            r = cur.fetchone()
            n = (r[0] if not hasattr(r, "keys") else r[0]) or 0
            if n:
                blockers.append(f"{n} {label}")
        except Exception:
            pass  # table may not exist yet on this DB
    if blockers:
        conn.close()
        return jsonify({
            "error": "Can't delete — this vendor is still referenced by "
                     + ", ".join(blockers)
                     + ". Reassign or remove those first.",
        }), 409

    cur.execute("DELETE FROM qa_vendor_status_history WHERE vendor_id=?", (vendor_id,))
    cur.execute("DELETE FROM qa_vendors WHERE id=?", (vendor_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "redirect": "/admin/qa/vendors"})


@qa_bp.route("/vendors/<int:vendor_id>/send_vqq", methods=["POST"])
def vendor_send_vqq(vendor_id):
    """Send the VQQ to the vendor via email and transition status to QUESTIONNAIRE_SENT."""
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403

    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM qa_vendors WHERE id=?", (vendor_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Vendor not found"}), 404
    vendor = _row_to_dict(row)

    if not vendor.get("email"):
        conn.close()
        return jsonify({"error": "Vendor has no email on file. Add an email first."}), 400

    html = build_vqq_email_html(vendor["company_name"], vendor.get("contact_name"))
    subject = f"Peptide Supplier Qualification Questionnaire — The Peptide Wizard"

    # Use the app's existing send_email function (Mailgun pipe)
    try:
        if _send_email is None:
            conn.close()
            return jsonify({"error": "Email integration not wired up"}), 500
        _send_email(vendor["email"], subject, html)
    except Exception as e:
        conn.close()
        return jsonify({"error": f"Email send failed: {e}"}), 500

    # Transition status
    old_status = vendor["status"]
    new_status = "QUESTIONNAIRE_SENT"
    cur.execute(
        "UPDATE qa_vendors SET status=?, updated_at=? WHERE id=?",
        (new_status, _now_iso(), vendor_id),
    )
    conn.commit()
    _record_status_change(conn, vendor_id, old_status, new_status, session.get("user_id"), "VQQ emailed")
    conn.close()

    if request.is_json:
        return jsonify({"ok": True, "sent_to": vendor["email"], "new_status": new_status})
    return jsonify({"ok": True, "sent_to": vendor["email"], "new_status": new_status,
                    "redirect": f"/admin/qa/vendors/{vendor_id}"})


@qa_bp.route("/vendors/<int:vendor_id>/upload_response", methods=["POST"])
def vendor_upload_response(vendor_id):
    """Accept a pasted text response to the VQQ, store it, score via AI,
    and transition status based on score."""
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403

    data = request.form if request.form else (request.get_json() or {})
    response_text = (data.get("response_text") or "").strip()
    if len(response_text) < 100:
        return jsonify({"error": "Response too short — paste the full questionnaire reply."}), 400

    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM qa_vendors WHERE id=?", (vendor_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Vendor not found"}), 404
    vendor = _row_to_dict(row)

    # Run AI scoring
    score_result = score_questionnaire_response(response_text, vendor["company_name"])

    now = _now_iso()
    cur.execute(
        "INSERT INTO qa_vqq_responses "
        "(vendor_id, response_text, score, breakdown_json, deficiencies_json, strengths_json, "
        " deductions_json, recommended_status, ai_reasoning, raw_ai_response, "
        " scored_at, uploaded_at, uploaded_by_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            vendor_id,
            response_text,
            score_result.get("score"),
            json.dumps(score_result.get("breakdown", {})),
            json.dumps(score_result.get("deficiencies", [])),
            json.dumps(score_result.get("strengths", [])),
            json.dumps(score_result.get("deductions_applied", [])),
            score_result.get("recommended_status"),
            score_result.get("reasoning", ""),
            score_result.get("raw_ai_response", "")[:5000],
            now,
            now,
            session.get("user_id"),
        ),
    )
    conn.commit()

    # Transition status: QUESTIONNAIRE_RETURNED first (always), then maybe further based on score
    old_status = vendor["status"]
    cur.execute(
        "UPDATE qa_vendors SET status=?, score=?, updated_at=? WHERE id=?",
        ("QUESTIONNAIRE_RETURNED", score_result.get("score"), now, vendor_id),
    )
    conn.commit()
    _record_status_change(conn, vendor_id, old_status, "QUESTIONNAIRE_RETURNED",
                          session.get("user_id"), f"VQQ response uploaded; AI score = {score_result.get('score')}")

    # Don't auto-advance past QUESTIONNAIRE_RETURNED — let Ben review the AI score first
    # He can manually move to CONDITIONAL_REVIEW or APPROVED_FOR_SAMPLE_TESTING
    conn.close()

    return jsonify({
        "ok": True,
        "score": score_result.get("score"),
        "recommended_status": score_result.get("recommended_status"),
        "deficiencies": score_result.get("deficiencies", []),
        "strengths": score_result.get("strengths", []),
        "reasoning": score_result.get("reasoning", ""),
        "redirect": f"/admin/qa/vendors/{vendor_id}",
    })


REQUIRED_PURDUE_TESTS = [
    "LC-MS / HRMS identity confirmation",
    "HPLC / UPLC purity",
    "Peptide assay / content",
    "Endotoxins (LAL or rFC)",
    "Residual solvents (acetonitrile, DMF, methanol, DCM)",
    "Microbial testing (E. coli, Salmonella, Staph aureus)",
    "Heavy metals via ICP-MS (Pb, As, Cd, Hg per USP <232>)",
    "Water content via Karl Fischer",
]

ACCEPTANCE_SPEC_V1 = {
    "purity": {"premium": ">=99%", "minimum": ">=98%",
               "reject": "unknown impurity >1% OR total impurities >2%"},
    "assay": "90-110% of labeled claim",
    "water_content": {"preferred": "<=5%", "maximum": "<=8%"},
    "residual_solvents": {
        "acetonitrile": "<410 ppm", "DMF": "<880 ppm",
        "methanol": "<3000 ppm", "DCM": "ND preferred"
    },
    "endotoxins": {"preferred": "<5 EU/mg", "maximum": "<10 EU/mg"},
    "heavy_metals": "USP <232> aligned low ppm (Pb, As, Cd, Hg)",
    "microbial": "E. coli absent, Salmonella absent, Staph aureus absent",
    "identity": "MW within tolerance; no unexpected dominant peaks",
}


def _lookup_peptide_in_products(peptide_name):
    """Cross-check the peptide name against the existing products SKU catalog.
    Returns (matched, suggestion). matched=True if a clean SKU match exists."""
    if not peptide_name:
        return False, None
    try:
        conn = _get_db()
        cur = conn.cursor()
        # Try exact-ish match: case-insensitive substring on product name
        cur.execute(
            "SELECT sku, name FROM products WHERE LOWER(name) LIKE LOWER(?) LIMIT 5",
            (f"%{peptide_name.strip()}%",),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return False, None
        # Take the first match
        r0 = _row_to_dict(rows[0])
        return True, r0
    except Exception:
        return False, None


@qa_bp.route("/vendors/<int:vendor_id>/samples/new", methods=["POST"])
def sample_new(vendor_id):
    """Log an incoming sample from an approved vendor."""
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    data = request.form if request.form else (request.get_json() or {})
    peptide_name = (data.get("peptide_name") or "").strip()
    if not peptide_name:
        return jsonify({"error": "peptide_name is required"}), 400

    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, status FROM qa_vendors WHERE id=?", (vendor_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Vendor not found"}), 404
    vendor_row = _row_to_dict(row)
    if vendor_row["status"] not in ("APPROVED_FOR_SAMPLE_TESTING", "PENDING_ANALYTICAL_TESTING"):
        conn.close()
        return jsonify({"error": f"Vendor must be APPROVED_FOR_SAMPLE_TESTING. Current: {vendor_row['status']}"}), 400

    # Cross-check the peptide name against our products catalog
    matched, suggestion = _lookup_peptide_in_products(peptide_name)
    peptide_sku = suggestion["sku"] if matched else None

    now = _now_iso()
    cur.execute(
        "INSERT INTO qa_sample_submissions "
        "(vendor_id, peptide_name, peptide_sku, lot_number, received_date, storage_location, "
        " notes, status, created_at, created_by_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'RECEIVED', ?, ?)",
        (
            vendor_id,
            peptide_name,
            peptide_sku,
            (data.get("lot_number") or "").strip() or None,
            (data.get("received_date") or datetime.now().strftime("%Y-%m-%d")),
            (data.get("storage_location") or "").strip() or None,
            (data.get("notes") or "").strip() or None,
            now,
            session.get("user_id"),
        ),
    )
    conn.commit()

    new_id = None
    try:
        new_id = cur.lastrowid
    except Exception:
        pass

    # Transition vendor status if it was APPROVED_FOR_SAMPLE_TESTING → PENDING_ANALYTICAL_TESTING
    if vendor_row["status"] == "APPROVED_FOR_SAMPLE_TESTING":
        cur.execute(
            "UPDATE qa_vendors SET status=?, updated_at=? WHERE id=?",
            ("PENDING_ANALYTICAL_TESTING", now, vendor_id),
        )
        conn.commit()
        _record_status_change(
            conn, vendor_id, "APPROVED_FOR_SAMPLE_TESTING", "PENDING_ANALYTICAL_TESTING",
            session.get("user_id"), f"Sample received: {peptide_name}"
        )
    conn.close()

    return jsonify({
        "ok": True,
        "sample_id": new_id,
        "peptide_matched_sku": peptide_sku,
        "peptide_match_warning": None if matched else f"'{peptide_name}' did not match any SKU in your products catalog — proceeding anyway, but verify this is a peptide you sell.",
        "redirect": f"/admin/qa/vendors/{vendor_id}",
    })


@qa_bp.route("/samples/<int:sample_id>", methods=["GET"])
def sample_detail(sample_id):
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM qa_sample_submissions WHERE id=?", (sample_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Sample not found"}), 404
    sample = _row_to_dict(row)
    cur.execute("SELECT * FROM qa_vendors WHERE id=?", (sample["vendor_id"],))
    vendor = _row_to_dict(cur.fetchone())
    cur.execute("SELECT * FROM qa_purdue_work_orders WHERE sample_id=? ORDER BY id DESC", (sample_id,))
    work_orders = [_row_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return render_template("qa/sample_detail.html",
                            sample=sample, vendor=vendor, work_orders=work_orders,
                            required_tests=REQUIRED_PURDUE_TESTS,
                            acceptance_spec=ACCEPTANCE_SPEC_V1)


@qa_bp.route("/samples/<int:sample_id>/generate_work_order", methods=["POST"])
def sample_generate_work_order(sample_id):
    """Generate a Purdue work order PDF + email it to ngou@purdue.edu."""
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM qa_sample_submissions WHERE id=?", (sample_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Sample not found"}), 404
    sample = _row_to_dict(row)
    cur.execute("SELECT * FROM qa_vendors WHERE id=?", (sample["vendor_id"],))
    vendor = _row_to_dict(cur.fetchone())

    # Create the work order record
    now = _now_iso()
    cur.execute(
        "INSERT INTO qa_purdue_work_orders "
        "(vendor_id, sample_id, peptide_name, lot_number, requested_tests_json, "
        " acceptance_spec_version, status, created_at, created_by_user_id) "
        "VALUES (?, ?, ?, ?, ?, 'v1.0', 'DRAFT', ?, ?)",
        (
            vendor["id"], sample["id"], sample["peptide_name"], sample.get("lot_number"),
            json.dumps(REQUIRED_PURDUE_TESTS), now, session.get("user_id"),
        ),
    )
    conn.commit()
    work_order_id = cur.lastrowid

    # Generate PDF
    pdf_bytes = _generate_work_order_pdf(work_order_id, vendor, sample)

    # Email to ngou@purdue.edu (if Mailgun configured) with PDF attached
    email_sent = False
    try:
        if _send_email:
            html = (
                f"<p>Dear Purdue Analytical Team,</p>"
                f"<p>Attached is Work Order #{work_order_id} for analytical testing of "
                f"a peptide sample from our supplier qualification program.</p>"
                f"<p><strong>Sample:</strong> {sample['peptide_name']}"
                f"{' (lot ' + sample['lot_number'] + ')' if sample.get('lot_number') else ''}<br>"
                f"<strong>Vendor:</strong> {vendor['company_name']}<br>"
                f"<strong>Tests requested:</strong> Full panel (see PDF for spec)</p>"
                f"<p>Please reply with results when complete. Acceptance specifications "
                f"are included in the PDF.</p>"
                f"<p>Best regards,<br>The Peptide Wizard QA<br>NH Chemicals LLC</p>"
            )
            # Note: existing send_email doesn't support attachments — would need to extend it.
            # For now: send the email with details, ship the PDF separately if needed.
            _send_email("ngou@purdue.edu",
                        f"Work Order #{work_order_id} — {sample['peptide_name']}",
                        html)
            email_sent = True
            cur.execute(
                "UPDATE qa_purdue_work_orders SET status='SUBMITTED', submitted_at=? WHERE id=?",
                (now, work_order_id),
            )
            conn.commit()
    except Exception as e:
        # Don't fail the request — work order is created, just note email failure
        cur.execute("UPDATE qa_purdue_work_orders SET notes=? WHERE id=?",
                    (f"Email send failed: {e}", work_order_id))
        conn.commit()

    conn.close()

    # Return the PDF as a download
    if request.args.get("format") == "pdf" or not email_sent:
        from flask import Response
        return Response(pdf_bytes, mimetype="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=work_order_{work_order_id}.pdf"})

    return jsonify({
        "ok": True,
        "work_order_id": work_order_id,
        "email_sent_to": "ngou@purdue.edu" if email_sent else None,
        "pdf_url": f"/admin/qa/work_orders/{work_order_id}/pdf",
        "redirect": f"/admin/qa/samples/{sample_id}",
    })


def _generate_work_order_pdf(work_order_id, vendor, sample):
    """Generate the Purdue work order PDF using reportlab."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
    except ImportError:
        # Fallback to plain text if reportlab unavailable
        text = _generate_work_order_text(work_order_id, vendor, sample)
        return text.encode()

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], fontSize=18, spaceAfter=12)
    h2_style = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceAfter=8, spaceBefore=16)
    body = styles["BodyText"]

    story = []
    story.append(Paragraph(f"PURDUE ANALYTICAL WORK ORDER #{work_order_id}", title_style))
    story.append(Paragraph(f"<i>Issued by The Peptide Wizard / NH Chemicals LLC — {datetime.now().strftime('%B %d, %Y')}</i>", body))
    story.append(Spacer(1, 12))

    # Vendor + sample info
    story.append(Paragraph("Sample Information", h2_style))
    info_data = [
        ["Vendor", vendor["company_name"]],
        ["Vendor country", vendor.get("country") or "—"],
        ["Peptide", sample["peptide_name"]],
        ["Internal SKU match", sample.get("peptide_sku") or "(no SKU match found — verify)"],
        ["Lot number", sample.get("lot_number") or "—"],
        ["Received date", sample.get("received_date") or "—"],
        ["Storage", sample.get("storage_location") or "—"],
    ]
    t = Table(info_data, colWidths=[1.8*inch, 4.5*inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("TEXTCOLOR", (0,0), (0,-1), colors.grey),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(t)

    # Required tests
    story.append(Paragraph("Required Analytical Tests", h2_style))
    for i, test in enumerate(REQUIRED_PURDUE_TESTS, 1):
        story.append(Paragraph(f"{i}. {test}", body))

    # Acceptance specifications
    story.append(Paragraph("Acceptance Specifications (v1.0)", h2_style))
    spec_lines = []
    spec_lines.append(f"<b>Identity:</b> {ACCEPTANCE_SPEC_V1['identity']}")
    spec_lines.append(f"<b>Purity:</b> premium {ACCEPTANCE_SPEC_V1['purity']['premium']}; minimum {ACCEPTANCE_SPEC_V1['purity']['minimum']}; reject if {ACCEPTANCE_SPEC_V1['purity']['reject']}")
    spec_lines.append(f"<b>Assay:</b> {ACCEPTANCE_SPEC_V1['assay']}")
    spec_lines.append(f"<b>Water content:</b> preferred {ACCEPTANCE_SPEC_V1['water_content']['preferred']}, max {ACCEPTANCE_SPEC_V1['water_content']['maximum']}")
    spec_lines.append(f"<b>Residual solvents:</b> acetonitrile {ACCEPTANCE_SPEC_V1['residual_solvents']['acetonitrile']}, DMF {ACCEPTANCE_SPEC_V1['residual_solvents']['DMF']}, methanol {ACCEPTANCE_SPEC_V1['residual_solvents']['methanol']}, DCM {ACCEPTANCE_SPEC_V1['residual_solvents']['DCM']}")
    spec_lines.append(f"<b>Endotoxins:</b> preferred {ACCEPTANCE_SPEC_V1['endotoxins']['preferred']}, max {ACCEPTANCE_SPEC_V1['endotoxins']['maximum']}")
    spec_lines.append(f"<b>Heavy metals:</b> {ACCEPTANCE_SPEC_V1['heavy_metals']}")
    spec_lines.append(f"<b>Microbial:</b> {ACCEPTANCE_SPEC_V1['microbial']}")
    for line in spec_lines:
        story.append(Paragraph(line, body))
        story.append(Spacer(1, 4))

    # Required deliverables
    story.append(Paragraph("Required Deliverables From Purdue", h2_style))
    deliverables = [
        "Raw HPLC / UPLC chromatograms (not just COA summary)",
        "LC-MS / HRMS spectra",
        "Actual ppm values for residual solvents (numerical, not 'conforms')",
        "Actual EU/mg values for endotoxin (numerical)",
        "Heavy metals concentrations per element",
        "Microbial test results (count or absent/present per pathogen)",
        "Karl Fischer water content (% w/w)",
        "Full PDF analytical report with signature + date",
    ]
    for d in deliverables:
        story.append(Paragraph(f"• {d}", body))

    story.append(Spacer(1, 20))
    story.append(Paragraph("<i>Please reply to this work order with results. Questions: contact admin@thepeptidewizard.com.</i>", body))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


def _generate_work_order_text(work_order_id, vendor, sample):
    """Plain-text fallback when reportlab isn't available."""
    lines = [
        f"PURDUE ANALYTICAL WORK ORDER #{work_order_id}",
        f"Issued by The Peptide Wizard / NH Chemicals LLC",
        f"Date: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "SAMPLE INFO",
        f"  Vendor: {vendor['company_name']} ({vendor.get('country') or '?'})",
        f"  Peptide: {sample['peptide_name']}",
        f"  SKU: {sample.get('peptide_sku') or '(no match — verify)'}",
        f"  Lot: {sample.get('lot_number') or '—'}",
        f"  Received: {sample.get('received_date') or '—'}",
        "",
        "REQUIRED TESTS",
    ]
    for i, t in enumerate(REQUIRED_PURDUE_TESTS, 1):
        lines.append(f"  {i}. {t}")
    lines.append("")
    lines.append("ACCEPTANCE SPECS (v1.0)")
    lines.append(json.dumps(ACCEPTANCE_SPEC_V1, indent=2))
    return "\n".join(lines)


@qa_bp.route("/work_orders/<int:work_order_id>/pdf", methods=["GET"])
def work_order_pdf(work_order_id):
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM qa_purdue_work_orders WHERE id=?", (work_order_id,))
    wo = _row_to_dict(cur.fetchone())
    if not wo:
        conn.close()
        return jsonify({"error": "Work order not found"}), 404
    cur.execute("SELECT * FROM qa_sample_submissions WHERE id=?", (wo["sample_id"],))
    sample = _row_to_dict(cur.fetchone())
    cur.execute("SELECT * FROM qa_vendors WHERE id=?", (wo["vendor_id"],))
    vendor = _row_to_dict(cur.fetchone())
    conn.close()
    pdf = _generate_work_order_pdf(work_order_id, vendor, sample)
    from flask import Response
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=work_order_{work_order_id}.pdf"})


@qa_bp.route("/vendors/<int:vendor_id>/status", methods=["POST"])
def vendor_status_change(vendor_id):
    if not _is_logged_in_admin():
        return jsonify({"error": "Admin access required"}), 403
    data = request.form if request.form else (request.get_json() or {})
    new_status = (data.get("status") or "").strip().upper()
    reason = (data.get("reason") or "").strip()
    if new_status not in VENDOR_STATUSES:
        return jsonify({"error": f"Invalid status. Must be one of: {', '.join(VENDOR_STATUSES)}"}), 400
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM qa_vendors WHERE id=?", (vendor_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Vendor not found"}), 404
    old_status = row[0] if not hasattr(row, "keys") else row["status"]
    cur.execute(
        "UPDATE qa_vendors SET status=?, updated_at=? WHERE id=?",
        (new_status, _now_iso(), vendor_id),
    )
    conn.commit()
    _record_status_change(conn, vendor_id, old_status, new_status, session.get("user_id"), reason)
    conn.close()
    if request.is_json:
        return jsonify({"ok": True, "from": old_status, "to": new_status})
    return jsonify({"ok": True, "from": old_status, "to": new_status,
                    "redirect": f"/admin/qa/vendors/{vendor_id}"})


# ── Auth helper (uses app.session) ───────────────────────────────────────────

def _is_logged_in_admin():
    """Check session has user_id AND that user has is_admin=1.
    We don't reuse the @admin_required decorator because it returns JSON
    errors; we want HTML pages to redirect to login. Same logic, different shape."""
    if "user_id" not in session:
        return False
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT is_admin FROM users WHERE id=?", (session["user_id"],))
    r = cur.fetchone()
    conn.close()
    if not r:
        return False
    return bool(r[0] if not hasattr(r, "keys") else r["is_admin"])


# ── Registration entry point ────────────────────────────────────────────────

def register_qa_blueprint(flask_app, get_db_fn, admin_required_decorator, is_postgres_fn, send_email_fn=None):
    """Called from app.py to wire up the blueprint.
    Idempotent — safe to call multiple times if app reloads.

    Honors QA_ENABLED env var: if set to "false" (case-insensitive), the
    blueprint is NOT registered. Routes will 404. Default = enabled.
    """
    global _get_db, _admin_required, _is_postgres, _send_email
    _get_db = get_db_fn
    _admin_required = admin_required_decorator
    _is_postgres = is_postgres_fn
    _send_email = send_email_fn

    qa_enabled = os.environ.get("QA_ENABLED", "true").strip().lower() != "false"
    if not qa_enabled:
        flask_app.logger.info("[QA] QA_ENABLED=false, blueprint not registered")
        return False
    flask_app.register_blueprint(qa_bp)
    flask_app.logger.info("[QA] Vendor QA blueprint registered at /admin/qa")
    return True
