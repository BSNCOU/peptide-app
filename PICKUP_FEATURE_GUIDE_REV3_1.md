# Pickup Feature Implementation Guide (Rev 3 — Final)
## The Peptide Wizard — Local Pickup for Discount Codes

> **What changed in Rev 3:** Rev 2 covered only the backend. Rev 3 adds the frontend, built by reading the actual `index.html` (2,052 lines), `admin.html` (6,525 lines), and `mobile_admin.html` (1,463 lines). All line numbers reference your current files.

---

## What's Already in Your Code ✅

**Backend (`app.py`):**
- ✅ `orders.delivery_method` column (defaults to `'pickup'`)
- ✅ `create_order` accepts `delivery_method` from the client (line 2514)
- ✅ Free-shipping-over-$500 logic
- ✅ `PUT /api/admin/orders/<oid>/delivery-method` admin override (line 4692)
- ✅ Admin new-order email shows pickup vs ship (line 1207)
- ✅ Pirate Ship CSV export filters out pickups (line 5315)

**Admin (`admin.html`):**
- ✅ `isPickupOrder()` helper (line 3870)
- ✅ `markPickedUp()` function (line 4606) — uses generic status endpoint
- ✅ `fixToPickup()` reclassifier (line 4577)
- ✅ Ship vs pickup branching in Open Orders actions (line 3736–3737)
- ✅ Ready to Ship queue filters ship-only (line 4016)

**Mobile (`mobile_admin.html`):**
- ✅ Pickup badge display (line 826)
- ✅ `markPickedUp()` function (line 841)
- ✅ Ship-only filter on Ready to Ship (line 860)

## What We're Adding

- ❌ `discount_codes.allows_pickup` column
- ❌ `orders.pickup_location` column
- ❌ `orders.picked_up_at` timestamp
- ❌ `'ready_for_pickup'` status (intermediate between processing and fulfilled)
- ❌ `/api/validate-discount` returns `allows_pickup`
- ❌ Security check in `create_order`: pickup requires eligible code
- ❌ Persist `pickup_location` at order creation
- ❌ `allows_pickup` in admin discount code CRUD + UI checkbox
- ❌ New admin endpoint: mark ready for pickup (sends customer email)
- ❌ Customer email: "Your order is ready for pickup"
- ❌ Checkout UI: show pickup toggle when code allows, hide shipping address, zero shipping
- ❌ Admin UI: "Ready for Pickup" button, location badges, detail view

---

# PART A — `app.py` Changes

## Step 1 — Database Migrations

Your `init_db()` already has migration blocks at lines 506–559. Add these to the matching spots:

**Postgres block (add after line 559):**
```python
# Pickup feature columns
c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_location TEXT")
c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS picked_up_at TIMESTAMP")
c.execute("ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS allows_pickup INTEGER DEFAULT 0")
```

**SQLite block (add after line 553, inside the existing try/except pattern):**
```python
try:
    c.execute("ALTER TABLE orders ADD COLUMN pickup_location TEXT")
except:
    pass
try:
    c.execute("ALTER TABLE orders ADD COLUMN picked_up_at TIMESTAMP")
except:
    pass
try:
    c.execute("ALTER TABLE discount_codes ADD COLUMN allows_pickup INTEGER DEFAULT 0")
except:
    pass
```

---

## Step 2 — Pickup Config Constants

Add near the top of the file, by your other `CONFIG`-style constants:

```python
# Pickup locations
PICKUP_LOCATIONS = {
    'huntertown': {
        'name': 'Huntertown',
        'address': '1414 Simon Rd, Huntertown, IN',
        'badge': '🏪 HUNTERTOWN',
    },
    'auburn': {
        'name': 'Auburn',
        'address': '530 North St, Auburn, IN 46706',
        'badge': '🏪 AUBURN',
    },
}

# Contact for pickup scheduling — update before go-live
PICKUP_CONTACT_EMAIL = 'info@thepeptidewizard.com'
PICKUP_CONTACT_PHONE = None  # e.g. '260-555-1234', or None
```

---

## Step 3 — Expose `allows_pickup` in `/api/validate-discount`

Replace the `return jsonify({...})` block at **lines 2151–2164** with:

```python
return jsonify({
    'valid': True,
    'code': discount['code'],
    'discount_id': discount['id'],
    'discount_percent': discount['discount_percent'],
    'discount_amount': round(amt, 2),
    'message': message,
    'is_own_code': is_own_code,
    'commission_percent': commission_percent,
    'combined_percent': combined_percent,
    'combined_amount': round(combined_amount, 2),
    'has_sale_items': has_sale_items,
    'non_sale_subtotal': round(non_sale_subtotal, 2),
    'allows_pickup': bool(discount['allows_pickup']),   # NEW
    'pickup_locations': [                                # NEW
        {'value': 'huntertown', 'label': '1414 Simon Rd, Huntertown, IN'},
        {'value': 'auburn',     'label': '530 North St, Auburn, IN 46706'},
    ] if discount['allows_pickup'] else [],
})
```

---

## Step 4 — Lock Down `create_order` (Security + Location)

Replace the delivery-method block at **lines 2513–2524** with:

```python
# Handle delivery method and shipping cost
delivery_method = data.get('delivery_method', 'pickup')
pickup_location = None
shipping_cost = 0.0

if delivery_method == 'pickup':
    # SECURITY: pickup only permitted if the applied discount code allows it
    if not (discount_code_id and discount and discount['allows_pickup']):
        conn.close()
        return jsonify({'error': 'Local pickup requires an eligible discount code.'}), 400

    pickup_location = data.get('pickup_location')
    if pickup_location not in PICKUP_LOCATIONS:
        conn.close()
        return jsonify({'error': 'Please select a valid pickup location.'}), 400

elif delivery_method == 'ship':
    # Free shipping if subtotal after discounts is $500+
    net_product_total = subtotal - discount_amount
    free_shipping_threshold = float(get_setting('free_shipping_threshold', '500.00'))
    if net_product_total >= free_shipping_threshold:
        shipping_cost = 0.0
        print(f"[SHIPPING] Free shipping applied - net total ${net_product_total:.2f} >= ${free_shipping_threshold:.2f}")
    else:
        shipping_cost = float(get_setting('shipping_cost', '20.00'))
else:
    conn.close()
    return jsonify({'error': 'Invalid delivery method.'}), 400
```

Replace the INSERT statement at **lines 2559–2560** with:

```python
c.execute('''INSERT INTO orders
    (user_id, order_number, subtotal, discount_amount, discount_code_id,
     shipping_cost, sales_tax, processing_fee, delivery_method, pickup_location,
     credit_applied, total, notes, shipping_address, introducer_user_id, status)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
  (session['user_id'], order_number, subtotal, discount_amount, discount_code_id,
   shipping_cost, sales_tax, processing_fee, delivery_method, pickup_location,
   credit_applied, total, data.get('notes', ''), data.get('shipping_address', ''),
   introducer_user_id, 'pending_payment'))
```

Update the fallback order dict at **line 2628** to include `pickup_location`:

```python
{'total': total, 'delivery_method': delivery_method, 'pickup_location': pickup_location,
 'shipping_address': '', 'notes': ''},
```

Update the response JSON at **line 2636** — add `'pickup_location': pickup_location,` anywhere in the dict.

---

## Step 5 — Persist `allows_pickup` in Discount Code Endpoints

**`admin_add_code()` — replace INSERT at lines 4060–4061:**

```python
c.execute('''INSERT INTO discount_codes
    (code, description, discount_percent, discount_amount, min_order_amount,
     usage_limit, expires_at, referrer_user_id, commission_percent, allows_pickup)
    VALUES (?,?,?,?,?,?,?,?,?,?)''',
  (data['code'].upper(), data.get('description', ''),
   data.get('discount_percent', 0), data.get('discount_amount', 0),
   data.get('min_order_amount', 0), data.get('usage_limit'),
   data.get('expires_at'), data.get('referrer_user_id'),
   data.get('commission_percent', 20),
   1 if data.get('allows_pickup') else 0))
```

**`admin_update_code()` — replace UPDATE at lines 4075–4076:**

```python
conn.execute('''UPDATE discount_codes
    SET code=?, description=?, discount_percent=?, discount_amount=?,
        min_order_amount=?, usage_limit=?, active=?, expires_at=?,
        referrer_user_id=?, commission_percent=?, first_order_only=?,
        allows_pickup=?
    WHERE id=?''',
  (data.get('code', '').upper(), data.get('description', ''),
   data.get('discount_percent', 0), data.get('discount_amount', 0),
   data.get('min_order_amount', 0), data.get('usage_limit'),
   1 if data.get('active', True) else 0, data.get('expires_at'),
   data.get('referrer_user_id'), data.get('commission_percent', 20),
   1 if data.get('first_order_only') else 0,
   1 if data.get('allows_pickup') else 0,
   cid))
```

---

## Step 6 — Add `'ready_for_pickup'` to Valid Statuses

**Line 4477**, add it to the list:

```python
valid = ['pending', 'pending_payment', 'paid', 'processing', 'ready_to_ship',
         'ready_for_pickup',                                     # NEW
         'shipped', 'delivered', 'fulfilled', 'cancelled', 'refunded']
```

**Line 1286** in `send_status_update`, add to the dict:

```python
status_messages = {
    'paid': 'Your payment has been received.',
    'processing': 'Your order is being prepared.',
    'ready_for_pickup': 'Your order is ready for pickup!',       # NEW
    'shipped': f"Your order has been shipped.{' Tracking: ' + order['tracking_number'] if order.get('tracking_number') else ''}",
    'delivered': 'Your order has been delivered.',
    'cancelled': 'Your order has been cancelled.',
}
```

---

## Step 7 — Set `picked_up_at` in the Status Endpoint

In `admin_update_order_status`, find the UPDATE at **line 4525** and replace with:

```python
# Set picked_up_at timestamp when pickup order transitions to fulfilled
picked_up_at_sql = ''
if status == 'fulfilled' and current_dict.get('delivery_method') == 'pickup' and not current_dict.get('picked_up_at'):
    picked_up_at_sql = ', picked_up_at=CURRENT_TIMESTAMP'

conn.execute(f'UPDATE orders SET status=?, admin_notes=?, tracking_number=?, updated_at=CURRENT_TIMESTAMP{picked_up_at_sql} WHERE id=?',
             (status, data.get('admin_notes', current_dict.get('admin_notes', '')), tracking_number, oid))
```

---

## Step 8 — New Admin Endpoint: Mark Ready for Pickup

Add this **right after the `delivery-method` route at line 4704**:

```python
@app.route('/api/admin/orders/<int:oid>/mark-ready-pickup', methods=['POST'])
@admin_required
def admin_mark_ready_pickup(oid):
    """Mark a pickup order as ready and email the customer."""
    conn = get_db()
    order = conn.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
    if not order:
        conn.close()
        return jsonify({'error': 'Order not found'}), 404
    if order['delivery_method'] != 'pickup':
        conn.close()
        return jsonify({'error': 'Not a pickup order'}), 400

    conn.execute(
        "UPDATE orders SET status='ready_for_pickup', updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (oid,)
    )
    conn.commit()
    conn.close()

    try:
        send_pickup_ready_email(oid)
    except Exception as e:
        print(f"[PICKUP] Ready-email failed for order {oid}: {e}")

    return jsonify({'message': 'Order marked ready for pickup; customer notified.'})
```

> We don't need a separate mark-picked-up endpoint — the existing `markPickedUp()` admin function already hits `/api/admin/orders/<id>/status` with `status: 'fulfilled'`, and Step 7 now stamps `picked_up_at` automatically.

---

## Step 9 — New Email Function

Add this next to `send_status_update` around **line 1300**:

```python
def send_pickup_ready_email(order_id):
    """Notify customer their pickup order is ready."""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT o.*, u.full_name, u.email, u.phone
                 FROM orders o JOIN users u ON o.user_id=u.id
                 WHERE o.id=?''', (order_id,))
    order = c.fetchone()
    conn.close()
    if not order:
        return
    order = dict(order)

    loc = PICKUP_LOCATIONS.get(order.get('pickup_location'))
    if not loc:
        print(f"[PICKUP] No valid location on order {order_id}; skipping email.")
        return

    contact_line = 'reply to this email'
    if PICKUP_CONTACT_PHONE:
        contact_line += f' or text {PICKUP_CONTACT_PHONE}'

    html = f"""<html><body style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">
    <div style="background:#10b981;color:white;padding:20px;border-radius:10px 10px 0 0;">
        <h2 style="margin:0;">🏪 Your Order is Ready for Pickup!</h2>
    </div>
    <div style="background:white;padding:20px;border:1px solid #ddd;border-top:none;border-radius:0 0 10px 10px;">
        <p>Hi {order['full_name']},</p>
        <p>Great news — your order <strong>{order['order_number']}</strong> is ready for local pickup.</p>
        <div style="background:#f0fdf4;border-left:4px solid #10b981;padding:14px;margin:16px 0;border-radius:4px;">
            <p style="margin:0;"><strong>📍 Pickup Location:</strong><br>{loc['address']}</p>
            <p style="margin:8px 0 0 0;"><strong>⏰ Hours:</strong> By appointment only</p>
        </div>
        <p>To schedule a pickup time, please {contact_line}.</p>
        <p><strong>What to bring:</strong></p>
        <ul>
            <li>Your order number: <strong>{order['order_number']}</strong></li>
            <li>A valid photo ID</li>
        </ul>
        <p style="margin-top:20px;color:#666;font-size:13px;">
            Thanks for supporting local!<br>— The Peptide Wizard
        </p>
    </div>
    </body></html>"""

    send_email(order['email'], f"Ready for Pickup — Order {order['order_number']}", html)

    if order.get('phone'):
        send_sms(order['phone'],
                 f"Order {order['order_number']} ready for pickup at {loc['address']}. Reply to schedule.")

    log_notification(order['user_id'], order_id, 'pickup_ready', 'email', order['email'], 'sent')
```

---

# PART B — `templates/index.html` Changes (Customer Checkout)

Good news: your checkout already has most pieces. Currently `delivery_method: 'ship'` is **hardcoded** at line 1303 — we'll make it dynamic.

## Step 10 — Add State Fields

**Line 169** (in the `state = {...}` object), add:

```javascript
deliveryMethod: 'ship',
pickupLocation: null,
```

## Step 11 — Reset State When Cart Opens

Whenever the checkout modal opens, delivery method should reset to ship. Find the function that builds the checkout modal (near line 970, `showCheckoutModal` or similar) and add at the very start:

```javascript
state.deliveryMethod = 'ship';
state.pickupLocation = null;
```

## Step 12 — Insert Pickup Toggle Block in Checkout Modal

In the checkout form HTML around **line 977**, **before** the existing `<div class="form-group">` that contains the shipping address, add this block:

```html
<!-- Pickup option — only shown if an eligible discount code is applied -->
<div id="pickupOptionBlock" style="display:none; margin-bottom:20px; padding:16px; border:2px solid #10b981; border-radius:8px; background:#f0fdf4;">
    <h4 style="margin:0 0 12px 0; color:#065f46;">🏪 Local Pickup Available!</h4>
    <p style="margin:0 0 12px 0; font-size:14px; color:#064e3b;">
        This discount code qualifies you for free local pickup.
    </p>
    <label style="display:block; margin-bottom:8px; cursor:pointer;">
        <input type="radio" name="deliveryMethodChoice" value="ship" checked onchange="togglePickupFields()">
        <strong>Ship to me</strong> (standard shipping rates apply)
    </label>
    <label style="display:block; cursor:pointer;">
        <input type="radio" name="deliveryMethodChoice" value="pickup" onchange="togglePickupFields()">
        <strong>Pick up locally</strong> <span style="color:#059669;">(free)</span>
    </label>
    <div id="pickupLocationFields" style="display:none; margin-top:12px; padding-top:12px; border-top:1px solid #d1fae5;">
        <label for="pickupLocationSelect" style="display:block; margin-bottom:4px; font-weight:600; color:#065f46;">
            Choose pickup location:
        </label>
        <select id="pickupLocationSelect" style="width:100%; padding:8px; border:1px solid #10b981; border-radius:6px;">
            <option value="huntertown">1414 Simon Rd, Huntertown, IN</option>
            <option value="auburn">530 North St, Auburn, IN 46706</option>
        </select>
        <p style="font-size:13px; color:#059669; margin-top:8px;">
            📅 <em>Pickup is by appointment only. We'll email you to schedule after payment.</em>
        </p>
    </div>
</div>
```

## Step 13 — Wrap Shipping Address in an ID

Change **line 978** from:
```html
<div class="form-group">
```
to:
```html
<div class="form-group" id="shippingAddressSection">
```

This lets us hide the whole block when pickup is chosen.

## Step 14 — Add `togglePickupFields()` JS Function

Add this anywhere in the script block (right before `submitOrder` near line 1247 is a good spot):

```javascript
function togglePickupFields() {
    const selected = document.querySelector('input[name="deliveryMethodChoice"]:checked');
    const isPickup = selected && selected.value === 'pickup';

    state.deliveryMethod = isPickup ? 'pickup' : 'ship';
    state.pickupLocation = isPickup
        ? document.getElementById('pickupLocationSelect').value
        : null;

    // Hide/show shipping address section
    const shippingSection = document.getElementById('shippingAddressSection');
    if (shippingSection) shippingSection.style.display = isPickup ? 'none' : 'block';

    // Hide/show pickup location dropdown
    const locFields = document.getElementById('pickupLocationFields');
    if (locFields) locFields.style.display = isPickup ? 'block' : 'none';

    // Recalculate totals (shipping goes to $0 when pickup)
    const subtotal = state.cart.reduce((sum, item) => {
        const p = state.products.find(pp => pp.id === item.productId);
        if (!p) return sum;
        let price;
        const saleMin = p.sale_min_qty || 1;
        if (p.sale_active && p.sale_price > 0 && item.qty >= saleMin) price = p.sale_price;
        else if (p.price_bulk && item.qty >= p.bulk_quantity) price = p.price_bulk / p.bulk_quantity;
        else price = p.price_single;
        return sum + price * item.qty;
    }, 0);
    const discountAmount = state.discount?.discount_amount || 0;
    updateCheckoutTotal(subtotal, discountAmount);
}

// Listen for location dropdown changes too
document.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'pickupLocationSelect') {
        state.pickupLocation = e.target.value;
    }
});
```

## Step 15 — Update `updateCheckoutTotal` to Zero Shipping for Pickup

In `updateCheckoutTotal` at **line 1152**, change:

```javascript
let shippingCost = state.shippingCost;
let freeShipping = false;
if (netProductTotal >= state.freeShippingThreshold) {
    shippingCost = 0;
    freeShipping = true;
}
```

to:

```javascript
let shippingCost = state.shippingCost;
let freeShipping = false;

// Pickup = no shipping cost
if (state.deliveryMethod === 'pickup') {
    shippingCost = 0;
    freeShipping = true;
} else if (netProductTotal >= state.freeShippingThreshold) {
    shippingCost = 0;
    freeShipping = true;
}
```

Then in the shipping line display at **line 1163**, when pickup is chosen show "PICKUP" instead of "FREE!". Change:

```javascript
if (freeShipping) {
    shippingLine.innerHTML = `<span>Shipping:</span><span style="color: #38a169; font-weight: 600;">FREE!</span>`;
}
```

to:

```javascript
if (freeShipping) {
    const label = state.deliveryMethod === 'pickup' ? '🏪 PICKUP' : 'FREE!';
    shippingLine.innerHTML = `<span>Shipping:</span><span style="color: #38a169; font-weight: 600;">${label}</span>`;
}
```

## Step 16 — Reveal Pickup Block When Validating Discount

In the discount validation handler around **line 812**, where `state.discount = result;` is set, add right after it:

```javascript
state.discount = result;
state.referrerChoice = null;

// Reveal pickup option if the code allows it AND checkout modal is open
const pickupBlock = document.getElementById('pickupOptionBlock');
if (pickupBlock) {
    pickupBlock.style.display = result.allows_pickup ? 'block' : 'none';
}
```

Also — when discount is removed (find wherever `state.discount = null` is set), hide the block and reset:

```javascript
state.discount = null;
state.deliveryMethod = 'ship';
state.pickupLocation = null;
const pickupBlock = document.getElementById('pickupOptionBlock');
if (pickupBlock) pickupBlock.style.display = 'none';
const shippingSection = document.getElementById('shippingAddressSection');
if (shippingSection) shippingSection.style.display = 'block';
```

## Step 17 — Also Check at Modal Open Time

When the checkout modal renders (line 1083 area, right after `initAddressAutocomplete()`), add:

```javascript
// If a pickup-eligible code is already applied, show the pickup block
if (state.discount?.allows_pickup) {
    const pickupBlock = document.getElementById('pickupOptionBlock');
    if (pickupBlock) pickupBlock.style.display = 'block';
}
```

## Step 18 — Skip Address Validation + Send Correct Fields

In `submitOrder()` at **line 1247**, replace the address-validation block at **lines 1260–1284** with:

```javascript
let shippingAddress = '';
let addressData = null;

if (state.deliveryMethod === 'ship') {
    // Get structured address fields
    const street1 = document.getElementById('addrStreet1')?.value?.trim() || '';
    const street2 = document.getElementById('addrStreet2')?.value?.trim() || '';
    const city = document.getElementById('addrCity')?.value?.trim() || '';
    const addrState = document.getElementById('addrState')?.value?.trim().toUpperCase() || '';
    const zip = document.getElementById('addrZip')?.value?.trim() || '';

    if (!street1 || !city || !addrState || !zip) {
        showAlert('Please enter a complete shipping address');
        return;
    }

    addressData = { street1, street2, city, state: addrState, zip };
    shippingAddress = street2
        ? `${street1}\n${street2}\n${city}, ${addrState} ${zip}`
        : `${street1}\n${city}, ${addrState} ${zip}`;
} else if (state.deliveryMethod === 'pickup') {
    // Pickup: validate location selected
    if (!state.pickupLocation || !['huntertown', 'auburn'].includes(state.pickupLocation)) {
        showAlert('Please select a pickup location');
        return;
    }
}
```

Replace the `/api/orders` POST body at **lines 1297–1317** with:

```javascript
const result = await api('/api/orders', {
    method: 'POST',
    body: JSON.stringify({
        items,
        discount_code: state.discount?.code || null,
        referrer_choice: state.referrerChoice || null,
        delivery_method: state.deliveryMethod,                  // dynamic
        pickup_location: state.pickupLocation,                  // NEW
        shipping_address: shippingAddress,
        shipping_address_data: addressData,
        apply_credit: applyCredit,
        introducer_user_id: parseInt(document.getElementById('introducerUserId')?.value) || null,
        final_attestation: true,
        acknowledgments: {
            research_only: ack1,
            not_for_consumption: ack2,
            authorized: ack3,
            compliance: ack4,
            terms_accepted: ack5
        }
    })
});
```

---

# PART C — `templates/admin.html` Changes

## Step 19 — Add `allows_pickup` Checkbox to Add-Discount Modal

In `showAddDiscountModal()` around **line 2097**, right before the closing `</div>` of Referral Settings, add a new section:

```html
<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:14px;margin-top:15px;">
    <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-weight:600;color:#065f46;">
        <input type="checkbox" id="discAllowsPickup" style="width:18px;height:18px;cursor:pointer;">
        🏪 Allow Local Pickup
    </label>
    <p style="color:#047857;font-size:13px;margin:6px 0 0 28px;">If checked, customers using this code can choose free local pickup (Huntertown or Auburn) instead of shipping.</p>
</div>
```

Then in `addDiscount()` at **line 2122**, add to the POST body:

```javascript
commission_percent: parseFloat(document.getElementById('discCommission').value) || 20,
allows_pickup: document.getElementById('discAllowsPickup').checked ? 1 : 0   // NEW
```

## Step 20 — Add `allows_pickup` Checkbox to Edit-Discount Modal

In `showEditDiscountModal()` around **line 2186** (right after the First-Time Order block), add:

```html
<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:14px;margin-bottom:4px;">
    <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-weight:600;color:#065f46;">
        <input type="checkbox" id="discAllowsPickup" ${d.allows_pickup ? 'checked' : ''} style="width:18px;height:18px;cursor:pointer;">
        🏪 Allow Local Pickup
    </label>
    <p style="color:#047857;font-size:13px;margin:6px 0 0 28px;">If checked, customers using this code can choose free local pickup.</p>
</div>
```

In `updateDiscount()` at **line 2230**, add to the PUT body:

```javascript
commission_percent: parseFloat(document.getElementById('discCommission').value) || 20,
allows_pickup: document.getElementById('discAllowsPickup').checked ? 1 : 0   // NEW
```

## Step 21 — Add "Ready for Pickup" Button to Open Orders

In the order row at **line 3737**, replace that line with two separate buttons:

```javascript
${['paid', 'processing'].includes(o.status) && isPickupOrder(o) ? `<button class="btn btn-small" style="background:#8b5cf6;color:white;" onclick="markReadyForPickup(${o.id})">🏪 Ready for Pickup</button>` : ''}
${o.status === 'ready_for_pickup' ? `<button class="btn btn-success btn-small" onclick="markPickedUp(${o.id})">✓ Picked Up</button>` : ''}
```

## Step 22 — Add `markReadyForPickup()` Function

Add this right after `markPickedUp()` at **line 4623**:

```javascript
async function markReadyForPickup(id) {
    if (!confirm('Mark this order as ready for pickup? The customer will be emailed with pickup instructions.')) return;
    try {
        await api(`/api/admin/orders/${id}/mark-ready-pickup`, {
            method: 'POST'
        });
        showAlert('Customer notified. Order is now awaiting pickup.', 'success');
        state.orders = await api('/api/admin/orders');
        if (state.currentTab === 'readyToShip') {
            renderReadyToShip();
        } else {
            renderOpenOrders();
        }
    } catch (err) {
        showAlert(err.message);
    }
}
```

## Step 23 — Show Pickup Location in Order Detail

Your order detail views show delivery method but not location. Find the delivery display line (there are several — line 1381, 4391 are examples) and replace patterns like:

```javascript
<p><strong>Delivery:</strong> ${o.delivery_method === 'ship' ? '📦 Ship' : '🏪 Pickup'}</p>
```

with:

```javascript
<p><strong>Delivery:</strong> ${o.delivery_method === 'ship' ? '📦 Ship' : (o.pickup_location === 'huntertown' ? '🏪 Pickup — Huntertown (1414 Simon Rd)' : o.pickup_location === 'auburn' ? '🏪 Pickup — Auburn (530 North St)' : '🏪 Pickup')}</p>
```

Check **lines 1381, 3833, 4206, 4391** — update wherever that pattern appears.

## Step 24 — Update Ready to Ship Queue (already mostly correct)

The filter at line 4016 already scopes to ship-only. However, the `pickupOrders` section at line 3883 allows clicking "✓ Fulfilled" straight through — that's fine for orders that never got the email, but now that we have `ready_for_pickup`, you might want to refine. Optional cleanup — not required for feature to work.

---

# PART D — `templates/mobile_admin.html` Changes

## Step 25 — Add Ready-for-Pickup Button

In the open-orders card renderer at **line 832**, replace:

```javascript
${o.delivery_method === 'pickup' 
    ? `<button class="order-btn primary" onclick="markPickedUp(${o.id})">✓ Picked Up</button>`
    : `<button class="order-btn primary" onclick="markReadyToShip(${o.id})">📦 Ready</button>`
}
```

with:

```javascript
${o.delivery_method === 'pickup' && ['paid', 'processing'].includes(o.status)
    ? `<button class="order-btn primary" style="background:#8b5cf6;" onclick="markReadyForPickup(${o.id})">🏪 Ready for Pickup</button>`
    : o.delivery_method === 'pickup' && o.status === 'ready_for_pickup'
    ? `<button class="order-btn primary" onclick="markPickedUp(${o.id})">✓ Picked Up</button>`
    : `<button class="order-btn primary" onclick="markReadyToShip(${o.id})">📦 Ready</button>`
}
```

## Step 26 — Add `markReadyForPickup()` to Mobile

Right after `markPickedUp()` at **line 857**, add:

```javascript
async function markReadyForPickup(orderId) {
    if (!confirm('Mark ready for pickup? Customer will be emailed.')) return;
    try {
        const res = await fetch(`/api/admin/orders/${orderId}/mark-ready-pickup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed');
        showToast('Customer notified. Awaiting pickup.');
        refreshData();
    } catch(e) {
        showToast(e.message || 'Error updating order', true);
    }
}
```

## Step 27 — Show Location on Mobile Cards

In the card renderer at **line 826**, replace:

```javascript
<span class="order-status status-${o.status}">${o.delivery_method === 'pickup' ? '🏪 Pickup' : o.status}</span>
```

with:

```javascript
<span class="order-status status-${o.status}">${
    o.delivery_method === 'pickup'
        ? (o.pickup_location === 'huntertown' ? '🏪 HUNTERTOWN' : o.pickup_location === 'auburn' ? '🏪 AUBURN' : '🏪 Pickup')
        : o.status
}</span>
```

---

# Deployment Sequence

1. **Backend first** — Edit `app.py` (Steps 1–9), commit, push. Railway auto-deploys, runs migrations.
2. **Check Railway logs** for migration errors.
3. **Test backend via API** (Postman / curl):
   - Create a test code with `allows_pickup: true`
   - Validate that code → should return `allows_pickup: true`
   - Create order with `delivery_method: 'pickup'`, `pickup_location: 'auburn'`, that code
   - POST `/api/admin/orders/<id>/mark-ready-pickup` → check your inbox
   - PUT status to `fulfilled` → verify `picked_up_at` gets set in DB
4. **Frontend** — Edit all three templates (Steps 10–27), commit, push.
5. **End-to-end test**:
   - Log in as a regular user, add items to cart, apply pickup-eligible code → confirm pickup block appears
   - Complete order with pickup, pay via Stripe
   - Log in as admin, go to Open Orders → see purple "Ready for Pickup" button
   - Click it → check customer inbox
   - Click "Picked Up" → verify status and timestamp

---

# Testing Checklist

## Backend
- [ ] Migrations run clean on Railway
- [ ] `/api/admin/discount-codes` POST with `allows_pickup: 1` persists
- [ ] `/api/admin/discount-codes/<id>` PUT with `allows_pickup` persists
- [ ] `/api/validate-discount` returns `allows_pickup: true` for eligible code
- [ ] `/api/validate-discount` returns `allows_pickup: false` for normal code
- [ ] `/api/orders` with pickup + eligible code + valid location → creates, shipping=$0
- [ ] `/api/orders` with pickup + non-eligible code → 400
- [ ] `/api/orders` with pickup + invalid location → 400
- [ ] `/api/orders` with ship → unchanged behavior (free shipping threshold still works)
- [ ] `/api/admin/orders/<id>/mark-ready-pickup` → status flips + email sent
- [ ] Marking fulfilled on pickup order → `picked_up_at` timestamp set

## Frontend — Customer
- [ ] Normal code → no pickup option appears in checkout
- [ ] Pickup code → pickup option appears
- [ ] Select "Pick up locally" → shipping address fields hide, shipping line shows "🏪 PICKUP", total drops
- [ ] Switch back to "Ship to me" → shipping address fields reappear, total restores
- [ ] Remove discount code → pickup block hides
- [ ] Submit pickup order → succeeds, correct total charged
- [ ] Submit ship order → unchanged behavior

## Frontend — Admin
- [ ] Add new discount code with "Allow Local Pickup" checked → code works
- [ ] Edit existing code → checkbox reflects current value
- [ ] Open Orders: pickup order shows purple "Ready for Pickup" button (not Ready to Ship)
- [ ] Click Ready for Pickup → customer gets email, status flips, button changes to "Picked Up"
- [ ] Click Picked Up → status becomes fulfilled
- [ ] Order detail view shows pickup location name + address
- [ ] Ship orders behave exactly as before

## Frontend — Mobile
- [ ] Pickup orders show HUNTERTOWN/AUBURN badge
- [ ] Purple "Ready for Pickup" button appears for paid/processing pickups
- [ ] "Picked Up" button appears for ready_for_pickup status

---

# Before Go-Live

1. Update `PICKUP_CONTACT_EMAIL` / `PICKUP_CONTACT_PHONE` in `app.py`
2. Turn `allows_pickup` ON for just one or two codes initially (e.g., `LOCAL`)
3. Do one full end-to-end test order on yourself
4. Optional marketing: small note on product pages — *"Local to Ft. Wayne? Use code LOCAL for free pickup."*

---

# Parking Lot

- Auto-reminder email if pickup not completed after 7 days
- Calendly link in the ready email for self-scheduling
- Pickup time window preference at checkout (AM/PM)
- Pickup confirmation log (ties into damage/loss incident log already queued)
