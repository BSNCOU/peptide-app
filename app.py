"""
Research Materials Ordering Platform - Production Ready
Flask Backend with Admin Dashboard, Notifications, Security, PDF Invoices
"""

from flask import Flask, request, jsonify, render_template, session, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('PRODUCTION', False)

# ============================================
# CONFIGURATION
# ============================================

CONFIG = {
    'RESEND_API_KEY': os.environ.get('RESEND_API_KEY', ''),
    'EMAIL_FROM': os.environ.get('EMAIL_FROM', 'onboarding@resend.dev'),
    'TWILIO_ACCOUNT_SID': os.environ.get('TWILIO_ACCOUNT_SID', ''),
    'TWILIO_AUTH_TOKEN': os.environ.get('TWILIO_AUTH_TOKEN', ''),
    'TWILIO_PHONE_NUMBER': os.environ.get('TWILIO_PHONE_NUMBER', ''),
    'APP_URL': os.environ.get('APP_URL', 'http://localhost:5000'),
    'LOW_STOCK_THRESHOLD': int(os.environ.get('LOW_STOCK_THRESHOLD', '10')),
    'ADMIN_EMAIL': os.environ.get('ADMIN_EMAIL', ''),
    'DATABASE_URL': os.environ.get('DATABASE_URL', ''),
    'COMPANY_NAME': os.environ.get('COMPANY_NAME', 'The Peptide Wizard'),
    'COMPANY_ADDRESS': os.environ.get('COMPANY_ADDRESS', ''),
}

DATABASE = 'research_orders.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT NOT NULL,
        organization TEXT,
        country TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        email_verified INTEGER DEFAULT 0,
        email_verify_token TEXT,
        email_verify_expires TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        first_login_confirmed INTEGER DEFAULT 0,
        reset_token TEXT,
        reset_token_expires TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS acknowledgments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        acknowledgment_type TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ip_address TEXT,
        version_hash TEXT NOT NULL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        price_single REAL NOT NULL,
        price_bulk REAL,
        bulk_quantity INTEGER DEFAULT 10,
        stock INTEGER DEFAULT 0,
        category TEXT,
        active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS discount_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        description TEXT,
        discount_percent REAL DEFAULT 0,
        discount_amount REAL DEFAULT 0,
        min_order_amount REAL DEFAULT 0,
        usage_limit INTEGER DEFAULT NULL,
        times_used INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        expires_at TIMESTAMP DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        order_number TEXT UNIQUE NOT NULL,
        subtotal REAL NOT NULL,
        discount_amount REAL DEFAULT 0,
        discount_code_id INTEGER DEFAULT NULL,
        total REAL NOT NULL,
        status TEXT DEFAULT 'pending_payment',
        notes TEXT,
        admin_notes TEXT,
        shipping_address TEXT,
        tracking_number TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        is_bulk_price INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS notification_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        order_id INTEGER,
        notification_type TEXT NOT NULL,
        channel TEXT NOT NULL,
        recipient TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS rate_limits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_address TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        request_count INTEGER DEFAULT 1,
        window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_rate_limits_ip ON rate_limits(ip_address, endpoint)')
    
    c.execute('''CREATE TABLE IF NOT EXISTS csrf_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        session_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL
    )''')
    
    # Create default admin
    c.execute('SELECT COUNT(*) FROM users WHERE is_admin = 1')
    if c.fetchone()[0] == 0:
        admin_pw = generate_password_hash('admin123')
        c.execute('''INSERT INTO users (full_name, email, phone, country, password_hash, is_admin, first_login_confirmed, email_verified) 
                     VALUES (?,?,?,?,?,1,1,1)''',
                  ('Admin', 'admin@admin.com', '0000000000', 'US', admin_pw))
        print("✓ Default admin: admin@admin.com / admin123")
    
    conn.commit()
    conn.close()

def import_products():
    """Import your full product catalog"""
    products = [
        ('2S10', 'SS-31 (10mg/10vials)', 83, 578, 'Peptides'),
        ('332', 'SLU-PP-332 (5mg/10vials)', 132, 924, 'Peptides'),
        ('375', 'LL37 (5mg/10vials)', 61, 424, 'Peptides'),
        ('5AD', 'AOD9604 (5mg/10vials)', 66, 517, 'Peptides'),
        ('5AM', '5-amino-1mq (5mg*10vials)', 72, 501, 'Peptides'),
        ('BB20', 'BPC 10mg + TB 10mg (20mg/10vials)', 66, 550, 'Blends'),
        ('BBG70', 'GLOW (BPC+GHK-CU+TB500) (70mg/10vials)', 108, 858, 'Blends'),
        ('BBGK', 'KLOW (BPC+GHK-CU+TB500+KPV) (80mg/10vials)', 205, 1172, 'Blends'),
        ('BC10', 'BPC 157 (10mg/10vials)', 41, 385, 'Peptides'),
        ('CBL60', 'Cerebrolysin (60mg/6vials)', 94, 655, 'Nootropics'),
        ('CD5', 'CJC-1295 DAC (5mg/10vials)', 154, 1078, 'Growth Hormone'),
        ('CGL10', 'Cagrilintide (10mg/10vials)', 88, 616, 'Weight Management'),
        ('CND10', 'CJC-1295 NO DAC (10mg/10vials)', 143, 1001, 'Growth Hormone'),
        ('CP10', 'CJC-1295 NO DAC + IPA5mg (5mg+5mg/10vials)', 88, 605, 'Growth Hormone'),
        ('CS10', 'Cagrilintide+Semaglutide (5mg+5mg)', 94, 655, 'Weight Management'),
        ('CU50', 'GHK-CU (50mg/10vials)', 40, 306, 'Peptides'),
        ('DS15', 'DSIP (10mg/10vials)', 77, 539, 'Sleep'),
        ('ET10', 'Epithalon (10mg/10vials)', 39, 270, 'Anti-Aging'),
        ('F410', 'FOXO4 (10mg*10vials)', 297, 2079, 'Anti-Aging'),
        ('G5K', 'HCG (5000iu/10vials)', 83, 578, 'Hormones'),
        ('GTT', 'Glutathione (1500mg/10vials)', 110, 770, 'Antioxidants'),
        ('IP10', 'Ipamorelin (10mg/10vials)', 66, 462, 'Growth Hormone'),
        ('KPV10', 'KPV - LYSINE-PROLINE-VALINE (10mg/10vials)', 61, 424, 'Peptides'),
        ('KS10', 'KissPeptin-10 (10mg/10vials)', 55, 440, 'Peptides'),
        ('ML10', 'MT-2 Melanotan 2 Acetate (10mg/10vials)', 44, 308, 'Tanning'),
        ('MS10', 'MOTS-c (10mg/10vials)', 55, 385, 'Metabolic'),
        ('NJ1000', 'NAD+ (1000mg/10vials)', 110, 893, 'Longevity'),
        ('NJ500', 'NAD+ (500mg/10vials)', 77, 550, 'Longevity'),
        ('NP810', 'Snap-8 (10mg/10vials)', 44, 308, 'Cosmetic'),
        ('OT2', 'Oxytocin Acetate (2mg*10vials)', 275, 344, 'Hormones'),
        ('P41', 'PT-141 (10mg/10vials)', 61, 424, 'Peptides'),
        ('PI10', 'Pinealon (10mg/10vials)', 69, 550, 'Nootropics'),
        ('RT10', 'Retatrutide (10mg/10vials)', 88, 704, 'Weight Management'),
        ('SK5', 'Selank (5mg/10vials)', 44, 308, 'Nootropics'),
        ('SM10', 'Semaglutide (10mg/10vials)', 77, 539, 'Weight Management'),
        ('TA5', 'Thymosin Alpha-1 (5mg/10vials)', 72, 501, 'Immune'),
        ('TB10', 'TB500 Thymosin B4 Acetate (10mg/10vials)', 61, 550, 'Peptides'),
        ('TR10', 'Tirzepatide (10mg/10vials)', 77, 539, 'Weight Management'),
        ('TSM10', 'Tesamorelin (10mg/10vials)', 83, 550, 'Growth Hormone'),
        ('VIP10', 'VIP (10mg/10vials)', 154, 1078, 'Peptides'),
        ('VIP5', 'VIP (5mg/10vials)', 83, 578, 'Peptides'),
        ('WA10', 'BAC Water (10ML/10vials)', 6, 55, 'Supplies'),
        ('XA5', 'Semax (5mg/10vials)', 44, 308, 'Nootropics'),
    ]
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM products')
    if c.fetchone()[0] > 0:
        conn.close()
        return False
    
    desc = "This material is supplied for laboratory research purposes only. NOT for human or animal consumption."
    for i, (sku, name, p1, p2, cat) in enumerate(products):
        c.execute('INSERT INTO products (sku,name,description,price_single,price_bulk,bulk_quantity,stock,category,sort_order) VALUES (?,?,?,?,?,10,100,?,?)',
                  (sku, name, desc, p1, p2, cat, i))
    
    codes = [
        ('RESEARCH10', '10% off orders $50+', 10, 0, 50, 100), 
        ('FIRST20', '20% off first order', 20, 0, 0, 50), 
        ('BULK15', '15% off orders $200+', 15, 0, 200, None)
    ]
    for code, d, pct, amt, minord, lim in codes:
        try:
            c.execute('INSERT INTO discount_codes (code,description,discount_percent,discount_amount,min_order_amount,usage_limit) VALUES (?,?,?,?,?,?)',
                      (code, d, pct, amt, minord, lim))
        except: pass
    
    conn.commit()
    conn.close()
    return True

# ============================================
# RATE LIMITING
# ============================================

RATE_LIMITS = {
    'register': (5, 3600),
    'login': (10, 300),
    'forgot_password': (3, 3600),
    'order': (20, 3600),
    'api': (100, 60),
}

def check_rate_limit(endpoint, limit=None, window=None):
    if endpoint not in RATE_LIMITS and not limit:
        return True
    
    max_requests, window_seconds = limit or RATE_LIMITS.get(endpoint, (100, 60))
    if window:
        window_seconds = window
    
    ip = request.remote_addr
    conn = get_db()
    c = conn.cursor()
    
    c.execute('DELETE FROM rate_limits WHERE window_start < ?', (datetime.now() - timedelta(seconds=window_seconds),))
    c.execute('SELECT request_count FROM rate_limits WHERE ip_address = ? AND endpoint = ?', (ip, endpoint))
    result = c.fetchone()
    
    if result:
        if result[0] >= max_requests:
            conn.close()
            return False
        c.execute('UPDATE rate_limits SET request_count = request_count + 1 WHERE ip_address = ? AND endpoint = ?', (ip, endpoint))
    else:
        c.execute('INSERT INTO rate_limits (ip_address, endpoint) VALUES (?, ?)', (ip, endpoint))
    
    conn.commit()
    conn.close()
    return True

def rate_limit(endpoint):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not check_rate_limit(endpoint):
                return jsonify({'error': 'Too many requests. Please try again later.'}), 429
            return f(*args, **kwargs)
        return decorated
    return decorator

# ============================================
# CSRF PROTECTION
# ============================================

def generate_csrf_token():
    if 'session_id' not in session:
        session['session_id'] = secrets.token_hex(16)
    
    token = secrets.token_hex(32)
    expires = datetime.now() + timedelta(hours=24)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM csrf_tokens WHERE expires_at < ?', (datetime.now(),))
    c.execute('INSERT INTO csrf_tokens (token, session_id, expires_at) VALUES (?, ?, ?)',
              (token, session['session_id'], expires))
    conn.commit()
    conn.close()
    
    return token

def verify_csrf_token(token):
    if not token or 'session_id' not in session:
        return False
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM csrf_tokens WHERE token = ? AND session_id = ? AND expires_at > ?',
              (token, session['session_id'], datetime.now()))
    result = c.fetchone()
    conn.close()
    
    return result is not None

# ============================================
# NOTIFICATIONS
# ============================================

def send_email(to, subject, html):
    if not CONFIG['RESEND_API_KEY']:
        print(f"[EMAIL MOCK] To: {to}, Subject: {subject}")
        return True, "Mock sent"
    try:
        import requests
        print(f"[EMAIL] Sending to {to}: {subject}")
        r = requests.post('https://api.resend.com/emails',
            headers={'Authorization': f"Bearer {CONFIG['RESEND_API_KEY']}", 'Content-Type': 'application/json'},
            json={'from': CONFIG['EMAIL_FROM'], 'to': [to], 'subject': subject, 'html': html})
        print(f"[EMAIL] Response: {r.status_code} - {r.text}")
        return r.status_code in [200, 201], r.text
    except Exception as e:
        print(f"[EMAIL ERROR] {str(e)}")
        return False, str(e)

def send_sms(to, msg):
    if not CONFIG['TWILIO_ACCOUNT_SID']:
        print(f"[SMS MOCK] To: {to}, Msg: {msg}")
        return True, "Mock sent"
    try:
        from twilio.rest import Client
        client = Client(CONFIG['TWILIO_ACCOUNT_SID'], CONFIG['TWILIO_AUTH_TOKEN'])
        m = client.messages.create(body=msg, from_=CONFIG['TWILIO_PHONE_NUMBER'], to=to)
        return True, m.sid
    except Exception as e:
        return False, str(e)

def log_notification(user_id, order_id, ntype, channel, recipient, status, error=None):
    conn = get_db()
    conn.execute('INSERT INTO notification_log (user_id,order_id,notification_type,channel,recipient,status,error_message) VALUES (?,?,?,?,?,?,?)',
                 (user_id, order_id, ntype, channel, recipient, status, error))
    conn.commit()
    conn.close()

def send_verification_email(email, token):
    url = f"{CONFIG['APP_URL']}/#/verify-email/{token}"
    html = f"""<html><body style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">
    <h2>Verify Your Email</h2>
    <p>Thank you for registering. Please verify your email by clicking the button below:</p>
    <p style="text-align:center;margin:30px 0;">
        <a href="{url}" style="background:#3b82f6;color:white;padding:14px 28px;border-radius:8px;text-decoration:none;display:inline-block;font-weight:600;">Verify Email</a>
    </p>
    <p style="color:#666;font-size:13px;">This link expires in 24 hours.</p>
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0;"/>
    <p style="color:#999;font-size:12px;">FOR RESEARCH USE ONLY. NOT FOR HUMAN OR ANIMAL CONSUMPTION.</p>
    </body></html>"""
    return send_email(email, "Verify Your Email - Research Materials", html)

def send_order_confirmation(order_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT o.*,u.full_name,u.email,u.phone FROM orders o JOIN users u ON o.user_id=u.id WHERE o.id=?', (order_id,))
    order = c.fetchone()
    if not order:
        conn.close()
        return
    order = dict(order)
    
    c.execute('SELECT oi.*,p.name,p.sku FROM order_items oi JOIN products p ON oi.product_id=p.id WHERE oi.order_id=?', (order_id,))
    items = [dict(i) for i in c.fetchall()]
    conn.close()
    
    items_html = "".join([f"""<tr>
        <td style="padding:10px;border-bottom:1px solid #eee;">{i['name']}</td>
        <td style="padding:10px;border-bottom:1px solid #eee;text-align:center;">{i['quantity']}</td>
        <td style="padding:10px;border-bottom:1px solid #eee;text-align:right;">${i['unit_price']:.2f}</td>
        <td style="padding:10px;border-bottom:1px solid #eee;text-align:right;">${i['unit_price']*i['quantity']:.2f}</td>
    </tr>""" for i in items])
    
    html = f"""<html><body style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;background:#f9f9f9;">
    <div style="background:white;padding:30px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.1);">
        <h2 style="color:#1a1a1a;margin-bottom:20px;">Order Confirmation</h2>
        <p>Hi {order['full_name']},</p>
        <p>Your order <strong style="color:#3b82f6;">{order['order_number']}</strong> has been received.</p>
        <table style="width:100%;border-collapse:collapse;margin:20px 0;">
            <tr style="background:#333;color:white;">
                <th style="padding:12px;text-align:left;">Item</th>
                <th style="padding:12px;text-align:center;">Qty</th>
                <th style="padding:12px;text-align:right;">Price</th>
                <th style="padding:12px;text-align:right;">Total</th>
            </tr>
            {items_html}
        </table>
        <div style="text-align:right;margin-top:20px;padding-top:20px;border-top:2px solid #333;">
            <p><strong>Subtotal:</strong> ${order['subtotal']:.2f}</p>
            {"<p><strong>Discount:</strong> -$" + f"{order['discount_amount']:.2f}</p>" if order['discount_amount'] else ""}
            <p style="font-size:18px;"><strong>Total:</strong> ${order['total']:.2f}</p>
        </div>
        <div style="background:#fff3cd;border:1px solid #ffc107;padding:15px;border-radius:8px;margin-top:20px;">
            <strong>⚠️ Research Use Only</strong><br/>
            <span style="font-size:13px;">All materials are for laboratory research purposes only. Not for human or animal consumption.</span>
        </div>
    </div>
    </body></html>"""
    
    ok, msg = send_email(order['email'], f"Order Confirmation - {order['order_number']}", html)
    log_notification(order['user_id'], order_id, 'order_confirmation', 'email', order['email'], 'sent' if ok else 'failed', None if ok else msg)
    
    if order['phone']:
        sms = f"Research Materials Order {order['order_number']} confirmed. Total: ${order['total']:.2f}"
        ok, msg = send_sms(order['phone'], sms)
        log_notification(order['user_id'], order_id, 'order_confirmation', 'sms', order['phone'], 'sent' if ok else 'failed', None if ok else msg)

def send_password_reset(email, token):
    url = f"{CONFIG['APP_URL']}/#/reset-password/{token}"
    html = f"""<html><body style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">
    <h2>Password Reset Request</h2>
    <p>Click below to reset your password:</p>
    <p style="text-align:center;margin:30px 0;">
        <a href="{url}" style="background:#3b82f6;color:white;padding:14px 28px;border-radius:8px;text-decoration:none;display:inline-block;font-weight:600;">Reset Password</a>
    </p>
    <p style="color:#666;font-size:13px;">This link expires in 1 hour.</p>
    </body></html>"""
    return send_email(email, "Password Reset - Research Materials", html)

def check_low_stock():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM products WHERE stock <= ? AND active = 1', (CONFIG['LOW_STOCK_THRESHOLD'],))
    low_stock = [dict(p) for p in c.fetchall()]
    conn.close()
    
    if low_stock and CONFIG['ADMIN_EMAIL']:
        items_html = "".join([f"<li>{p['sku']} - {p['name']}: <strong>{p['stock']} remaining</strong></li>" for p in low_stock])
        html = f"""<html><body><h2>⚠️ Low Stock Alert</h2><p>The following products are running low:</p><ul>{items_html}</ul></body></html>"""
        send_email(CONFIG['ADMIN_EMAIL'], "Low Stock Alert", html)
    
    return low_stock

def send_status_update(order_id, new_status):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT o.*,u.full_name,u.email,u.phone FROM orders o JOIN users u ON o.user_id=u.id WHERE o.id=?', (order_id,))
    order = c.fetchone()
    conn.close()
    
    if not order:
        return
    order = dict(order)
    
    status_messages = {
        'paid': 'Your payment has been received.',
        'processing': 'Your order is being prepared.',
        'shipped': f"Your order has been shipped.{' Tracking: ' + order['tracking_number'] if order.get('tracking_number') else ''}",
        'delivered': 'Your order has been delivered.',
        'cancelled': 'Your order has been cancelled.',
    }
    
    msg = status_messages.get(new_status, f'Your order status: {new_status}')
    html = f"""<html><body><h2>Order Update</h2><p>Hi {order['full_name']},</p>
    <p>Order <strong>{order['order_number']}</strong>: {msg}</p></body></html>"""
    send_email(order['email'], f"Order Update - {order['order_number']}", html)
    
    if order['phone']:
        send_sms(order['phone'], f"Order {order['order_number']}: {msg}")

# ============================================
# PDF INVOICE GENERATION
# ============================================

def generate_invoice_pdf(order_id):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError:
        return None
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT o.*,u.full_name,u.email,u.phone,u.organization,u.country FROM orders o JOIN users u ON o.user_id=u.id WHERE o.id=?', (order_id,))
    order = c.fetchone()
    if not order:
        conn.close()
        return None
    order = dict(order)
    
    c.execute('SELECT oi.*,p.name,p.sku FROM order_items oi JOIN products p ON oi.product_id=p.id WHERE oi.order_id=?', (order_id,))
    items = [dict(i) for i in c.fetchall()]
    conn.close()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=24, spaceAfter=20)
    warning_style = ParagraphStyle('Warning', parent=styles['Normal'], fontSize=9, textColor=colors.red, alignment=1)
    
    elements = []
    elements.append(Paragraph(CONFIG['COMPANY_NAME'], title_style))
    elements.append(Paragraph(f"Invoice #{order['order_number']}", styles['Heading2']))
    elements.append(Paragraph(f"Date: {order['created_at']}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    elements.append(Paragraph("<b>Bill To:</b>", styles['Normal']))
    elements.append(Paragraph(order['full_name'], styles['Normal']))
    if order['organization']:
        elements.append(Paragraph(order['organization'], styles['Normal']))
    elements.append(Paragraph(order['email'], styles['Normal']))
    elements.append(Spacer(1, 20))
    
    table_data = [['SKU', 'Product', 'Qty', 'Price', 'Total']]
    for item in items:
        table_data.append([item['sku'], item['name'][:35], str(item['quantity']), f"${item['unit_price']:.2f}", f"${item['unit_price']*item['quantity']:.2f}"])
    
    table = Table(table_data, colWidths=[60, 230, 40, 70, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#333333')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))
    
    totals = [['', '', '', 'Subtotal:', f"${order['subtotal']:.2f}"]]
    if order['discount_amount']:
        totals.append(['', '', '', 'Discount:', f"-${order['discount_amount']:.2f}"])
    totals.append(['', '', '', 'Total:', f"${order['total']:.2f}"])
    
    totals_table = Table(totals, colWidths=[60, 230, 40, 70, 80])
    totals_table.setStyle(TableStyle([('ALIGN', (3, 0), (-1, -1), 'RIGHT'), ('FONTNAME', (-2, -1), (-1, -1), 'Helvetica-Bold')]))
    elements.append(totals_table)
    elements.append(Spacer(1, 40))
    
    elements.append(Paragraph("⚠️ FOR RESEARCH USE ONLY - NOT FOR HUMAN OR ANIMAL CONSUMPTION", warning_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

# ============================================
# AUTH HELPERS
# ============================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated

def verified_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        # Email verification disabled until Resend is configured
        # To enable: uncomment the check below and configure RESEND_API_KEY
        # conn = get_db()
        # user = conn.execute('SELECT email_verified FROM users WHERE id=?', (session['user_id'],)).fetchone()
        # conn.close()
        # if not user or not user['email_verified']:
        #     return jsonify({'error': 'Please verify your email first', 'code': 'EMAIL_NOT_VERIFIED'}), 403
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        conn = get_db()
        user = conn.execute('SELECT is_admin FROM users WHERE id=?', (session['user_id'],)).fetchone()
        conn.close()
        if not user or not user['is_admin']:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

def gen_order_num():
    return f"RO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"

def get_ack_hash(t):
    return hashlib.sha256(str(t).encode()).hexdigest()[:16]

ACKS = {
    'use_restriction': "FOR RESEARCH USE ONLY, not for human/animal consumption",
    'intent_statement': "Purchasing solely for laboratory research purposes",
    'no_guidance': "Seller provides no instructions for human/animal use"
}

# ============================================
# ROUTES - PUBLIC
# ============================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/csrf-token', methods=['GET'])
def get_csrf_token():
    token = generate_csrf_token()
    return jsonify({'csrf_token': token})

@app.route('/api/register', methods=['POST'])
@rate_limit('register')
def register():
    data = request.json
    for f in ['full_name', 'email', 'phone', 'country', 'password']:
        if not data.get(f):
            return jsonify({'error': f'{f} required'}), 400
    
    if len(data['password']) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    
    acks = data.get('acknowledgments', {})
    # Registration acknowledgments disabled - users accept at checkout instead
    # if not all([acks.get('use_restriction'), acks.get('intent_statement'), acks.get('no_guidance')]):
    #     return jsonify({'error': 'All acknowledgments required'}), 400
    
    conn = get_db()
    if conn.execute('SELECT id FROM users WHERE email=?', (data['email'].lower(),)).fetchone():
        conn.close()
        return jsonify({'error': 'Email already registered'}), 400
    
    verify_token = secrets.token_urlsafe(32)
    verify_expires = datetime.now() + timedelta(hours=24)
    
    c = conn.cursor()
    c.execute('INSERT INTO users (full_name,email,phone,organization,country,password_hash,email_verify_token,email_verify_expires) VALUES (?,?,?,?,?,?,?,?)',
              (data['full_name'], data['email'].lower(), data['phone'], data.get('organization',''), data['country'], generate_password_hash(data['password']), verify_token, verify_expires))
    user_id = c.lastrowid
    
    # Registration acknowledgments disabled
    # for ack in ['use_restriction', 'intent_statement', 'no_guidance']:
    #     c.execute('INSERT INTO acknowledgments (user_id,acknowledgment_type,ip_address,version_hash) VALUES (?,?,?,?)',
    #               (user_id, ack, request.remote_addr, get_ack_hash(ACKS)))
    
    conn.commit()
    conn.close()
    
    send_verification_email(data['email'].lower(), verify_token)
    
    session['user_id'] = user_id
    return jsonify({'message': 'Registration successful. Please check your email to verify.', 'user_id': user_id, 'requires_first_login_confirmation': True, 'email_verified': False}), 201

@app.route('/api/verify-email/<token>', methods=['POST'])
def verify_email(token):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, email FROM users WHERE email_verify_token = ? AND email_verify_expires > ?', (token, datetime.now()))
    user = c.fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'Invalid or expired verification link'}), 400
    
    c.execute('UPDATE users SET email_verified = 1, email_verify_token = NULL, email_verify_expires = NULL WHERE id = ?', (user['id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Email verified successfully!'})

@app.route('/api/resend-verification', methods=['POST'])
@login_required
@rate_limit('forgot_password')
def resend_verification():
    conn = get_db()
    user = conn.execute('SELECT email, email_verified FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    if user['email_verified']:
        conn.close()
        return jsonify({'message': 'Email already verified'})
    
    verify_token = secrets.token_urlsafe(32)
    verify_expires = datetime.now() + timedelta(hours=24)
    
    conn.execute('UPDATE users SET email_verify_token = ?, email_verify_expires = ? WHERE id = ?',
                 (verify_token, verify_expires, session['user_id']))
    conn.commit()
    conn.close()
    
    send_verification_email(user['email'], verify_token)
    return jsonify({'message': 'Verification email sent'})

@app.route('/api/login', methods=['POST'])
@rate_limit('login')
def login():
    data = request.json
    if not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Email and password required'}), 400
    
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (data['email'].lower(),)).fetchone()
    conn.close()
    
    if not user or not check_password_hash(user['password_hash'], data['password']):
        return jsonify({'error': 'Invalid credentials'}), 401
    
    session['user_id'] = user['id']
    return jsonify({'message': 'Login successful', 'user': {'id': user['id'], 'full_name': user['full_name'], 'email': user['email'], 'is_admin': bool(user['is_admin']), 'first_login_confirmed': bool(user['first_login_confirmed']), 'email_verified': bool(user['email_verified'])}})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'message': 'Logged out'})

@app.route('/api/me', methods=['GET'])
@login_required
def get_me():
    conn = get_db()
    user = conn.execute('SELECT id,full_name,email,phone,organization,country,is_admin,first_login_confirmed,email_verified FROM users WHERE id=?', (session['user_id'],)).fetchone()
    conn.close()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(dict(user))

@app.route('/api/confirm-first-login', methods=['POST'])
@login_required
def confirm_first_login():
    conn = get_db()
    conn.execute('UPDATE users SET first_login_confirmed=1 WHERE id=?', (session['user_id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Confirmed'})

@app.route('/api/forgot-password', methods=['POST'])
@rate_limit('forgot_password')
def forgot_password():
    email = request.json.get('email', '').lower()
    if not email:
        return jsonify({'error': 'Email required'}), 400
    
    conn = get_db()
    user = conn.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
    if user:
        token = secrets.token_urlsafe(32)
        expires = datetime.now() + timedelta(hours=1)
        conn.execute('UPDATE users SET reset_token=?, reset_token_expires=? WHERE id=?', (token, expires, user['id']))
        conn.commit()
        send_password_reset(email, token)
    conn.close()
    return jsonify({'message': 'If account exists, reset link sent'})

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data = request.json
    token = data.get('token')
    password = data.get('password')
    if not token or not password:
        return jsonify({'error': 'Token and password required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be 6+ characters'}), 400
    
    conn = get_db()
    user = conn.execute('SELECT id FROM users WHERE reset_token=? AND reset_token_expires>?', (token, datetime.now())).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'Invalid or expired token'}), 400
    
    conn.execute('UPDATE users SET password_hash=?, reset_token=NULL, reset_token_expires=NULL WHERE id=?',
                 (generate_password_hash(password), user['id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Password reset successful'})

# ============================================
# ROUTES - PRODUCTS
# ============================================

@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    conn = get_db()
    products = conn.execute('SELECT id,sku,name,description,price_single,price_bulk,bulk_quantity,stock,category FROM products WHERE active=1 ORDER BY sort_order,name').fetchall()
    conn.close()
    return jsonify([dict(p) for p in products])

@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    conn = get_db()
    cats = conn.execute('SELECT DISTINCT category FROM products WHERE active=1 AND category IS NOT NULL ORDER BY category').fetchall()
    conn.close()
    return jsonify([c['category'] for c in cats])

# ============================================
# ROUTES - DISCOUNT CODES
# ============================================

@app.route('/api/validate-discount', methods=['POST'])
@login_required
def validate_discount():
    data = request.json
    code = data.get('code', '').upper().strip()
    subtotal = data.get('subtotal', 0)
    
    if not code:
        return jsonify({'error': 'No code provided'}), 400
    
    conn = get_db()
    discount = conn.execute('''SELECT * FROM discount_codes WHERE code=? AND active=1 
        AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        AND (usage_limit IS NULL OR times_used < usage_limit)''', (code,)).fetchone()
    conn.close()
    
    if not discount:
        return jsonify({'error': 'Invalid or expired code'}), 400
    if subtotal < discount['min_order_amount']:
        return jsonify({'error': f"Min order ${discount['min_order_amount']:.2f} required"}), 400
    
    amt = subtotal * (discount['discount_percent'] / 100) if discount['discount_percent'] > 0 else discount['discount_amount']
    return jsonify({'valid': True, 'code': discount['code'], 'discount_id': discount['id'], 'discount_percent': discount['discount_percent'], 'discount_amount': round(amt, 2), 'message': f"{discount['discount_percent']}% off" if discount['discount_percent'] > 0 else f"${discount['discount_amount']:.2f} off"})

# ============================================
# ROUTES - ORDERS
# ============================================

@app.route('/api/orders', methods=['POST'])
@login_required
@verified_required
@rate_limit('order')
def create_order():
    data = request.json
    if not data.get('final_attestation'):
        return jsonify({'error': 'Attestation required'}), 400
    
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'No items'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    subtotal = 0
    order_items = []
    
    for item in items:
        product = c.execute('SELECT * FROM products WHERE id=? AND active=1', (item['product_id'],)).fetchone()
        if not product:
            conn.close()
            return jsonify({'error': f"Product {item['product_id']} not found"}), 400
        if product['stock'] < item['quantity']:
            conn.close()
            return jsonify({'error': f"Insufficient stock for {product['name']}"}), 400
        
        use_bulk = item.get('use_bulk', False) and product['price_bulk']
        price = product['price_bulk'] if use_bulk else product['price_single']
        subtotal += price * item['quantity']
        order_items.append({'product_id': product['id'], 'quantity': item['quantity'], 'unit_price': price, 'is_bulk': 1 if use_bulk else 0})
    
    discount_amount = 0
    discount_code_id = None
    
    if data.get('discount_code'):
        discount = c.execute('''SELECT * FROM discount_codes WHERE code=? AND active=1 
            AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            AND (usage_limit IS NULL OR times_used < usage_limit)''', (data['discount_code'].upper(),)).fetchone()
        if discount and subtotal >= discount['min_order_amount']:
            discount_code_id = discount['id']
            discount_amount = subtotal * (discount['discount_percent'] / 100) if discount['discount_percent'] > 0 else discount['discount_amount']
            c.execute('UPDATE discount_codes SET times_used=times_used+1 WHERE id=?', (discount['id'],))
    
    total = subtotal - discount_amount
    order_number = gen_order_num()
    
    c.execute('INSERT INTO orders (user_id,order_number,subtotal,discount_amount,discount_code_id,total,notes,shipping_address) VALUES (?,?,?,?,?,?,?,?)',
              (session['user_id'], order_number, subtotal, discount_amount, discount_code_id, total, data.get('notes', ''), data.get('shipping_address', '')))
    order_id = c.lastrowid
    
    for item in order_items:
        c.execute('INSERT INTO order_items (order_id,product_id,quantity,unit_price,is_bulk_price) VALUES (?,?,?,?,?)',
                  (order_id, item['product_id'], item['quantity'], item['unit_price'], item['is_bulk']))
        c.execute('UPDATE products SET stock=stock-? WHERE id=?', (item['quantity'], item['product_id']))
    
    c.execute('INSERT INTO acknowledgments (user_id,acknowledgment_type,ip_address,version_hash) VALUES (?,?,?,?)',
              (session['user_id'], 'checkout_attestation', request.remote_addr, get_ack_hash('checkout')))
    
    conn.commit()
    conn.close()
    
    send_order_confirmation(order_id)
    check_low_stock()
    
    return jsonify({'message': 'Order placed', 'order_number': order_number, 'order_id': order_id, 'subtotal': subtotal, 'discount': discount_amount, 'total': total, 'status': 'pending_payment'}), 201

@app.route('/api/orders', methods=['GET'])
@login_required
def get_orders():
    conn = get_db()
    orders = conn.execute('SELECT o.*,dc.code as discount_code FROM orders o LEFT JOIN discount_codes dc ON o.discount_code_id=dc.id WHERE o.user_id=? ORDER BY o.created_at DESC', (session['user_id'],)).fetchall()
    
    result = []
    for order in orders:
        items = conn.execute('SELECT oi.*,p.name,p.sku FROM order_items oi JOIN products p ON oi.product_id=p.id WHERE oi.order_id=?', (order['id'],)).fetchall()
        result.append({**dict(order), 'items': [dict(i) for i in items]})
    
    conn.close()
    return jsonify(result)

@app.route('/api/orders/<int:oid>/invoice', methods=['GET'])
@login_required
def download_invoice(oid):
    conn = get_db()
    order = conn.execute('SELECT user_id, order_number FROM orders WHERE id=?', (oid,)).fetchone()
    conn.close()
    
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if order['user_id'] != session['user_id']:
        conn = get_db()
        user = conn.execute('SELECT is_admin FROM users WHERE id=?', (session['user_id'],)).fetchone()
        conn.close()
        if not user or not user['is_admin']:
            return jsonify({'error': 'Access denied'}), 403
    
    try:
        pdf_buffer = generate_invoice_pdf(oid)
        if not pdf_buffer:
            return jsonify({'error': 'PDF generation requires reportlab: pip install reportlab'}), 500
        
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f"attachment; filename=invoice-{order['order_number']}.pdf"
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# ROUTES - ADMIN
# ============================================

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def admin_stats():
    conn = get_db()
    orders = conn.execute('SELECT COUNT(*) as count, SUM(total) as total FROM orders').fetchone()
    by_status = {r['status']: r['count'] for r in conn.execute('SELECT status, COUNT(*) as count FROM orders GROUP BY status').fetchall()}
    users = conn.execute('SELECT COUNT(*) as count FROM users WHERE is_admin=0').fetchone()
    products = conn.execute('SELECT COUNT(*) as count FROM products WHERE active=1').fetchone()
    recent = conn.execute('SELECT o.order_number,o.total,o.status,o.created_at,u.full_name,u.email FROM orders o JOIN users u ON o.user_id=u.id ORDER BY o.created_at DESC LIMIT 10').fetchall()
    low_stock = conn.execute('SELECT * FROM products WHERE stock <= ? AND active = 1', (CONFIG['LOW_STOCK_THRESHOLD'],)).fetchall()
    conn.close()
    
    return jsonify({'total_orders': orders['count'] or 0, 'total_revenue': orders['total'] or 0, 'orders_by_status': by_status, 'total_users': users['count'] or 0, 'total_products': products['count'] or 0, 'recent_orders': [dict(r) for r in recent], 'low_stock_items': [dict(p) for p in low_stock], 'low_stock_threshold': CONFIG['LOW_STOCK_THRESHOLD']})

@app.route('/api/admin/products', methods=['GET'])
@admin_required
def admin_get_products():
    conn = get_db()
    products = conn.execute('SELECT * FROM products ORDER BY sort_order,name').fetchall()
    conn.close()
    return jsonify([dict(p) for p in products])

@app.route('/api/admin/products', methods=['POST'])
@admin_required
def admin_add_product():
    data = request.json
    for f in ['sku', 'name', 'price_single']:
        if not data.get(f):
            return jsonify({'error': f'{f} required'}), 400
    
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO products (sku,name,description,price_single,price_bulk,bulk_quantity,stock,category,sort_order) VALUES (?,?,?,?,?,?,?,?,?)',
                  (data['sku'].upper(), data['name'], data.get('description', 'For research use only.'), data['price_single'], data.get('price_bulk'), data.get('bulk_quantity', 10), data.get('stock', 0), data.get('category'), data.get('sort_order', 0)))
        conn.commit()
        pid = c.lastrowid
        conn.close()
        return jsonify({'message': 'Product added', 'id': pid}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'SKU already exists'}), 400

@app.route('/api/admin/products/<int:pid>', methods=['PUT'])
@admin_required
def admin_update_product(pid):
    data = request.json
    conn = get_db()
    conn.execute('UPDATE products SET sku=?,name=?,description=?,price_single=?,price_bulk=?,bulk_quantity=?,stock=?,category=?,active=?,sort_order=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                 (data.get('sku','').upper(), data.get('name'), data.get('description'), data.get('price_single'), data.get('price_bulk'), data.get('bulk_quantity',10), data.get('stock',0), data.get('category'), 1 if data.get('active',True) else 0, data.get('sort_order',0), pid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Product updated'})

@app.route('/api/admin/products/<int:pid>', methods=['DELETE'])
@admin_required
def admin_delete_product(pid):
    conn = get_db()
    conn.execute('UPDATE products SET active=0 WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Product deactivated'})

@app.route('/api/admin/products/<int:pid>/restore', methods=['POST'])
@admin_required
def admin_restore_product(pid):
    conn = get_db()
    conn.execute('UPDATE products SET active=1 WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Product restored'})

@app.route('/api/admin/products/bulk-update-stock', methods=['POST'])
@admin_required
def admin_bulk_update_stock():
    data = request.json
    updates = data.get('updates', [])
    if not updates:
        return jsonify({'error': 'No updates'}), 400
    
    conn = get_db()
    updated = 0
    for u in updates:
        if 'id' in u and 'stock' in u:
            conn.execute('UPDATE products SET stock=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (u['stock'], u['id']))
            updated += 1
    conn.commit()
    conn.close()
    return jsonify({'message': f'{updated} products updated'})

@app.route('/api/admin/discount-codes', methods=['GET'])
@admin_required
def admin_get_codes():
    conn = get_db()
    codes = conn.execute('SELECT * FROM discount_codes ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(c) for c in codes])

@app.route('/api/admin/discount-codes', methods=['POST'])
@admin_required
def admin_add_code():
    data = request.json
    if not data.get('code'):
        return jsonify({'error': 'Code required'}), 400
    
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO discount_codes (code,description,discount_percent,discount_amount,min_order_amount,usage_limit,expires_at) VALUES (?,?,?,?,?,?,?)',
                  (data['code'].upper(), data.get('description',''), data.get('discount_percent',0), data.get('discount_amount',0), data.get('min_order_amount',0), data.get('usage_limit'), data.get('expires_at')))
        conn.commit()
        cid = c.lastrowid
        conn.close()
        return jsonify({'message': 'Code added', 'id': cid}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Code already exists'}), 400

@app.route('/api/admin/discount-codes/<int:cid>', methods=['PUT'])
@admin_required
def admin_update_code(cid):
    data = request.json
    conn = get_db()
    conn.execute('UPDATE discount_codes SET code=?,description=?,discount_percent=?,discount_amount=?,min_order_amount=?,usage_limit=?,active=?,expires_at=? WHERE id=?',
                 (data.get('code','').upper(), data.get('description',''), data.get('discount_percent',0), data.get('discount_amount',0), data.get('min_order_amount',0), data.get('usage_limit'), 1 if data.get('active',True) else 0, data.get('expires_at'), cid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Code updated'})

@app.route('/api/admin/discount-codes/<int:cid>', methods=['DELETE'])
@admin_required
def admin_delete_code(cid):
    conn = get_db()
    conn.execute('UPDATE discount_codes SET active=0 WHERE id=?', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Code deactivated'})

@app.route('/api/admin/orders', methods=['GET'])
@admin_required
def admin_get_orders():
    status = request.args.get('status')
    conn = get_db()
    query = 'SELECT o.*,u.full_name,u.email,u.phone,u.organization,dc.code as discount_code FROM orders o JOIN users u ON o.user_id=u.id LEFT JOIN discount_codes dc ON o.discount_code_id=dc.id'
    if status:
        query += f" WHERE o.status='{status}'"
    query += ' ORDER BY o.created_at DESC'
    
    orders = conn.execute(query).fetchall()
    result = []
    for order in orders:
        items = conn.execute('SELECT oi.*,p.name,p.sku FROM order_items oi JOIN products p ON oi.product_id=p.id WHERE oi.order_id=?', (order['id'],)).fetchall()
        result.append({**dict(order), 'items': [dict(i) for i in items]})
    
    conn.close()
    return jsonify(result)

@app.route('/api/admin/orders/<int:oid>/status', methods=['PUT'])
@admin_required
def admin_update_order_status(oid):
    data = request.json
    status = data.get('status')
    valid = ['pending', 'pending_payment', 'paid', 'processing', 'shipped', 'delivered', 'fulfilled', 'cancelled', 'refunded']
    if status not in valid:
        return jsonify({'error': f'Invalid status. Use: {", ".join(valid)}'}), 400
    
    conn = get_db()
    current = conn.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()
    if not current:
        conn.close()
        return jsonify({'error': 'Order not found'}), 404
    
    conn.execute('UPDATE orders SET status=?, admin_notes=?, tracking_number=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                 (status, data.get('admin_notes',''), data.get('tracking_number',''), oid))
    conn.commit()
    conn.close()
    
    if current['status'] != status:
        send_status_update(oid, status)
    
    return jsonify({'message': 'Status updated'})

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_get_users():
    conn = get_db()
    users = conn.execute('SELECT id,full_name,email,phone,organization,country,is_admin,email_verified,created_at FROM users ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/admin/users/<int:uid>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(uid):
    if uid == session['user_id']:
        return jsonify({'error': 'Cannot change own status'}), 400
    conn = get_db()
    conn.execute('UPDATE users SET is_admin = NOT is_admin WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Admin status toggled'})

@app.route('/api/admin/users/<int:uid>', methods=['PUT'])
@admin_required
def admin_update_user(uid):
    data = request.json
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    conn.execute('''UPDATE users SET 
        full_name=?, email=?, phone=?, organization=?, email_verified=?, updated_at=CURRENT_TIMESTAMP 
        WHERE id=?''',
        (data.get('full_name', user['full_name']),
         data.get('email', user['email']).lower(),
         data.get('phone', user['phone']),
         data.get('organization', user['organization']),
         1 if data.get('email_verified') else 0,
         uid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'User updated'})

@app.route('/api/admin/users/<int:uid>', methods=['DELETE'])
@admin_required
def admin_delete_user(uid):
    if uid == session['user_id']:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    
    conn = get_db()
    user = conn.execute('SELECT is_admin FROM users WHERE id=?', (uid,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    if user['is_admin']:
        conn.close()
        return jsonify({'error': 'Cannot delete admin users'}), 400
    
    # Delete user's orders and related data
    conn.execute('DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE user_id=?)', (uid,))
    conn.execute('DELETE FROM orders WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM acknowledgments WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM notification_log WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'User deleted'})

@app.route('/api/admin/notifications', methods=['GET'])
@admin_required
def admin_get_notifications():
    conn = get_db()
    notifs = conn.execute('SELECT n.*,u.full_name,u.email,o.order_number FROM notification_log n LEFT JOIN users u ON n.user_id=u.id LEFT JOIN orders o ON n.order_id=o.id ORDER BY n.created_at DESC LIMIT 100').fetchall()
    conn.close()
    return jsonify([dict(n) for n in notifs])

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("The Peptide Wizard - Ordering Platform")
    print("="*60)
    print(f"\n📧 Email: {'Resend' if CONFIG['RESEND_API_KEY'] else 'Mock mode'}")
    print(f"📱 SMS: {'Twilio' if CONFIG['TWILIO_ACCOUNT_SID'] else 'Mock mode'}")
    
    init_db()
    if import_products():
        print("✓ Products imported (43 items)")
    
    print("\n🌐 Customer: http://localhost:5000")
    print("🔧 Admin: http://localhost:5000/admin")
    print("🔑 Login: admin@admin.com / admin123")
    print("\n" + "="*60 + "\n")
    
    app.run(debug=True, port=5000)
