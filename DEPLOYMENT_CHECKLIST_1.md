# Pickup Feature — Deployment Checklist

All 4 files are ready. Deploy in this exact order.

## Files to replace in your repo
- `app.py`
- `templates/index.html`
- `templates/admin.html`
- `templates/mobile_admin.html`

## Before You Push

- [ ] Confirm GitHub Desktop is showing all 4 files as changed. If not — the browser saved them to the wrong folder or with wrong extensions (that recurring issue). Recheck before committing.
- [ ] (Optional) Set these Railway environment variables if you want to override defaults:
  - `PICKUP_CONTACT_EMAIL` — defaults to `info@thepeptidewizard.com`
  - `PICKUP_CONTACT_PHONE` — defaults to none (add your number if you want SMS-to-schedule)

## Deploy Sequence

1. **Commit & push to GitHub.** Railway auto-deploys.
2. **Watch Railway logs.** `init_db()` runs on startup and will add 3 new columns:
   - `orders.pickup_location`
   - `orders.picked_up_at`
   - `discount_codes.allows_pickup`
3. **If migration errors appear** — DM me the error and don't proceed. Otherwise continue.

## Smoke Test (do this yourself before any customer sees it)

### Create a test code
1. Log into admin → Discount Codes → Add New
2. Code: `LOCALTEST`, 10% off, check **🏪 Allow Local Pickup**, save
3. Edit it → verify checkbox is still checked

### Customer flow
1. Log out of admin, log into any regular customer account (or create one)
2. Add any item to cart
3. Open cart → enter code `LOCALTEST` → apply
4. Click Checkout → **pickup block should appear** at top of modal
5. Select "Pick up locally" → shipping address hides, shipping line shows "🏪 PICKUP", total drops
6. Pick Huntertown → place order → pay $1 through Stripe (or use a credit-covered $0 flow)

### Admin flow
1. Back to admin → Open Orders → find the test order
2. **Purple "🏪 Ready for Pickup" button** should be visible (not "Ready to Ship")
3. Click it → confirm → check the test account's inbox for the pickup-ready email
4. Order row should now show "✓ Picked Up" button
5. Click "✓ Picked Up" → status flips to `fulfilled`
6. Check order detail → delivery should say "🏪 Pickup — Huntertown (1414 Simon Rd)"

### Mobile flow
1. Open `/m` on your phone, PIN in
2. Open Orders → test pickup order should show "🏪 HUNTERTOWN" badge and purple "🏪 Ready for Pickup" button
3. Same workflow as desktop

### Security sanity checks
- Try ordering with pickup but no code → backend should reject with "Local pickup requires an eligible discount code"
- Try ordering with pickup using a **non-pickup** code → same rejection
- Orders with `delivery_method='ship'` should behave exactly as before (no regressions)

## When All Green

1. Deactivate `LOCALTEST` (or permanent delete it — never used in real orders)
2. Flip `allows_pickup` ON for the real codes you want (e.g. `LOCAL`, `PICKUP`)
3. Optional: add a line on product pages: *"Local to Ft. Wayne? Use code LOCAL at checkout for free pickup."*

## Rollback Plan

If something goes wrong post-deploy:
- Git revert the commit → Railway redeploys the previous version
- The 3 new DB columns stay behind (harmless — ignored by old code)
- Old code won't see `allows_pickup` — any in-flight pickup orders become "pickup with no eligible code" but will already be in the system; resolve manually via admin
