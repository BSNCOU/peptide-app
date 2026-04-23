# Shipping Incidents — Deployment & Stephenie Playbook

**Important:** These files include the pickup feature changes you already deployed + the new incidents work. Safe to drop in as-is.

## Deploy Sequence

1. Replace all 4 files, commit, push to GitHub.
2. Railway redeploys; `init_db()` creates the new `shipping_incidents` table automatically.
3. Watch Railway logs for `✓ Shipping incidents table initialized`.

## File Stephenie's Incident (what to do right after deploy)

1. Log into admin → **All Orders** or **Open Orders**
2. Find Stephenie's order (RO-20260410153011-329222)
3. Click **🚨 Incident** button (or open the order and click **🚨 File Incident / Replacement**)
4. Fill in:
   - Type: **📭 Lost in transit**
   - Notes: *"Package stuck in Latham UPS facility since Apr 18; delivery promised Apr 20; no movement 2+ days past due. Customer contacted admin."*
   - Carrier: UPS (auto-detected from `1Z...` tracking)
   - Insurance Provider: **InsureShield (via Pirate Ship)** (pre-selected)
   - ✅ Keep "Issue replacement order now" checked
5. Click **🚨 File Incident**

Result: new replacement order created ($0, same items, inventory auto-deducted), linked to the incident, note added to original order's admin_notes, and Stephenie will see a green "We've got you covered" banner when she opens her order detail.

## File Insurance Claim Through Pirate Ship

Separately, go to Pirate Ship → Stephenie's shipment → click "File Insurance Claim". Upload invoice, customer communication, tracking.

## Update Incident Later (When Claim Processes)

1. Admin → **🚨 Incidents** tab
2. Click **View/Edit** on Stephenie's row
3. Update:
   - Status: "Filed — pending" → later "Paid"
   - Claim Date: today's date
   - Claim Amount: $110.00 (product subtotal)
   - Payout Amount: (fill when received)
4. Save

## What the Incidents Tab Shows

- **4 summary tiles:** Total Incidents, Pending Insurance, Claimed $, Recovered $
- **Table of all incidents:** Date, Order #, Customer, Type, Carrier, Replacement Order (if any), Insurance status, View/Edit

## BAC Water Broken Case (backfill)

Same workflow:
- Type: **💥 Damaged in transit**
- Notes: *"BAC water vial broke in transit. Customer local — ran replacement bottle in person."*
- ❌ **Uncheck** "Issue replacement order" (you already handed one off in person)
- Filed → then go edit it later to mark the Pirate Ship claim paid

## Mobile (`/m`) Support

Every order card now has a 🚨 File Incident button. It uses simple prompts (pick type 1-7, type notes, confirm replacement yes/no). Good for on-the-go but desktop modal is more capable.

## Rollback

Revert commit on GitHub → Railway redeploys. The `shipping_incidents` table stays behind (harmless — ignored by old code).

## What's Not Built (parking lot)

- Email notification to customer when replacement auto-created (currently silent — banner appears on login). Easy to add if you want it.
- Filtering/search on Incidents tab (date range, type filter, carrier filter) — list is chronological for now.
- Auto-reminder to file the insurance claim after N days.
- Linking multiple incidents to the same order (model supports it, UI shows most recent).
