"""
Research Materials Ordering Platform - Production Ready
Flask Backend with Admin Dashboard, Notifications, Security, PDF Invoices
"""

from flask import Flask, request, jsonify, render_template, session, make_response, redirect
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
    'MAILGUN_API_KEY': os.environ.get('MAILGUN_API_KEY', ''),
    'MAILGUN_DOMAIN': os.environ.get('MAILGUN_DOMAIN', ''),
    'EMAIL_FROM': os.environ.get('EMAIL_FROM', 'orders@mail.thepeptidewizard.com'),
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

def is_postgres():
    """Check if using PostgreSQL"""
    database_url = CONFIG.get('DATABASE_URL', '')
    return database_url and database_url.startswith('postgres')

def get_raw_db():
    """Get raw database connection - uses PostgreSQL if DATABASE_URL is set, otherwise SQLite"""
    database_url = CONFIG.get('DATABASE_URL', '')
    
    if database_url and database_url.startswith('postgres'):
        import psycopg2
        import psycopg2.extras
        # Handle Railway's postgres:// vs postgresql://
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(database_url)
        return conn
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn

def dict_from_row(row, cursor=None):
    """Convert database row to dictionary"""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(row, 'keys'):
        return dict(row)
    if cursor and cursor.description:
        return dict(zip([col[0] for col in cursor.description], row))
    return dict(row)

class DBWrapper:
    """Wrapper to make PostgreSQL work like SQLite with ? placeholders"""
    def __init__(self, conn):
        self.conn = conn
        self._is_postgres = is_postgres()
    
    def execute(self, query, params=None):
        if self._is_postgres:
            import psycopg2.extras
            query = query.replace('?', '%s')
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cursor = self.conn.cursor()
        
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return DBCursor(cursor, self._is_postgres)
    
    def commit(self):
        self.conn.commit()
    
    def close(self):
        self.conn.close()

class DBCursor:
    """Cursor wrapper for consistent row access"""
    def __init__(self, cursor, is_postgres):
        self.cursor = cursor
        self._is_postgres = is_postgres
        self._lastrowid = None
    
    def execute(self, query, params=None):
        """Execute with automatic ? to %s conversion for PostgreSQL"""
        if self._is_postgres:
            query = query.replace('?', '%s')
            
            # Add RETURNING id for INSERT queries to get lastrowid
            query_upper = query.strip().upper()
            needs_returning = query_upper.startswith('INSERT') and 'RETURNING' not in query_upper
            if needs_returning:
                query = query.rstrip(';').rstrip() + ' RETURNING id'
        else:
            needs_returning = False
        
        if params:
            self.cursor.execute(query, params)
        else:
            self.cursor.execute(query)
        
        # For PostgreSQL, fetch the returned id
        if self._is_postgres and needs_returning:
            try:
                result = self.cursor.fetchone()
                if result and 'id' in result:
                    self._lastrowid = result['id']
            except:
                pass
        
        return self
    
    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        if self._is_postgres:
            return dict(row) if hasattr(row, 'keys') else row
        return row
    
    def fetchall(self):
        rows = self.cursor.fetchall()
        if self._is_postgres:
            return [dict(row) if hasattr(row, 'keys') else row for row in rows]
        return rows
    
    @property
    def lastrowid(self):
        if self._is_postgres:
            return self._lastrowid
        return self.cursor.lastrowid
    
    def set_lastrowid(self, val):
        self._lastrowid = val
    
    def __getattr__(self, name):
        return getattr(self.cursor, name)

class DBWrapper:
    """Wrapper to make PostgreSQL work like SQLite with ? placeholders"""
    def __init__(self, conn):
        self.conn = conn
        self._is_postgres = is_postgres()
    
    def execute(self, query, params=None):
        if self._is_postgres:
            import psycopg2.extras
            query = query.replace('?', '%s')
            
            # Add RETURNING id for INSERT queries to get lastrowid
            query_upper = query.strip().upper()
            needs_returning = query_upper.startswith('INSERT') and 'RETURNING' not in query_upper
            if needs_returning:
                query = query.rstrip(';').rstrip() + ' RETURNING id'
            
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cursor = self.conn.cursor()
            needs_returning = False
        
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
        wrapped = DBCursor(cursor, self._is_postgres)
        
        # For PostgreSQL, fetch the returned id
        if self._is_postgres and needs_returning:
            try:
                result = cursor.fetchone()
                if result and 'id' in result:
                    wrapped.set_lastrowid(result['id'])
            except:
                pass
        
        return wrapped
    
    def commit(self):
        self.conn.commit()
    
    def close(self):
        self.conn.close()
    
    def cursor(self):
        """Return wrapped cursor for compatibility"""
        if self._is_postgres:
            import psycopg2.extras
            return DBCursor(self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor), True)
        return DBCursor(self.conn.cursor(), False)

def get_wrapped_db():
    """Get wrapped database connection"""
    return DBWrapper(get_raw_db())

# Alias get_db to the wrapped version for backwards compatibility
def get_db():
    """Get database connection with automatic ? to %s conversion for PostgreSQL"""
    return get_wrapped_db()

def init_returns_table(c, using_postgres, auto_id):
    """Initialize returns and return_items tables"""
    c.execute(f'''CREATE TABLE IF NOT EXISTS returns (
        id {auto_id},
        order_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        reason_details TEXT,
        resolution_type TEXT,
        resolution_amount REAL DEFAULT 0,
        replacement_order_id INTEGER,
        status TEXT DEFAULT 'pending',
        admin_notes TEXT,
        processed_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        processed_at TIMESTAMP
    )''')
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS return_items (
        id {auto_id},
        return_id INTEGER NOT NULL,
        order_item_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        reason TEXT
    )''')
    
    print("✓ Returns tables initialized")

def init_db():
    using_postgres = is_postgres()
    conn = get_raw_db()
    c = conn.cursor()
    
    # Use appropriate syntax for each database
    if using_postgres:
        auto_id = 'SERIAL PRIMARY KEY'
    else:
        auto_id = 'INTEGER PRIMARY KEY AUTOINCREMENT'
    
    # Create tables with database-appropriate syntax
    c.execute(f'''CREATE TABLE IF NOT EXISTS users (
        id {auto_id},
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
        reset_token_expires TIMESTAMP,
        updated_at TIMESTAMP
    )''')
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS acknowledgments (
        id {auto_id},
        user_id INTEGER NOT NULL,
        acknowledgment_type TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ip_address TEXT,
        version_hash TEXT NOT NULL
    )''')
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS products (
        id {auto_id},
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
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS discount_codes (
        id {auto_id},
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
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS orders (
        id {auto_id},
        user_id INTEGER NOT NULL,
        order_number TEXT UNIQUE NOT NULL,
        subtotal REAL NOT NULL,
        discount_amount REAL DEFAULT 0,
        discount_code_id INTEGER DEFAULT NULL,
        shipping_cost REAL DEFAULT 0,
        delivery_method TEXT DEFAULT 'pickup',
        total REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        notes TEXT,
        admin_notes TEXT,
        shipping_address TEXT,
        tracking_number TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS order_items (
        id {auto_id},
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        is_bulk_price INTEGER DEFAULT 0
    )''')
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS notification_log (
        id {auto_id},
        user_id INTEGER,
        order_id INTEGER,
        notification_type TEXT NOT NULL,
        channel TEXT NOT NULL,
        recipient TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS inventory_receipts (
        id {auto_id},
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        received_date DATE NOT NULL,
        lot_number TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS rate_limits (
        id {auto_id},
        ip_address TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        request_count INTEGER DEFAULT 1,
        window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    try:
        c.execute('CREATE INDEX IF NOT EXISTS idx_rate_limits_ip ON rate_limits(ip_address, endpoint)')
    except:
        pass  # Index might already exist
    
    c.execute(f'''CREATE TABLE IF NOT EXISTS csrf_tokens (
        id {auto_id},
        token TEXT UNIQUE NOT NULL,
        session_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL
    )''')
    
    conn.commit()
    
    # Add columns if they don't exist (for existing databases)
    try:
        if using_postgres:
            c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_cost REAL DEFAULT 0")
            c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_method TEXT DEFAULT 'pickup'")
        else:
            # SQLite doesn't have IF NOT EXISTS for columns, so try/except
            try:
                c.execute("ALTER TABLE orders ADD COLUMN shipping_cost REAL DEFAULT 0")
            except:
                pass
            try:
                c.execute("ALTER TABLE orders ADD COLUMN delivery_method TEXT DEFAULT 'pickup'")
            except:
                pass
        conn.commit()
    except Exception as e:
        print(f"Note: Column migration skipped or already done: {e}")
    
    # Add cost column to products if it doesn't exist
    try:
        if using_postgres:
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS cost REAL DEFAULT 0")
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS reorder_qty INTEGER DEFAULT 4")
        else:
            try:
                c.execute("ALTER TABLE products ADD COLUMN cost REAL DEFAULT 0")
            except:
                pass
            try:
                c.execute("ALTER TABLE products ADD COLUMN reorder_qty INTEGER DEFAULT 4")
            except:
                pass
        conn.commit()
    except Exception as e:
        print(f"Note: Column migration: {e}")
    
    # Fix any NULL active fields
    try:
        c.execute("UPDATE products SET active = 1 WHERE active IS NULL")
        conn.commit()
    except Exception as e:
        print(f"Note: Active field fix: {e}")
    
    # Add sale price columns to products
    try:
        if using_postgres:
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_price REAL DEFAULT NULL")
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_start TIMESTAMP DEFAULT NULL")
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_end TIMESTAMP DEFAULT NULL")
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_min_qty INTEGER DEFAULT 1")
        else:
            try:
                c.execute("ALTER TABLE products ADD COLUMN sale_price REAL DEFAULT NULL")
            except:
                pass
            try:
                c.execute("ALTER TABLE products ADD COLUMN sale_start TIMESTAMP DEFAULT NULL")
            except:
                pass
            try:
                c.execute("ALTER TABLE products ADD COLUMN sale_end TIMESTAMP DEFAULT NULL")
            except:
                pass
            try:
                c.execute("ALTER TABLE products ADD COLUMN sale_min_qty INTEGER DEFAULT 1")
            except:
                pass
        conn.commit()
    except Exception as e:
        print(f"Note: Sale columns migration: {e}")
    
    # Create email_blasts table for tracking sent emails
    try:
        c.execute(f'''CREATE TABLE IF NOT EXISTS email_blasts (
            id {auto_id},
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            recipients_count INTEGER DEFAULT 0,
            sent_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
    except Exception as e:
        print(f"Note: Email blasts table: {e}")
    
    # Create referral_transactions table
    try:
        c.execute(f'''CREATE TABLE IF NOT EXISTS referral_transactions (
            id {auto_id},
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
    except Exception as e:
        print(f"Note: Referral transactions table: {e}")
    
    # Add referral columns to discount_codes and users
    try:
        if using_postgres:
            c.execute("ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS referrer_user_id INTEGER DEFAULT NULL")
            c.execute("ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS commission_percent REAL DEFAULT 20")
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_credit REAL DEFAULT 0")
            c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS credit_applied REAL DEFAULT 0")
        else:
            try:
                c.execute("ALTER TABLE discount_codes ADD COLUMN referrer_user_id INTEGER DEFAULT NULL")
            except:
                pass
            try:
                c.execute("ALTER TABLE discount_codes ADD COLUMN commission_percent REAL DEFAULT 20")
            except:
                pass
            try:
                c.execute("ALTER TABLE users ADD COLUMN referral_credit REAL DEFAULT 0")
            except:
                pass
            try:
                c.execute("ALTER TABLE orders ADD COLUMN credit_applied REAL DEFAULT 0")
            except:
                pass
        conn.commit()
    except Exception as e:
        print(f"Note: Referral column migration: {e}")
    
    # Initialize returns tables
    try:
        init_returns_table(c, using_postgres, auto_id)
        conn.commit()
    except Exception as e:
        print(f"Note: Returns tables: {e}")
    
    # Create default admin if none exists
    if using_postgres:
        import psycopg2.extras
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute('SELECT COUNT(*) as count FROM users WHERE is_admin = 1')
        count = cursor.fetchone()['count']
    else:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_admin = 1')
        count = cursor.fetchone()[0]
    
    if count == 0:
        admin_pw = generate_password_hash('admin123')
        if using_postgres:
            cursor.execute('''INSERT INTO users (full_name, email, phone, country, password_hash, is_admin, first_login_confirmed, email_verified) 
                         VALUES (%s,%s,%s,%s,%s,1,1,1)''',
                      ('Admin', 'admin@admin.com', '0000000000', 'US', admin_pw))
        else:
            cursor.execute('''INSERT INTO users (full_name, email, phone, country, password_hash, is_admin, first_login_confirmed, email_verified) 
                         VALUES (?,?,?,?,?,1,1,1)''',
                      ('Admin', 'admin@admin.com', '0000000000', 'US', admin_pw))
        conn.commit()
        print("✓ Default admin: admin@admin.com / admin123")
    
    conn.close()
    print(f"✓ Database initialized ({'PostgreSQL' if using_postgres else 'SQLite'})")

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
    try:
        # Check if products exist
        result = conn.execute('SELECT COUNT(*) as cnt FROM products').fetchone()
        count = result['cnt'] if isinstance(result, dict) else result[0]
        if count > 0:
            print(f"Products already exist ({count}), skipping import")
            conn.close()
            return False
        
        desc = "This material is supplied for laboratory research purposes only. NOT for human or animal consumption."
        for i, (sku, name, p1, p2, cat) in enumerate(products):
            conn.execute('INSERT INTO products (sku,name,description,price_single,price_bulk,bulk_quantity,stock,category,sort_order) VALUES (?,?,?,?,?,10,100,?,?)',
                      (sku, name, desc, p1, p2, cat, i))
        
        codes = [
            ('RESEARCH10', '10% off orders $50+', 10, 0, 50, 100), 
            ('FIRST20', '20% off first order', 20, 0, 0, 50), 
            ('BULK15', '15% off orders $200+', 15, 0, 200, None)
        ]
        for code, d, pct, amt, minord, lim in codes:
            try:
                conn.execute('INSERT INTO discount_codes (code,description,discount_percent,discount_amount,min_order_amount,usage_limit) VALUES (?,?,?,?,?,?)',
                          (code, d, pct, amt, minord, lim))
            except: pass
        
        conn.commit()
        conn.close()
        print(f"✓ Products imported ({len(products)} items)")
        return True
    except Exception as e:
        print(f"Import products error: {e}")
        try:
            conn.close()
        except:
            pass
        return False

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
        count = result['request_count'] if isinstance(result, dict) or hasattr(result, 'keys') else result[0]
        if count >= max_requests:
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
    if not CONFIG['MAILGUN_API_KEY'] or not CONFIG['MAILGUN_DOMAIN']:
        print(f"[EMAIL MOCK] To: {to}, Subject: {subject}")
        return True, "Mock sent"
    try:
        import requests
        print(f"[EMAIL] Sending to {to}: {subject}")
        r = requests.post(
            f"https://api.mailgun.net/v3/{CONFIG['MAILGUN_DOMAIN']}/messages",
            auth=("api", CONFIG['MAILGUN_API_KEY']),
            data={
                "from": CONFIG['EMAIL_FROM'],
                "to": [to],
                "subject": subject,
                "html": html
            })
        print(f"[EMAIL] Response: {r.status_code} - {r.text}")
        return r.status_code == 200, r.text
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
    url = f"{CONFIG['APP_URL']}/verify?token={token}"
    html = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333;">
    <h2 style="color:#2d3748;">Verify Your Research Account</h2>
    <p>Thank you for creating a research account with The Peptide Wizard.</p>
    <p>Please verify your email address to activate your account:</p>
    <p style="text-align:center;margin:30px 0;">
        <a href="{url}" style="background:#3b82f6;color:white;padding:14px 28px;border-radius:8px;text-decoration:none;display:inline-block;font-weight:600;">Verify Email</a>
    </p>
    <p style="color:#666;font-size:13px;">This link expires in 24 hours.</p>
    <hr style="border:none;border-top:1px solid #eee;margin:30px 0;"/>
    <p style="color:#666;font-size:12px;line-height:1.6;">
        <strong>Reminder:</strong> All materials offered by The Peptide Wizard are designated 
        <strong>Research Use Only</strong> and are not intended for human or veterinary use.
    </p>
    </body></html>"""
    return send_email(email, "Verify Your Research Account – The Peptide Wizard", html)

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
    url = f"{CONFIG['APP_URL']}/#reset={token}"
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
        # Check email verification
        conn = get_db()
        user = conn.execute('SELECT email_verified FROM users WHERE id=?', (session['user_id'],)).fetchone()
        conn.close()
        
        if not user:
            print(f"[VERIFIED CHECK] User {session['user_id']} not found")
            return jsonify({'error': 'Please verify your email first', 'code': 'EMAIL_NOT_VERIFIED'}), 403
        
        verified = user['email_verified'] if isinstance(user, dict) else user[0]
        print(f"[VERIFIED CHECK] User {session['user_id']} email_verified = {verified}")
        
        if not verified:
            return jsonify({'error': 'Please verify your email first', 'code': 'EMAIL_NOT_VERIFIED'}), 403
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

# RUO Acknowledgment version - update this if terms change
RUO_ACKNOWLEDGMENT_VERSION = "v1.0-2026-01"
RUO_ACKNOWLEDGMENT_TEXT = """By creating an account with The Peptide Wizard, I acknowledge and agree to the following:
- All products offered are Research Use Only (RUO) materials.
- Products are not intended for human or veterinary use, including but not limited to injection, ingestion, or topical application.
- I am purchasing these materials solely for legitimate research, analytical, or educational purposes.
- I understand that The Peptide Wizard does not provide medical advice, dosing guidance, or instructions for human use.
- I accept full responsibility for ensuring that my purchase, handling, and use of these materials complies with all applicable local, state, and federal laws and regulations.
- I acknowledge that misuse of these materials is strictly prohibited."""

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
    
    # Require RUO acknowledgment
    if not data.get('ruo_acknowledged'):
        return jsonify({'error': 'You must accept the Research Use Only terms to create an account.'}), 400
    
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
    
    # Log RUO acknowledgment for compliance audit trail
    c.execute('INSERT INTO acknowledgments (user_id,acknowledgment_type,ip_address,version_hash) VALUES (?,?,?,?)',
              (user_id, 'ruo_registration', request.remote_addr, get_ack_hash(RUO_ACKNOWLEDGMENT_VERSION)))
    print(f"[COMPLIANCE] User {user_id} accepted RUO terms at registration - IP: {request.remote_addr}, Version: {RUO_ACKNOWLEDGMENT_VERSION}")
    
    conn.commit()
    conn.close()
    
    send_verification_email(data['email'].lower(), verify_token)
    
    session['user_id'] = user_id
    return jsonify({'message': 'Registration successful. Please check your email to verify.', 'user_id': user_id, 'requires_first_login_confirmation': True, 'email_verified': False}), 201

@app.route('/api/verify-email/<token>', methods=['POST'])
def verify_email(token):
    try:
        conn = get_db()
        
        result = conn.execute('SELECT id, email FROM users WHERE email_verify_token = ?', (token,))
        user = result.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'error': 'Invalid or expired verification link'}), 400
        
        user_id = user['id'] if isinstance(user, dict) else user[0]
        
        conn.execute('UPDATE users SET email_verified = 1, email_verify_token = NULL, email_verify_expires = NULL WHERE id = ?', (user_id,))
        
        conn.commit()
        conn.close()
        print(f"[EMAIL VERIFY] User {user_id} email verified successfully")
        return jsonify({'message': 'Email verified successfully!'})
    except Exception as e:
        print(f"[EMAIL VERIFY ERROR] {str(e)}")
        return jsonify({'error': 'Verification failed'}), 500

@app.route('/verify', methods=['GET'])
def verify_email_page():
    token = request.args.get('token')
    print(f"[EMAIL VERIFY] Received verification request with token: {token[:20] if token else 'None'}...")
    
    if not token:
        return redirect('/?error=missing_token')
    
    try:
        conn = get_db()
        
        # First check if token exists at all
        result = conn.execute('SELECT id, email FROM users WHERE email_verify_token = ?', (token,))
        user = result.fetchone()
        
        if not user:
            print(f"[EMAIL VERIFY] Token not found in database")
            conn.close()
            return redirect('/?error=invalid_token')
        
        user_id = user['id'] if isinstance(user, dict) else user[0]
        print(f"[EMAIL VERIFY] Found user {user_id}, updating verified status")
        
        # Update email_verified to 1
        conn.execute('UPDATE users SET email_verified = 1, email_verify_token = NULL, email_verify_expires = NULL WHERE id = ?', (user_id,))
        conn.commit()
        
        # Verify the update worked
        check = conn.execute('SELECT email_verified FROM users WHERE id = ?', (user_id,)).fetchone()
        verified_status = check['email_verified'] if isinstance(check, dict) else check[0]
        print(f"[EMAIL VERIFY] User {user_id} email_verified is now: {verified_status}")
        
        conn.close()
        return redirect('/?verified=1')
    except Exception as e:
        print(f"[EMAIL VERIFY ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect('/?error=verification_failed')

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
    print(f"[LOGIN] Attempt for email: {data.get('email')}")
    if not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Email and password required'}), 400
    
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (data['email'].lower(),)).fetchone()
    conn.close()
    
    if not user:
        print(f"[LOGIN] User not found: {data.get('email')}")
        return jsonify({'error': 'Invalid credentials'}), 401
    
    if not check_password_hash(user['password_hash'], data['password']):
        print(f"[LOGIN] Wrong password for: {data.get('email')}")
        return jsonify({'error': 'Invalid credentials'}), 401
    
    session['user_id'] = user['id']
    print(f"[LOGIN] Success for user {user['id']}: {user['email']}")
    return jsonify({'message': 'Login successful', 'user': {'id': user['id'], 'full_name': user['full_name'], 'email': user['email'], 'is_admin': bool(user['is_admin']), 'first_login_confirmed': bool(user['first_login_confirmed']), 'email_verified': bool(user['email_verified'])}})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'message': 'Logged out'})

@app.route('/api/me', methods=['GET'])
@login_required
def get_me():
    conn = get_db()
    user = conn.execute('SELECT id,full_name,email,phone,organization,country,is_admin,first_login_confirmed,email_verified,referral_credit FROM users WHERE id=?', (session['user_id'],)).fetchone()
    conn.close()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(dict(user))

@app.route('/api/my-referrals', methods=['GET'])
@login_required
def get_my_referrals():
    """Get user's referral transactions and stats"""
    conn = get_db()
    
    # Get user's credit balance
    user = conn.execute('SELECT referral_credit FROM users WHERE id=?', (session['user_id'],)).fetchone()
    
    # Get referral transactions
    transactions = conn.execute('''
        SELECT rt.*, o.order_number 
        FROM referral_transactions rt 
        LEFT JOIN orders o ON rt.order_id = o.id
        WHERE rt.user_id = ?
        ORDER BY rt.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Get total earned and used
    totals = conn.execute('''
        SELECT 
            COALESCE(SUM(CASE WHEN type = 'earned' THEN amount ELSE 0 END), 0) as total_earned,
            COALESCE(SUM(CASE WHEN type = 'used' THEN ABS(amount) ELSE 0 END), 0) as total_used
        FROM referral_transactions WHERE user_id = ?
    ''', (session['user_id'],)).fetchone()
    
    conn.close()
    
    return jsonify({
        'credit_balance': float(user['referral_credit'] or 0) if user else 0,
        'total_earned': float(totals['total_earned'] or 0),
        'total_used': float(totals['total_used'] or 0),
        'transactions': [dict(t) for t in transactions]
    })

@app.route('/api/confirm-first-login', methods=['POST'])
@login_required
def confirm_first_login():
    conn = get_db()
    c = conn.cursor()
    
    # Log first login reaffirmation for compliance
    c.execute('INSERT INTO acknowledgments (user_id,acknowledgment_type,ip_address,version_hash) VALUES (?,?,?,?)',
              (session['user_id'], 'ruo_first_login_reaffirmation', request.remote_addr, get_ack_hash(RUO_ACKNOWLEDGMENT_VERSION)))
    print(f"[COMPLIANCE] User {session['user_id']} reaffirmed RUO terms at first login - IP: {request.remote_addr}")
    
    c.execute('UPDATE users SET first_login_confirmed=1 WHERE id=?', (session['user_id'],))
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
    products = conn.execute('''SELECT id,sku,name,description,price_single,price_bulk,bulk_quantity,stock,category,
        sale_price,sale_start,sale_end,sale_min_qty FROM products WHERE active=1 ORDER BY sort_order,name''').fetchall()
    conn.close()
    
    # Process products to add sale_active flag (within date range)
    result = []
    now = datetime.now()
    for p in products:
        prod = dict(p)
        # Check if product sale is active (within date range)
        sale_active = False
        if prod.get('sale_price') and prod['sale_price'] > 0:
            sale_start = prod.get('sale_start')
            sale_end = prod.get('sale_end')
            
            # Parse dates if they're strings
            if sale_start and isinstance(sale_start, str):
                try:
                    sale_start = datetime.fromisoformat(sale_start.replace('Z', '+00:00').replace('+00:00', ''))
                except:
                    sale_start = None
            if sale_end and isinstance(sale_end, str):
                try:
                    sale_end = datetime.fromisoformat(sale_end.replace('Z', '+00:00').replace('+00:00', ''))
                except:
                    sale_end = None
            
            # Check if within sale period
            start_ok = sale_start is None or now >= sale_start
            end_ok = sale_end is None or now <= sale_end
            sale_active = start_ok and end_ok
        
        prod['sale_active'] = sale_active  # Sale is within date range
        prod['sale_min_qty'] = prod.get('sale_min_qty') or 1
        prod['is_on_sale'] = sale_active  # For backward compatibility (frontend checks qty)
        prod['effective_price'] = prod['sale_price'] if sale_active else prod['price_single']
        result.append(prod)
    
    return jsonify(result)

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
    
    if not discount:
        conn.close()
        return jsonify({'error': 'Invalid or expired code'}), 400
    if subtotal < discount['min_order_amount']:
        conn.close()
        return jsonify({'error': f"Min order ${discount['min_order_amount']:.2f} required"}), 400
    
    # Check if cart has sale items - discount only applies to non-sale items
    cart_items = data.get('cart_items', [])
    has_sale_items = False
    non_sale_subtotal = subtotal  # Default to full subtotal if no cart info
    
    if cart_items:
        non_sale_subtotal = 0
        now = datetime.now()
        for item in cart_items:
            product = conn.execute('SELECT * FROM products WHERE id=?', (item.get('product_id'),)).fetchone()
            if product:
                qty = item.get('quantity', 1)
                
                # Check if on sale AND meets minimum quantity
                is_on_sale = False
                if product['sale_price'] and product['sale_price'] > 0:
                    sale_min_qty = product['sale_min_qty'] or 1
                    if qty >= sale_min_qty:
                        sale_start = product['sale_start']
                        sale_end = product['sale_end']
                        if sale_start and isinstance(sale_start, str):
                            try:
                                sale_start = datetime.fromisoformat(sale_start.replace('Z', '+00:00').replace('+00:00', ''))
                            except:
                                sale_start = None
                        if sale_end and isinstance(sale_end, str):
                            try:
                                sale_end = datetime.fromisoformat(sale_end.replace('Z', '+00:00').replace('+00:00', ''))
                            except:
                                sale_end = None
                        start_ok = sale_start is None or now >= sale_start
                        end_ok = sale_end is None or now <= sale_end
                        is_on_sale = start_ok and end_ok
                
                if is_on_sale:
                    has_sale_items = True
                else:
                    # Add non-sale item value to discountable subtotal
                    if product['price_bulk'] and qty >= product['bulk_quantity']:
                        price = product['price_bulk'] / product['bulk_quantity']
                    else:
                        price = product['price_single']
                    non_sale_subtotal += price * qty
    
    conn.close()
    
    # Calculate discount on non-sale items only
    if discount['discount_percent'] > 0:
        amt = non_sale_subtotal * (discount['discount_percent'] / 100)
    else:
        amt = min(discount['discount_amount'], non_sale_subtotal)  # Don't exceed non-sale subtotal
    
    # Check if user is the referrer for this code (handle type conversion)
    referrer_id = discount['referrer_user_id']
    current_user_id = session.get('user_id')
    is_own_code = False
    commission_percent = 0
    
    if referrer_id is not None and current_user_id is not None:
        is_own_code = int(referrer_id) == int(current_user_id)
        commission_percent = float(discount['commission_percent'] or 20)
    
    # Calculate combined discount if it's their own code
    combined_percent = discount['discount_percent'] + commission_percent if is_own_code else 0
    combined_amount = non_sale_subtotal * (combined_percent / 100) if combined_percent > 0 else 0
    
    # Build message
    if has_sale_items and non_sale_subtotal < subtotal:
        if non_sale_subtotal > 0:
            message = f"{discount['discount_percent']}% off (applies to non-sale items only)" if discount['discount_percent'] > 0 else f"${amt:.2f} off (non-sale items)"
        else:
            message = "All items are on sale - code not applicable"
            amt = 0
    else:
        message = f"{discount['discount_percent']}% off" if discount['discount_percent'] > 0 else f"${discount['discount_amount']:.2f} off"
    
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
        'non_sale_subtotal': round(non_sale_subtotal, 2)
    })

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
    now = datetime.now()
    
    for item in items:
        product = c.execute('SELECT * FROM products WHERE id=? AND active=1', (item['product_id'],)).fetchone()
        if not product:
            conn.close()
            return jsonify({'error': f"Product {item['product_id']} not found"}), 400
        if product['stock'] < item['quantity']:
            conn.close()
            return jsonify({'error': f"Insufficient stock for {product['name']}"}), 400
        
        qty = item['quantity']
        
        # Check if product is on sale AND meets minimum quantity
        is_on_sale = False
        if product['sale_price'] and product['sale_price'] > 0:
            sale_min_qty = product['sale_min_qty'] or 1
            if qty >= sale_min_qty:
                sale_start = product['sale_start']
                sale_end = product['sale_end']
                
                # Parse dates if they're strings
                if sale_start and isinstance(sale_start, str):
                    try:
                        sale_start = datetime.fromisoformat(sale_start.replace('Z', '+00:00').replace('+00:00', ''))
                    except:
                        sale_start = None
                if sale_end and isinstance(sale_end, str):
                    try:
                        sale_end = datetime.fromisoformat(sale_end.replace('Z', '+00:00').replace('+00:00', ''))
                    except:
                        sale_end = None
                
                start_ok = sale_start is None or now >= sale_start
                end_ok = sale_end is None or now <= sale_end
                is_on_sale = start_ok and end_ok
        
        # Calculate pricing - check sale first, then bulk, then single
        if is_on_sale:
            # Sale price takes priority (already verified qty >= sale_min_qty)
            price_per_item = product['sale_price']
            item_subtotal = price_per_item * qty
            use_bulk = False
        elif product['price_bulk'] and qty >= product['bulk_quantity']:
            # Bulk pricing: price_bulk is total for bulk_quantity items
            price_per_item = product['price_bulk'] / product['bulk_quantity']
            item_subtotal = price_per_item * qty
            use_bulk = True
        else:
            price_per_item = product['price_single']
            item_subtotal = product['price_single'] * qty
            use_bulk = False
        
        subtotal += item_subtotal
        order_items.append({'product_id': product['id'], 'quantity': qty, 'unit_price': price_per_item, 'is_bulk': 1 if use_bulk else 0})
    
    discount_amount = 0
    discount_code_id = None
    referrer_user_id = None
    commission_percent = 20
    is_own_code = False
    referrer_choice = data.get('referrer_choice', 'split')  # 'combined' or 'split'
    
    if data.get('discount_code'):
        discount = c.execute('''SELECT * FROM discount_codes WHERE code=? AND active=1 
            AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            AND (usage_limit IS NULL OR times_used < usage_limit)''', (data['discount_code'].upper(),)).fetchone()
        if discount and subtotal >= discount['min_order_amount']:
            discount_code_id = discount['id']
            c.execute('UPDATE discount_codes SET times_used=times_used+1 WHERE id=?', (discount['id'],))
            
            # Check if this is a referral code and if it's their own code
            if discount['referrer_user_id']:
                referrer_user_id = discount['referrer_user_id']
                commission_percent = discount['commission_percent'] or 20
                is_own_code = (referrer_user_id == session['user_id'])
            
            # Calculate discount based on whether it's their own code and their choice
            if is_own_code and referrer_choice == 'combined':
                # Give them full discount (discount + commission combined)
                combined_percent = discount['discount_percent'] + commission_percent
                discount_amount = subtotal * (combined_percent / 100)
            else:
                # Normal discount
                discount_amount = subtotal * (discount['discount_percent'] / 100) if discount['discount_percent'] > 0 else discount['discount_amount']
    
    # Handle delivery method and shipping cost
    delivery_method = data.get('delivery_method', 'pickup')
    shipping_cost = 20.0 if delivery_method == 'ship' else 0.0
    
    # Handle credit application
    credit_applied = 0
    if data.get('apply_credit'):
        user = c.execute('SELECT referral_credit FROM users WHERE id=?', (session['user_id'],)).fetchone()
        available_credit = float(user['referral_credit'] or 0) if user else 0
        if available_credit > 0:
            # Calculate how much credit can be applied (up to subtotal after discount + shipping)
            max_credit = subtotal - discount_amount + shipping_cost
            credit_applied = min(available_credit, max_credit)
    
    total = subtotal - discount_amount + shipping_cost - credit_applied
    if total < 0:
        total = 0
    order_number = gen_order_num()
    
    c.execute('INSERT INTO orders (user_id,order_number,subtotal,discount_amount,discount_code_id,shipping_cost,delivery_method,credit_applied,total,notes,shipping_address) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
              (session['user_id'], order_number, subtotal, discount_amount, discount_code_id, shipping_cost, delivery_method, credit_applied, total, data.get('notes', ''), data.get('shipping_address', '')))
    order_id = c.lastrowid
    
    for item in order_items:
        c.execute('INSERT INTO order_items (order_id,product_id,quantity,unit_price,is_bulk_price) VALUES (?,?,?,?,?)',
                  (order_id, item['product_id'], item['quantity'], item['unit_price'], item['is_bulk']))
        c.execute('UPDATE products SET stock=stock-? WHERE id=?', (item['quantity'], item['product_id']))
    
    # Deduct credit if applied
    if credit_applied > 0:
        c.execute('UPDATE users SET referral_credit = referral_credit - ? WHERE id=?', (credit_applied, session['user_id']))
        c.execute('INSERT INTO referral_transactions (user_id, order_id, type, amount, description) VALUES (?,?,?,?,?)',
                  (session['user_id'], order_id, 'used', -credit_applied, f'Applied to order {order_number}'))
    
    # Credit the referrer if this is a referral order
    # - If it's someone else's order: credit the referrer
    # - If it's their own order with 'split' choice: credit themselves
    credit_earned = 0
    if referrer_user_id:
        if referrer_user_id != session['user_id']:
            # Someone else used the code - credit the referrer
            commission = subtotal * (commission_percent / 100)
            c.execute('UPDATE users SET referral_credit = referral_credit + ? WHERE id=?', (commission, referrer_user_id))
            c.execute('INSERT INTO referral_transactions (user_id, order_id, type, amount, description) VALUES (?,?,?,?,?)',
                      (referrer_user_id, order_id, 'earned', commission, f'Commission from order {order_number}'))
        elif is_own_code and referrer_choice == 'split':
            # They used their own code and chose to split - credit themselves
            commission = subtotal * (commission_percent / 100)
            credit_earned = commission
            c.execute('UPDATE users SET referral_credit = referral_credit + ? WHERE id=?', (commission, session['user_id']))
            c.execute('INSERT INTO referral_transactions (user_id, order_id, type, amount, description) VALUES (?,?,?,?,?)',
                      (session['user_id'], order_id, 'earned', commission, f'Self-referral credit from order {order_number}'))
    
    c.execute('INSERT INTO acknowledgments (user_id,acknowledgment_type,ip_address,version_hash) VALUES (?,?,?,?)',
              (session['user_id'], 'checkout_attestation', request.remote_addr, get_ack_hash('checkout')))
    
    conn.commit()
    conn.close()
    
    send_order_confirmation(order_id)
    check_low_stock()
    
    return jsonify({'message': 'Order placed', 'order_number': order_number, 'order_id': order_id, 'subtotal': subtotal, 'discount': discount_amount, 'credit_applied': credit_applied, 'credit_earned': credit_earned, 'shipping_cost': shipping_cost, 'delivery_method': delivery_method, 'total': total, 'status': 'pending_payment'}), 201

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
    # Exclude cancelled/refunded orders from revenue
    orders = conn.execute("SELECT COUNT(*) as count, SUM(total) as total FROM orders WHERE status NOT IN ('cancelled', 'refunded')").fetchone()
    by_status = {r['status']: r['count'] for r in conn.execute('SELECT status, COUNT(*) as count FROM orders GROUP BY status').fetchall()}
    users = conn.execute('SELECT COUNT(*) as count FROM users WHERE is_admin=0').fetchone()
    products = conn.execute('SELECT COUNT(*) as count FROM products WHERE active=1').fetchone()
    recent = conn.execute('SELECT o.order_number,o.total,o.status,o.created_at,u.full_name,u.email FROM orders o JOIN users u ON o.user_id=u.id ORDER BY o.created_at DESC LIMIT 10').fetchall()
    
    # Low stock: products where stock < (reorder_qty * 10) AND reorder_qty > 0
    low_stock = conn.execute('''
        SELECT * FROM products 
        WHERE active = 1 
        AND reorder_qty > 0 
        AND stock < (reorder_qty * 10)
    ''').fetchall()
    conn.close()
    
    return jsonify({'total_orders': orders['count'] or 0, 'total_revenue': orders['total'] or 0, 'orders_by_status': by_status, 'total_users': users['count'] or 0, 'total_products': products['count'] or 0, 'recent_orders': [dict(r) for r in recent], 'low_stock_items': [dict(p) for p in low_stock]})

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
        c.execute('INSERT INTO products (sku,name,description,price_single,price_bulk,bulk_quantity,stock,category,sort_order,cost,reorder_qty) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (data['sku'].upper(), data['name'], data.get('description', 'For research use only.'), data['price_single'], data.get('price_bulk'), data.get('bulk_quantity', 10), data.get('stock', 0), data.get('category'), data.get('sort_order', 0), data.get('cost', 0), data.get('reorder_qty', 4)))
        conn.commit()
        pid = c.lastrowid
        conn.close()
        return jsonify({'message': 'Product added', 'id': pid}), 201
    except Exception as e:
        conn.close()
        if 'UNIQUE' in str(e).upper() or 'duplicate' in str(e).lower():
            return jsonify({'error': 'SKU already exists'}), 400
        return jsonify({'error': str(e)}), 400

@app.route('/api/admin/products/<int:pid>', methods=['PUT'])
@admin_required
def admin_update_product(pid):
    data = request.json
    conn = get_db()
    
    # Handle sale dates - convert empty strings to None
    sale_price = data.get('sale_price')
    if sale_price == '' or sale_price == 0:
        sale_price = None
    
    sale_start = data.get('sale_start')
    if sale_start == '':
        sale_start = None
    
    sale_end = data.get('sale_end')
    if sale_end == '':
        sale_end = None
    
    sale_min_qty = data.get('sale_min_qty')
    if sale_min_qty == '' or sale_min_qty is None:
        sale_min_qty = 1
    
    conn.execute('''UPDATE products SET sku=?,name=?,description=?,price_single=?,price_bulk=?,bulk_quantity=?,
        stock=?,category=?,active=?,sort_order=?,cost=?,reorder_qty=?,sale_price=?,sale_start=?,sale_end=?,sale_min_qty=?,
        updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                 (data.get('sku','').upper(), data.get('name'), data.get('description'), data.get('price_single'), 
                  data.get('price_bulk'), data.get('bulk_quantity',10), data.get('stock',0), data.get('category'), 
                  1 if data.get('active',True) else 0, data.get('sort_order',0), data.get('cost',0), 
                  data.get('reorder_qty',4), sale_price, sale_start, sale_end, int(sale_min_qty), pid))
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

@app.route('/api/admin/products/bulk-update-costs', methods=['POST'])
@admin_required
def admin_bulk_update_costs():
    """Bulk update product costs from CSV data (SKU, Cost)"""
    data = request.json
    costs = data.get('costs', [])
    
    if not costs:
        return jsonify({'error': 'No costs data provided'}), 400
    
    conn = get_db()
    updated = 0
    not_found = []
    
    for item in costs:
        sku = str(item.get('sku', '')).strip().upper()
        cost = item.get('cost', 0)
        
        if not sku:
            continue
            
        try:
            cost = float(cost) if cost else 0
        except:
            continue
        
        # Try to find and update the product
        result = conn.execute('SELECT id FROM products WHERE UPPER(sku) = ?', (sku,)).fetchone()
        if result:
            conn.execute('UPDATE products SET cost = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (cost, result['id']))
            updated += 1
        else:
            not_found.append(sku)
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'message': f'{updated} products updated',
        'updated': updated,
        'not_found': not_found
    })

@app.route('/api/admin/extract-pdf', methods=['POST'])
@admin_required
def admin_extract_pdf():
    """Extract tables from a PDF file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'File must be a PDF'}), 400
    
    try:
        import pdfplumber
    except ImportError:
        return jsonify({'error': 'PDF extraction requires pdfplumber. Install with: pip install pdfplumber'}), 500
    
    try:
        all_rows = []
        columns = []
        page_count = 0
        
        with pdfplumber.open(file) as pdf:
            page_count = len(pdf.pages)
            
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    
                    for i, row in enumerate(table):
                        if not row:
                            continue
                        
                        # Clean up cells
                        clean_row = []
                        for cell in row:
                            if cell is None:
                                clean_row.append('')
                            else:
                                # Clean up whitespace and newlines
                                clean_row.append(str(cell).replace('\n', ' ').strip())
                        
                        # First table's first row becomes column headers
                        if len(columns) == 0 and len(all_rows) == 0:
                            columns = clean_row
                        else:
                            # Only add rows with same column count
                            if len(clean_row) == len(columns):
                                all_rows.append(clean_row)
                            elif len(columns) == 0:
                                # No headers yet, use this row's length
                                columns = [f'Column {i+1}' for i in range(len(clean_row))]
                                all_rows.append(clean_row)
        
        if len(all_rows) == 0:
            return jsonify({'error': 'No tables found in PDF'}), 400
        
        return jsonify({
            'columns': columns,
            'rows': all_rows,
            'pages': page_count
        })
        
    except Exception as e:
        print(f"[ERROR] PDF extraction: {str(e)}")
        return jsonify({'error': f'Failed to extract PDF: {str(e)}'}), 500

# ============================================
# EMAIL BLAST
# ============================================

@app.route('/api/admin/email-blast/preview', methods=['POST'])
@admin_required
def admin_email_blast_preview():
    """Get list of users for email blast selection"""
    conn = get_db()
    users = conn.execute('SELECT id, full_name, email FROM users WHERE email_verified=1 AND is_admin=0 ORDER BY full_name').fetchall()
    conn.close()
    return jsonify({
        'recipient_count': len(users),
        'users': [dict(u) for u in users]
    })

@app.route('/api/admin/email-blast/send', methods=['POST'])
@admin_required
def admin_email_blast_send():
    """Send email blast to selected users"""
    data = request.json
    subject = data.get('subject', '').strip()
    body = data.get('body', '').strip()
    user_ids = data.get('user_ids', [])  # Empty = all users
    
    if not subject or not body:
        return jsonify({'error': 'Subject and body are required'}), 400
    
    conn = get_db()
    
    # Get users - either selected ones or all verified non-admin users
    if user_ids and len(user_ids) > 0:
        placeholders = ','.join(['?' for _ in user_ids])
        users = conn.execute(f'SELECT id, email, full_name FROM users WHERE id IN ({placeholders}) AND email_verified=1', user_ids).fetchall()
    else:
        users = conn.execute('SELECT id, email, full_name FROM users WHERE email_verified=1 AND is_admin=0').fetchall()
    
    if not users:
        conn.close()
        return jsonify({'error': 'No users to send to'}), 400
    
    # Log the email blast
    c = conn.cursor()
    c.execute('INSERT INTO email_blasts (subject, body, recipients_count, sent_by) VALUES (?,?,?,?)',
              (subject, body, len(users), session.get('user_id')))
    blast_id = c.lastrowid
    conn.commit()
    
    # Send emails
    sent = 0
    failed = 0
    
    for user in users:
        try:
            # Personalize the email
            personalized_body = body.replace('{{name}}', user['full_name'] or 'Valued Customer')
            personalized_body = personalized_body.replace('{{email}}', user['email'])
            
            # Build HTML email
            html_body = f'''
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                    <h1 style="color: white; margin: 0;">🧪 The Peptide Wizard</h1>
                </div>
                <div style="padding: 30px; background: #f7fafc;">
                    {personalized_body.replace(chr(10), '<br>')}
                </div>
                <div style="padding: 20px; text-align: center; color: #718096; font-size: 12px;">
                    <p>The Peptide Wizard - Research Peptides</p>
                    <p><a href="{os.environ.get('APP_URL', 'https://thepeptidewizard.com')}" style="color: #667eea;">Visit our store</a></p>
                </div>
            </div>
            '''
            
            send_email(user['email'], subject, html_body)
            sent += 1
        except Exception as e:
            print(f"[ERROR] Failed to send to {user['email']}: {e}")
            failed += 1
    
    conn.close()
    
    return jsonify({
        'message': f'Email blast sent',
        'sent': sent,
        'failed': failed,
        'blast_id': blast_id
    })

@app.route('/api/admin/email-blast/history', methods=['GET'])
@admin_required
def admin_email_blast_history():
    """Get history of sent email blasts"""
    conn = get_db()
    blasts = conn.execute('''SELECT eb.*, u.full_name as sent_by_name 
        FROM email_blasts eb LEFT JOIN users u ON eb.sent_by = u.id 
        ORDER BY eb.created_at DESC LIMIT 50''').fetchall()
    conn.close()
    return jsonify([dict(b) for b in blasts])

@app.route('/api/admin/reports/financial', methods=['GET'])
@admin_required
def admin_financial_report():
    """Get financial report with costs, revenue, and margins"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    conn = get_db()
    
    # Build date filter
    date_filter = "1=1"
    if start_date and end_date:
        date_filter = f"DATE(o.created_at) >= '{start_date}' AND DATE(o.created_at) <= '{end_date}'"
    
    # Get order summary excluding cancelled/refunded
    orders_query = f'''
        SELECT 
            COUNT(*) as total_orders,
            COALESCE(SUM(o.total), 0) as gross_revenue,
            COALESCE(SUM(o.discount_amount), 0) as total_discounts,
            COALESCE(SUM(o.shipping_cost), 0) as shipping_collected
        FROM orders o
        WHERE o.status NOT IN ('cancelled', 'refunded')
        AND {date_filter}
    '''
    orders = conn.execute(orders_query).fetchone()
    
    # Get COGS (cost of goods sold) from order items
    cogs_query = f'''
        SELECT COALESCE(SUM(oi.quantity * p.cost), 0) as cogs
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN products p ON oi.product_id = p.id
        WHERE o.status NOT IN ('cancelled', 'refunded')
        AND {date_filter}
    '''
    cogs = conn.execute(cogs_query).fetchone()
    
    # Get product-level breakdown
    product_query = f'''
        SELECT 
            p.sku,
            p.name,
            p.cost,
            p.price_single,
            SUM(oi.quantity) as units_sold,
            SUM(oi.quantity * oi.unit_price) as revenue,
            SUM(oi.quantity * p.cost) as cost_of_goods,
            SUM(oi.quantity * (oi.unit_price - p.cost)) as gross_profit
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN products p ON oi.product_id = p.id
        WHERE o.status NOT IN ('cancelled', 'refunded')
        AND {date_filter}
        GROUP BY p.id, p.sku, p.name, p.cost, p.price_single
        ORDER BY gross_profit DESC
    '''
    products = conn.execute(product_query).fetchall()
    
    # Get current inventory value
    inventory = conn.execute('SELECT SUM(stock * cost) as inventory_value, SUM(stock) as total_units FROM products WHERE active = 1').fetchone()
    
    conn.close()
    
    gross_revenue = float(orders['gross_revenue'] or 0)
    total_cogs = float(cogs['cogs'] or 0)
    gross_profit = gross_revenue - total_cogs
    
    return jsonify({
        'summary': {
            'total_orders': orders['total_orders'] or 0,
            'gross_revenue': gross_revenue,
            'total_discounts': float(orders['total_discounts'] or 0),
            'shipping_collected': float(orders['shipping_collected'] or 0),
            'cogs': total_cogs,
            'gross_profit': gross_profit,
            'gross_margin_pct': (gross_profit / gross_revenue * 100) if gross_revenue > 0 else 0
        },
        'inventory': {
            'total_value': float(inventory['inventory_value'] or 0),
            'total_units': inventory['total_units'] or 0
        },
        'products': [dict(p) for p in products],
        'start_date': start_date,
        'end_date': end_date
    })

@app.route('/api/admin/reports/inventory', methods=['GET'])
@admin_required
def admin_inventory_report():
    """Get inventory report with reorder recommendations based on per-product reorder_qty"""
    order_threshold = float(request.args.get('order_threshold', 1000))  # Minimum order value
    
    conn = get_db()
    
    # Get all active products with their stock, costs, and reorder quantities
    products = conn.execute('''
        SELECT id, sku, name, stock, cost, price_single, price_bulk, reorder_qty
        FROM products 
        WHERE active = 1
        ORDER BY sku
    ''').fetchall()
    
    conn.close()
    
    total_units = 0
    inventory_cost = 0
    potential_revenue = 0
    needs_reorder = []
    all_products = []
    
    for p in products:
        stock = p['stock'] or 0
        cost = float(p['cost'] or 0)
        price = float(p['price_single'] or 0)
        reorder_qty = p['reorder_qty'] if p['reorder_qty'] is not None else 4  # Default to 4 boxes
        min_units = reorder_qty * 10  # Convert boxes to units
        
        total_units += stock
        inventory_cost += stock * cost
        potential_revenue += stock * price
        
        # Add to all products list for display
        all_products.append({
            'sku': p['sku'],
            'name': p['name'],
            'stock': stock,
            'cost': cost,
            'reorder_qty': reorder_qty,
            'min_units': min_units
        })
        
        # Check if needs reorder (below minimum AND reorder_qty > 0)
        if reorder_qty > 0 and stock < min_units and cost > 0:
            # Calculate how many boxes to order to get back to minimum
            units_needed = min_units - stock
            boxes_to_order = max(1, (units_needed + 9) // 10)  # Round up to nearest box
            
            # Order cost is boxes * (cost per unit * 10 units per box)
            order_cost = boxes_to_order * cost * 10
            
            needs_reorder.append({
                'sku': p['sku'],
                'name': p['name'],
                'stock': stock,
                'cost': cost,
                'reorder_qty': reorder_qty,
                'min_units': min_units,
                'boxes_to_order': boxes_to_order,
                'order_cost': order_cost
            })
    
    return jsonify({
        'total_units': total_units,
        'inventory_cost': inventory_cost,
        'potential_revenue': potential_revenue,
        'needs_reorder': needs_reorder,
        'all_products': all_products,
        'order_threshold': order_threshold
    })

@app.route('/api/admin/reports/orders', methods=['GET'])
@admin_required
def admin_orders_report():
    """Get order summary report with date range"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    conn = get_db()
    
    # Build date filter
    date_filter = "1=1"
    if start_date and end_date:
        date_filter = f"DATE(created_at) >= '{start_date}' AND DATE(created_at) <= '{end_date}'"
    
    # Get totals
    totals = conn.execute(f'''
        SELECT COUNT(*) as total_orders, COALESCE(SUM(total), 0) as total_revenue
        FROM orders WHERE {date_filter}
    ''').fetchone()
    
    # Get by status
    by_status = conn.execute(f'''
        SELECT status, COUNT(*) as count, COALESCE(SUM(total), 0) as total
        FROM orders WHERE {date_filter}
        GROUP BY status ORDER BY count DESC
    ''').fetchall()
    
    conn.close()
    
    return jsonify({
        'total_orders': totals['total_orders'] or 0,
        'total_revenue': float(totals['total_revenue'] or 0),
        'by_status': [dict(s) for s in by_status],
        'start_date': start_date,
        'end_date': end_date
    })

@app.route('/api/admin/reports/discounts', methods=['GET'])
@admin_required
def admin_discounts_report():
    """Get discount usage report with date range"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    conn = get_db()
    
    # Build date filter
    date_filter = "1=1"
    if start_date and end_date:
        date_filter = f"DATE(o.created_at) >= '{start_date}' AND DATE(o.created_at) <= '{end_date}'"
    
    # Get usage by code
    usage = conn.execute(f'''
        SELECT dc.code,
               COUNT(*) as times_used,
               COALESCE(SUM(o.discount_amount), 0) as total_discount,
               COALESCE(SUM(o.total), 0) as total_revenue
        FROM orders o
        JOIN discount_codes dc ON o.discount_code_id = dc.id
        WHERE o.status != 'cancelled' AND {date_filter}
        GROUP BY dc.code
        ORDER BY times_used DESC
    ''').fetchall()
    
    # Get totals
    totals = conn.execute(f'''
        SELECT COUNT(*) as total_orders_with_discount,
               COALESCE(SUM(o.discount_amount), 0) as total_discount_given,
               COALESCE(SUM(o.total), 0) as total_revenue
        FROM orders o
        WHERE o.discount_code_id IS NOT NULL
        AND o.status != 'cancelled'
        AND {date_filter}
    ''').fetchone()
    
    conn.close()
    
    return jsonify({
        'usage': [dict(u) for u in usage],
        'totals': dict(totals) if totals else {},
        'start_date': start_date,
        'end_date': end_date
    })

@app.route('/api/admin/reports/referrals', methods=['GET'])
@admin_required
def admin_referrals_report():
    """Get referral report for all referrers or a specific one"""
    referrer_id = request.args.get('referrer_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    conn = get_db()
    
    # Build date filter
    date_filter = "1=1"
    if start_date and end_date:
        date_filter = f"DATE(rt.created_at) >= '{start_date}' AND DATE(rt.created_at) <= '{end_date}'"
    
    if referrer_id:
        # Get specific referrer's report
        user = conn.execute('SELECT id, full_name, email, referral_credit FROM users WHERE id=?', (referrer_id,)).fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        
        # Get their transactions
        transactions = conn.execute(f'''
            SELECT rt.*, o.order_number, o.subtotal as order_subtotal
            FROM referral_transactions rt 
            LEFT JOIN orders o ON rt.order_id = o.id
            WHERE rt.user_id = ? AND {date_filter}
            ORDER BY rt.created_at DESC
        ''', (referrer_id,)).fetchall()
        
        # Get totals
        totals = conn.execute(f'''
            SELECT 
                COALESCE(SUM(CASE WHEN type = 'earned' THEN amount ELSE 0 END), 0) as total_earned,
                COALESCE(SUM(CASE WHEN type = 'used' THEN ABS(amount) ELSE 0 END), 0) as total_used,
                COUNT(CASE WHEN type = 'earned' THEN 1 END) as referral_count
            FROM referral_transactions 
            WHERE user_id = ? AND {date_filter}
        ''', (referrer_id,)).fetchone()
        
        # Get their discount code
        code = conn.execute('SELECT code FROM discount_codes WHERE referrer_user_id = ?', (referrer_id,)).fetchone()
        
        conn.close()
        
        return jsonify({
            'referrer': dict(user),
            'code': code['code'] if code else None,
            'transactions': [dict(t) for t in transactions],
            'totals': {
                'total_earned': float(totals['total_earned'] or 0),
                'total_used': float(totals['total_used'] or 0),
                'current_balance': float(user['referral_credit'] or 0),
                'referral_count': totals['referral_count'] or 0
            },
            'start_date': start_date,
            'end_date': end_date
        })
    else:
        # Get summary for all referrers
        referrers = conn.execute('''
            SELECT u.id, u.full_name, u.email, u.referral_credit,
                   dc.code,
                   (SELECT COALESCE(SUM(amount), 0) FROM referral_transactions WHERE user_id = u.id AND type = 'earned') as total_earned,
                   (SELECT COUNT(*) FROM referral_transactions WHERE user_id = u.id AND type = 'earned') as referral_count
            FROM users u
            JOIN discount_codes dc ON dc.referrer_user_id = u.id
            ORDER BY total_earned DESC
        ''').fetchall()
        
        conn.close()
        
        return jsonify({
            'referrers': [dict(r) for r in referrers]
        })

@app.route('/api/admin/discount-codes', methods=['GET'])
@admin_required
def admin_get_codes():
    conn = get_db()
    codes = conn.execute('''
        SELECT dc.*, u.full_name as referrer_name, u.email as referrer_email
        FROM discount_codes dc
        LEFT JOIN users u ON dc.referrer_user_id = u.id
        ORDER BY dc.created_at DESC
    ''').fetchall()
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
        c.execute('INSERT INTO discount_codes (code,description,discount_percent,discount_amount,min_order_amount,usage_limit,expires_at,referrer_user_id,commission_percent) VALUES (?,?,?,?,?,?,?,?,?)',
                  (data['code'].upper(), data.get('description',''), data.get('discount_percent',0), data.get('discount_amount',0), data.get('min_order_amount',0), data.get('usage_limit'), data.get('expires_at'), data.get('referrer_user_id'), data.get('commission_percent', 20)))
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
    conn.execute('UPDATE discount_codes SET code=?,description=?,discount_percent=?,discount_amount=?,min_order_amount=?,usage_limit=?,active=?,expires_at=?,referrer_user_id=?,commission_percent=? WHERE id=?',
                 (data.get('code','').upper(), data.get('description',''), data.get('discount_percent',0), data.get('discount_amount',0), data.get('min_order_amount',0), data.get('usage_limit'), 1 if data.get('active',True) else 0, data.get('expires_at'), data.get('referrer_user_id'), data.get('commission_percent', 20), cid))
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

@app.route('/api/admin/discount-codes/<int:cid>/permanent', methods=['DELETE'])
@admin_required
def admin_permanent_delete_code(cid):
    """Permanently delete a discount code - only if never used"""
    conn = get_db()
    
    # Check if code has been used
    code = conn.execute('SELECT times_used FROM discount_codes WHERE id=?', (cid,)).fetchone()
    if not code:
        conn.close()
        return jsonify({'error': 'Discount code not found'}), 404
    
    if code['times_used'] > 0:
        conn.close()
        return jsonify({'error': 'Cannot delete a discount code that has been used. Deactivate it instead.'}), 400
    
    conn.execute('DELETE FROM discount_codes WHERE id=?', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Discount code permanently deleted'})

@app.route('/api/admin/inventory-receipts', methods=['GET'])
@admin_required
def admin_get_inventory_receipts():
    """Get all inventory receipts with product names"""
    conn = get_db()
    receipts = conn.execute('''
        SELECT ir.*, p.name as product_name, p.sku
        FROM inventory_receipts ir
        JOIN products p ON ir.product_id = p.id
        ORDER BY ir.received_date DESC, ir.created_at DESC
        LIMIT 100
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in receipts])

@app.route('/api/admin/inventory-receipts', methods=['POST'])
@admin_required
def admin_create_inventory_receipt():
    """Create inventory receipt and update product stock"""
    data = request.json
    
    product_id = data.get('product_id')
    quantity = data.get('quantity')
    received_date = data.get('received_date')
    lot_number = data.get('lot_number')
    notes = data.get('notes', '')
    
    if not product_id or not quantity or not received_date:
        return jsonify({'error': 'product_id, quantity, and received_date are required'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    # Generate lot number if not provided
    if not lot_number:
        product = conn.execute('SELECT sku FROM products WHERE id=?', (product_id,)).fetchone()
        if product:
            sku = product['sku']
            date_str = received_date.replace('-', '')
            import random
            random_suffix = random.randint(100, 999)
            lot_number = f"{sku}-{date_str}-{random_suffix}"
    
    # Create receipt record
    c.execute('''INSERT INTO inventory_receipts (product_id, quantity, received_date, lot_number, notes)
                 VALUES (?, ?, ?, ?, ?)''', (product_id, quantity, received_date, lot_number, notes))
    
    # Update product stock
    c.execute('UPDATE products SET stock = stock + ? WHERE id = ?', (quantity, product_id))
    
    conn.commit()
    conn.close()
    
    print(f"[INVENTORY] Received {quantity} units for product {product_id}, Lot: {lot_number}")
    
    return jsonify({
        'message': 'Inventory received and stock updated',
        'lot_number': lot_number
    }), 201

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


@app.route('/api/admin/orders/<int:oid>/edit', methods=['PUT'])
@admin_required
def admin_edit_order(oid):
    """Admin can edit order - add discount code, adjust discount amount, shipping, etc."""
    data = request.json
    
    conn = get_db()
    c = conn.cursor()
    
    # Get current order
    order = c.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
    if not order:
        conn.close()
        return jsonify({'error': 'Order not found'}), 404
    
    order_dict = dict(order)
    subtotal = float(order_dict['subtotal'] or 0)
    
    # Track what changed for notes
    changes = []
    
    # Handle discount code application
    new_discount_code_id = order_dict.get('discount_code_id')
    new_discount_amount = float(order_dict.get('discount_amount') or 0)
    
    if 'discount_code' in data and data['discount_code']:
        # Look up the discount code
        code = data['discount_code'].upper().strip()
        discount = c.execute('''SELECT * FROM discount_codes WHERE code=? AND active=1''', (code,)).fetchone()
        
        if discount:
            discount_dict = dict(discount)
            new_discount_code_id = discount_dict['id']
            
            # Calculate discount
            if discount_dict['discount_percent'] and discount_dict['discount_percent'] > 0:
                new_discount_amount = subtotal * (discount_dict['discount_percent'] / 100)
            else:
                new_discount_amount = float(discount_dict['discount_amount'] or 0)
            
            # Increment usage count
            c.execute('UPDATE discount_codes SET times_used = times_used + 1 WHERE id = ?', (discount_dict['id'],))
            changes.append(f"Applied discount code {code}")
        else:
            conn.close()
            return jsonify({'error': f'Discount code "{code}" not found or inactive'}), 400
    
    # Handle manual discount amount override
    elif 'manual_discount' in data:
        manual = float(data['manual_discount'] or 0)
        if manual != new_discount_amount:
            changes.append(f"Discount adjusted from ${new_discount_amount:.2f} to ${manual:.2f}")
            new_discount_amount = manual
    
    # Handle shipping cost adjustment
    new_shipping = float(order_dict.get('shipping_cost') or 0)
    if 'shipping_cost' in data:
        new_ship = float(data['shipping_cost'] or 0)
        if new_ship != new_shipping:
            changes.append(f"Shipping adjusted from ${new_shipping:.2f} to ${new_ship:.2f}")
            new_shipping = new_ship
    
    # Calculate new total
    credit_applied = float(order_dict.get('credit_applied') or 0)
    new_total = subtotal - new_discount_amount + new_shipping - credit_applied
    if new_total < 0:
        new_total = 0
    
    old_total = float(order_dict.get('total') or 0)
    if abs(new_total - old_total) > 0.01:
        changes.append(f"Total changed from ${old_total:.2f} to ${new_total:.2f}")
    
    # Build admin notes
    admin_notes = order_dict.get('admin_notes') or ''
    edit_note = data.get('edit_note', '')
    
    if changes:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        change_log = f"\n[EDITED {timestamp}] " + "; ".join(changes)
        if edit_note:
            change_log += f" - Note: {edit_note}"
        admin_notes = (admin_notes + change_log).strip()
    
    # Update the order
    c.execute('''UPDATE orders SET 
        discount_code_id = ?,
        discount_amount = ?,
        shipping_cost = ?,
        total = ?,
        admin_notes = ?,
        updated_at = CURRENT_TIMESTAMP
        WHERE id = ?''', 
        (new_discount_code_id, new_discount_amount, new_shipping, new_total, admin_notes, oid))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'message': 'Order updated successfully',
        'changes': changes,
        'new_total': new_total,
        'discount_amount': new_discount_amount,
        'shipping_cost': new_shipping
    })

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_get_users():
    try:
        conn = get_db()
        result = conn.execute('SELECT id,full_name,email,phone,organization,country,is_admin,email_verified,created_at,referral_credit FROM users ORDER BY created_at DESC')
        rows = result.fetchall()
        conn.close()
        
        # Convert rows to plain dicts
        users = []
        for row in rows:
            if isinstance(row, dict):
                users.append(row)
            elif hasattr(row, 'keys'):
                users.append({k: row[k] for k in row.keys()})
            else:
                # SQLite Row object
                users.append(dict(row))
        
        return jsonify(users)
    except Exception as e:
        print(f"[ERROR] admin_get_users: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<int:uid>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(uid):
    if uid == session['user_id']:
        return jsonify({'error': 'Cannot change own status'}), 400
    conn = get_db()
    # Get current status first
    user = conn.execute('SELECT is_admin FROM users WHERE id=?', (uid,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    new_status = 0 if user['is_admin'] else 1
    conn.execute('UPDATE users SET is_admin=? WHERE id=?', (new_status, uid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Admin status toggled'})

@app.route('/api/admin/users/<int:uid>/resend-verification', methods=['POST'])
@admin_required
def admin_resend_verification(uid):
    conn = get_db()
    result = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not result:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    # Convert to dict for consistent access
    if isinstance(result, dict):
        user = result
    elif hasattr(result, 'keys'):
        user = {k: result[k] for k in result.keys()}
    else:
        user = dict(result)
    
    if user.get('email_verified'):
        conn.close()
        return jsonify({'error': 'User already verified'}), 400
    
    # Generate new verification token
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=24)
    
    conn.execute('UPDATE users SET email_verify_token=?, email_verify_expires=? WHERE id=?', 
                 (token, expires, uid))
    conn.commit()
    conn.close()
    
    # Send verification email
    verify_url = f"{CONFIG['APP_URL']}/verify?token={token}"
    send_email(
        user['email'],
        'Verify Your Email - Research Materials',
        f'''<h2>Email Verification</h2>
        <p>Hi {user['full_name']},</p>
        <p>Please click the link below to verify your email address:</p>
        <p><a href="{verify_url}" style="display:inline-block;padding:12px 24px;background:#4299e1;color:white;text-decoration:none;border-radius:6px;">Verify Email</a></p>
        <p>Or copy this link: {verify_url}</p>
        <p>This link expires in 24 hours.</p>'''
    )
    
    return jsonify({'message': 'Verification email sent'})

@app.route('/api/admin/users/<int:uid>', methods=['PUT'])
@admin_required
def admin_update_user(uid):
    data = request.json
    try:
        conn = get_db()
        result = conn.execute('SELECT * FROM users WHERE id=?', (uid,))
        user = result.fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        
        # Handle both dict and Row objects
        if isinstance(user, dict):
            user_dict = user
        elif hasattr(user, 'keys'):
            user_dict = {k: user[k] for k in user.keys()}
        else:
            user_dict = dict(user)
        
        # Get the new credit value, defaulting to current value
        new_credit = data.get('referral_credit')
        if new_credit is not None:
            new_credit = float(new_credit)
        else:
            new_credit = float(user_dict.get('referral_credit') or 0)
        
        conn.execute('''UPDATE users SET 
            full_name=?, email=?, phone=?, organization=?, email_verified=?, referral_credit=?, updated_at=CURRENT_TIMESTAMP 
            WHERE id=?''',
            (data.get('full_name', user_dict.get('full_name')),
             data.get('email', user_dict.get('email', '')).lower(),
             data.get('phone', user_dict.get('phone')),
             data.get('organization', user_dict.get('organization')),
             1 if data.get('email_verified') else 0,
             new_credit,
             uid))
        conn.commit()
        conn.close()
        return jsonify({'message': 'User updated'})
    except Exception as e:
        print(f"[ERROR] admin_update_user: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<int:uid>', methods=['DELETE'])
@admin_required
def admin_delete_user(uid):
    if uid == session['user_id']:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    
    try:
        conn = get_db()
        result = conn.execute('SELECT is_admin FROM users WHERE id=?', (uid,))
        user = result.fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        
        is_admin = user['is_admin'] if isinstance(user, dict) else user[0]
        if is_admin:
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
    except Exception as e:
        print(f"[ERROR] admin_delete_user: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/notifications', methods=['GET'])
@admin_required
def admin_get_notifications():
    conn = get_db()
    notifs = conn.execute('SELECT n.*,u.full_name,u.email,o.order_number FROM notification_log n LEFT JOIN users u ON n.user_id=u.id LEFT JOIN orders o ON n.order_id=o.id ORDER BY n.created_at DESC LIMIT 100').fetchall()
    conn.close()
    return jsonify([dict(n) for n in notifs])

# ============================================
# RETURNS & CREDIT SYSTEM
# ============================================

@app.route('/api/returns/eligible-orders', methods=['GET'])
def get_eligible_orders():
    """Get customer's orders eligible for returns (last 90 days, fulfilled/delivered)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Please log in'}), 401
    
    conn = get_db()
    
    # Get orders from last 90 days that are fulfilled or delivered
    if is_postgres():
        orders = conn.execute('''
            SELECT o.id, o.order_number, o.total, o.status, o.created_at,
                   (SELECT COUNT(*) FROM returns r WHERE r.order_id = o.id AND r.status != 'denied') as existing_returns
            FROM orders o 
            WHERE o.user_id = %s 
              AND o.status IN ('fulfilled', 'delivered', 'shipped')
              AND o.created_at > NOW() - INTERVAL '90 days'
            ORDER BY o.created_at DESC
        ''', (session['user_id'],)).fetchall()
    else:
        orders = conn.execute('''
            SELECT o.id, o.order_number, o.total, o.status, o.created_at,
                   (SELECT COUNT(*) FROM returns r WHERE r.order_id = o.id AND r.status != 'denied') as existing_returns
            FROM orders o 
            WHERE o.user_id = ? 
              AND o.status IN ('fulfilled', 'delivered', 'shipped')
              AND o.created_at > datetime('now', '-90 days')
            ORDER BY o.created_at DESC
        ''', (session['user_id'],)).fetchall()
    
    result = []
    for order in orders:
        order_dict = dict(order) if hasattr(order, 'keys') else {
            'id': order[0], 'order_number': order[1], 'total': order[2],
            'status': order[3], 'created_at': str(order[4]), 'existing_returns': order[5]
        }
        
        # Get order items
        items = conn.execute('''
            SELECT oi.id as order_item_id, oi.product_id, oi.quantity, oi.unit_price,
                   p.name, p.sku
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?
        '''.replace('?', '%s') if is_postgres() else '''
            SELECT oi.id as order_item_id, oi.product_id, oi.quantity, oi.unit_price,
                   p.name, p.sku
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?
        ''', (order_dict['id'],)).fetchall()
        
        order_dict['items'] = [dict(i) if hasattr(i, 'keys') else {
            'order_item_id': i[0], 'product_id': i[1], 'quantity': i[2],
            'unit_price': i[3], 'name': i[4], 'sku': i[5]
        } for i in items]
        
        result.append(order_dict)
    
    conn.close()
    return jsonify(result)


@app.route('/api/returns/submit', methods=['POST'])
def submit_return_request():
    """Customer submits a return/credit request"""
    if 'user_id' not in session:
        return jsonify({'error': 'Please log in'}), 401
    
    data = request.json
    order_id = data.get('order_id')
    reason = data.get('reason')
    reason_details = data.get('reason_details', '')
    items = data.get('items', [])
    
    if not order_id or not reason:
        return jsonify({'error': 'Order and reason are required'}), 400
    
    if not items:
        return jsonify({'error': 'Please select at least one item'}), 400
    
    conn = get_db()
    
    # Verify order belongs to user and is eligible
    order = conn.execute('''
        SELECT id, order_number, user_id, status FROM orders 
        WHERE id = ? AND user_id = ? AND status IN ('fulfilled', 'delivered', 'shipped')
    '''.replace('?', '%s') if is_postgres() else '''
        SELECT id, order_number, user_id, status FROM orders 
        WHERE id = ? AND user_id = ? AND status IN ('fulfilled', 'delivered', 'shipped')
    ''', (order_id, session['user_id'])).fetchone()
    
    if not order:
        conn.close()
        return jsonify({'error': 'Order not found or not eligible for return'}), 404
    
    # Check for existing pending return on this order
    existing = conn.execute('''
        SELECT id FROM returns WHERE order_id = ? AND status = 'pending'
    '''.replace('?', '%s') if is_postgres() else '''
        SELECT id FROM returns WHERE order_id = ? AND status = 'pending'
    ''', (order_id,)).fetchone()
    
    if existing:
        conn.close()
        return jsonify({'error': 'A return request is already pending for this order'}), 400
    
    # Create return request
    result = conn.execute('''
        INSERT INTO returns (order_id, user_id, reason, reason_details, status)
        VALUES (?, ?, ?, ?, 'pending')
    '''.replace('?', '%s') if is_postgres() else '''
        INSERT INTO returns (order_id, user_id, reason, reason_details, status)
        VALUES (?, ?, ?, ?, 'pending')
    ''', (order_id, session['user_id'], reason, reason_details))
    
    return_id = result.lastrowid
    
    # Add return items
    for item in items:
        conn.execute('''
            INSERT INTO return_items (return_id, order_item_id, product_id, quantity, reason)
            VALUES (?, ?, ?, ?, ?)
        '''.replace('?', '%s') if is_postgres() else '''
            INSERT INTO return_items (return_id, order_item_id, product_id, quantity, reason)
            VALUES (?, ?, ?, ?, ?)
        ''', (return_id, item['order_item_id'], item['product_id'], item['quantity'], item.get('reason', '')))
    
    conn.commit()
    
    order_number = order['order_number'] if hasattr(order, 'keys') else order[1]
    
    conn.close()
    
    return jsonify({
        'message': 'Return request submitted successfully',
        'return_id': return_id,
        'order_number': order_number
    }), 201


@app.route('/api/returns/my-requests', methods=['GET'])
def get_my_returns():
    """Get customer's return requests"""
    if 'user_id' not in session:
        return jsonify({'error': 'Please log in'}), 401
    
    conn = get_db()
    returns = conn.execute('''
        SELECT r.*, o.order_number 
        FROM returns r
        JOIN orders o ON r.order_id = o.id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
    '''.replace('?', '%s') if is_postgres() else '''
        SELECT r.*, o.order_number 
        FROM returns r
        JOIN orders o ON r.order_id = o.id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    result = []
    for ret in returns:
        ret_dict = dict(ret) if hasattr(ret, 'keys') else ret
        
        # Get return items
        items = conn.execute('''
            SELECT ri.*, p.name, p.sku
            FROM return_items ri
            JOIN products p ON ri.product_id = p.id
            WHERE ri.return_id = ?
        '''.replace('?', '%s') if is_postgres() else '''
            SELECT ri.*, p.name, p.sku
            FROM return_items ri
            JOIN products p ON ri.product_id = p.id
            WHERE ri.return_id = ?
        ''', (ret_dict['id'],)).fetchall()
        
        ret_dict['items'] = [dict(i) if hasattr(i, 'keys') else i for i in items]
        result.append(ret_dict)
    
    conn.close()
    return jsonify(result)


@app.route('/api/admin/returns', methods=['GET'])
@admin_required
def admin_get_returns():
    """Get all return requests for admin"""
    conn = get_db()
    
    status_filter = request.args.get('status', '')
    
    query = '''
        SELECT r.*, o.order_number, o.total as order_total, 
               u.full_name, u.email
        FROM returns r
        JOIN orders o ON r.order_id = o.id
        JOIN users u ON r.user_id = u.id
    '''
    
    params = ()
    if status_filter:
        query += " WHERE r.status = ?"
        params = (status_filter,)
    
    query += ' ORDER BY r.created_at DESC'
    
    if is_postgres():
        query = query.replace('?', '%s')
    
    returns = conn.execute(query, params).fetchall() if params else conn.execute(query).fetchall()
    
    result = []
    for ret in returns:
        ret_dict = dict(ret) if hasattr(ret, 'keys') else ret
        
        # Get return items with product details
        items = conn.execute('''
            SELECT ri.*, p.name, p.sku, p.price_single
            FROM return_items ri
            JOIN products p ON ri.product_id = p.id
            WHERE ri.return_id = ?
        '''.replace('?', '%s') if is_postgres() else '''
            SELECT ri.*, p.name, p.sku, p.price_single
            FROM return_items ri
            JOIN products p ON ri.product_id = p.id
            WHERE ri.return_id = ?
        ''', (ret_dict['id'],)).fetchall()
        
        ret_dict['items'] = [dict(i) if hasattr(i, 'keys') else i for i in items]
        
        # Calculate suggested credit amount
        suggested_amount = 0
        for i in items:
            if hasattr(i, 'keys'):
                suggested_amount += i['quantity'] * (i['price_single'] or 0)
            else:
                suggested_amount += i[4] * (i[-1] or 0)
        ret_dict['suggested_amount'] = round(suggested_amount, 2)
        
        result.append(ret_dict)
    
    conn.close()
    return jsonify(result)


@app.route('/api/admin/returns/<int:return_id>', methods=['GET'])
@admin_required
def admin_get_return_detail(return_id):
    """Get detailed info for a single return"""
    conn = get_db()
    
    ret = conn.execute('''
        SELECT r.*, o.order_number, o.total as order_total, o.subtotal,
               o.discount_amount, o.credit_applied, o.shipping_cost,
               u.full_name, u.email, u.phone, u.referral_credit
        FROM returns r
        JOIN orders o ON r.order_id = o.id
        JOIN users u ON r.user_id = u.id
        WHERE r.id = ?
    '''.replace('?', '%s') if is_postgres() else '''
        SELECT r.*, o.order_number, o.total as order_total, o.subtotal,
               o.discount_amount, o.credit_applied, o.shipping_cost,
               u.full_name, u.email, u.phone, u.referral_credit
        FROM returns r
        JOIN orders o ON r.order_id = o.id
        JOIN users u ON r.user_id = u.id
        WHERE r.id = ?
    ''', (return_id,)).fetchone()
    
    if not ret:
        conn.close()
        return jsonify({'error': 'Return not found'}), 404
    
    ret_dict = dict(ret) if hasattr(ret, 'keys') else ret
    
    # Get return items
    items = conn.execute('''
        SELECT ri.*, p.name, p.sku, p.price_single, oi.unit_price as paid_price
        FROM return_items ri
        JOIN products p ON ri.product_id = p.id
        JOIN order_items oi ON ri.order_item_id = oi.id
        WHERE ri.return_id = ?
    '''.replace('?', '%s') if is_postgres() else '''
        SELECT ri.*, p.name, p.sku, p.price_single, oi.unit_price as paid_price
        FROM return_items ri
        JOIN products p ON ri.product_id = p.id
        JOIN order_items oi ON ri.order_item_id = oi.id
        WHERE ri.return_id = ?
    ''', (return_id,)).fetchall()
    
    ret_dict['items'] = [dict(i) if hasattr(i, 'keys') else i for i in items]
    
    # Get all items from original order for context
    order_items = conn.execute('''
        SELECT oi.*, p.name, p.sku
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
    '''.replace('?', '%s') if is_postgres() else '''
        SELECT oi.*, p.name, p.sku
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
    ''', (ret_dict['order_id'],)).fetchall()
    
    ret_dict['original_order_items'] = [dict(i) if hasattr(i, 'keys') else i for i in order_items]
    
    conn.close()
    return jsonify(ret_dict)


@app.route('/api/admin/returns/<int:return_id>/process', methods=['POST'])
@admin_required
def admin_process_return(return_id):
    """Process a return request - issue credit, refund, replacement, or deny"""
    data = request.json
    resolution_type = data.get('resolution_type')
    resolution_amount = float(data.get('resolution_amount', 0))
    admin_notes = data.get('admin_notes', '')
    
    if not resolution_type:
        return jsonify({'error': 'Resolution type is required'}), 400
    
    if resolution_type in ['store_credit', 'partial_credit'] and resolution_amount <= 0:
        return jsonify({'error': 'Credit amount must be greater than 0'}), 400
    
    conn = get_db()
    
    # Get return request
    ret = conn.execute('SELECT * FROM returns WHERE id = ?'.replace('?', '%s') if is_postgres() else 'SELECT * FROM returns WHERE id = ?', (return_id,)).fetchone()
    if not ret:
        conn.close()
        return jsonify({'error': 'Return not found'}), 404
    
    ret_dict = dict(ret) if hasattr(ret, 'keys') else ret
    
    if ret_dict['status'] != 'pending':
        conn.close()
        return jsonify({'error': 'Return has already been processed'}), 400
    
    user_id = ret_dict['user_id']
    order_id = ret_dict['order_id']
    
    # Get order number for transaction description
    order = conn.execute('SELECT order_number FROM orders WHERE id = ?'.replace('?', '%s') if is_postgres() else 'SELECT order_number FROM orders WHERE id = ?', (order_id,)).fetchone()
    order_number = order['order_number'] if hasattr(order, 'keys') else order[0]
    
    new_status = 'approved'
    
    if resolution_type == 'denied':
        new_status = 'denied'
    elif resolution_type in ['store_credit', 'partial_credit']:
        # Add credit to user account
        conn.execute('UPDATE users SET referral_credit = referral_credit + ? WHERE id = ?'.replace('?', '%s') if is_postgres() else 'UPDATE users SET referral_credit = referral_credit + ? WHERE id = ?', 
                  (resolution_amount, user_id))
        
        # Log the transaction
        description = f'Return credit for order {order_number}: {admin_notes}' if admin_notes else f'Return credit for order {order_number}'
        conn.execute('''
            INSERT INTO referral_transactions (user_id, order_id, type, amount, description)
            VALUES (?, ?, ?, ?, ?)
        '''.replace('?', '%s') if is_postgres() else '''
            INSERT INTO referral_transactions (user_id, order_id, type, amount, description)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, order_id, 'credit', resolution_amount, description))
        
    elif resolution_type == 'full_refund':
        new_status = 'refund_pending'
        
    elif resolution_type == 'replacement':
        new_status = 'replacement_pending'
    
    # Update return record
    conn.execute('''
        UPDATE returns 
        SET status = ?, resolution_type = ?, resolution_amount = ?, 
            admin_notes = ?, processed_by = ?, processed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    '''.replace('?', '%s') if is_postgres() else '''
        UPDATE returns 
        SET status = ?, resolution_type = ?, resolution_amount = ?, 
            admin_notes = ?, processed_by = ?, processed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (new_status, resolution_type, resolution_amount, admin_notes, session['user_id'], return_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'message': 'Return processed successfully',
        'status': new_status,
        'resolution_type': resolution_type,
        'resolution_amount': resolution_amount
    })


@app.route('/api/admin/returns/<int:return_id>/complete-refund', methods=['POST'])
@admin_required
def admin_complete_refund(return_id):
    """Mark an external refund as completed"""
    data = request.json
    
    conn = get_db()
    ret = conn.execute('SELECT * FROM returns WHERE id = ?'.replace('?', '%s') if is_postgres() else 'SELECT * FROM returns WHERE id = ?', (return_id,)).fetchone()
    
    if not ret:
        conn.close()
        return jsonify({'error': 'Return not found'}), 404
    
    ret_dict = dict(ret) if hasattr(ret, 'keys') else ret
    
    if ret_dict['status'] != 'refund_pending':
        conn.close()
        return jsonify({'error': 'Return is not pending refund'}), 400
    
    notes = data.get('notes', '')
    existing_notes = ret_dict.get('admin_notes', '') or ''
    new_notes = f"{existing_notes}\n[REFUND COMPLETED] {notes}".strip()
    
    conn.execute('''
        UPDATE returns SET status = 'refunded', admin_notes = ? WHERE id = ?
    '''.replace('?', '%s') if is_postgres() else '''
        UPDATE returns SET status = 'refunded', admin_notes = ? WHERE id = ?
    ''', (new_notes, return_id))
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Refund marked as completed'})


@app.route('/api/admin/users/<int:uid>/add-credit', methods=['POST'])
@admin_required
def admin_add_credit(uid):
    """Manually add credit to a user's account"""
    data = request.json
    amount = float(data.get('amount', 0))
    reason = data.get('reason', 'Manual adjustment')
    
    if amount == 0:
        return jsonify({'error': 'Amount cannot be zero'}), 400
    
    conn = get_db()
    
    user = conn.execute('SELECT id, full_name, referral_credit FROM users WHERE id = ?'.replace('?', '%s') if is_postgres() else 'SELECT id, full_name, referral_credit FROM users WHERE id = ?', (uid,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    # Update credit
    conn.execute('UPDATE users SET referral_credit = referral_credit + ? WHERE id = ?'.replace('?', '%s') if is_postgres() else 'UPDATE users SET referral_credit = referral_credit + ? WHERE id = ?', (amount, uid))
    
    # Log transaction
    conn.execute('''
        INSERT INTO referral_transactions (user_id, type, amount, description)
        VALUES (?, ?, ?, ?)
    '''.replace('?', '%s') if is_postgres() else '''
        INSERT INTO referral_transactions (user_id, type, amount, description)
        VALUES (?, ?, ?, ?)
    ''', (uid, 'adjustment', amount, reason))
    
    conn.commit()
    
    # Get new balance
    new_balance = conn.execute('SELECT referral_credit FROM users WHERE id = ?'.replace('?', '%s') if is_postgres() else 'SELECT referral_credit FROM users WHERE id = ?', (uid,)).fetchone()
    new_balance = new_balance['referral_credit'] if hasattr(new_balance, 'keys') else new_balance[0]
    
    conn.close()
    
    return jsonify({
        'message': f'Credit {"added" if amount > 0 else "removed"} successfully',
        'amount': amount,
        'new_balance': new_balance
    })


@app.route('/api/admin/returns/stats', methods=['GET'])
@admin_required
def admin_returns_stats():
    """Get returns statistics for dashboard"""
    conn = get_db()
    
    stats = {}
    
    # Pending returns count
    pending = conn.execute('SELECT COUNT(*) as count FROM returns WHERE status = ?'.replace('?', '%s') if is_postgres() else 'SELECT COUNT(*) as count FROM returns WHERE status = ?', ('pending',)).fetchone()
    stats['pending'] = pending['count'] if hasattr(pending, 'keys') else pending[0]
    
    # This month's returns
    if is_postgres():
        month_returns = conn.execute('''
            SELECT COUNT(*) as count, COALESCE(SUM(resolution_amount), 0) as total_credited
            FROM returns 
            WHERE created_at >= date_trunc('month', CURRENT_DATE)
              AND status NOT IN ('pending', 'denied')
        ''').fetchone()
    else:
        month_returns = conn.execute('''
            SELECT COUNT(*) as count, COALESCE(SUM(resolution_amount), 0) as total_credited
            FROM returns 
            WHERE created_at >= date('now', 'start of month')
              AND status NOT IN ('pending', 'denied')
        ''').fetchone()
    
    stats['month_count'] = month_returns['count'] if hasattr(month_returns, 'keys') else month_returns[0]
    stats['month_credited'] = month_returns['total_credited'] if hasattr(month_returns, 'keys') else month_returns[1]
    
    # By reason
    by_reason = conn.execute('''
        SELECT reason, COUNT(*) as count 
        FROM returns 
        GROUP BY reason
    ''').fetchall()
    stats['by_reason'] = [dict(r) if hasattr(r, 'keys') else {'reason': r[0], 'count': r[1]} for r in by_reason]
    
    conn.close()
    return jsonify(stats)


@app.route('/api/admin/users/<int:uid>/reset-password', methods=['POST'])
@admin_required
def admin_reset_user_password(uid):
    """Admin can send password reset email to user or set temporary password"""
    data = request.json
    action = data.get('action', 'send_email')  # send_email or set_temp
    
    conn = get_db()
    user = conn.execute('SELECT id, email, full_name FROM users WHERE id = ?'.replace('?', '%s') if is_postgres() else 'SELECT id, email, full_name FROM users WHERE id = ?', (uid,)).fetchone()
    
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    user_dict = dict(user) if hasattr(user, 'keys') else {'id': user[0], 'email': user[1], 'full_name': user[2]}
    
    if action == 'send_email':
        # Generate reset token and send email
        token = secrets.token_urlsafe(32)
        expires = datetime.now() + timedelta(hours=24)
        conn.execute('UPDATE users SET reset_token=?, reset_token_expires=? WHERE id=?'.replace('?', '%s') if is_postgres() else 'UPDATE users SET reset_token=?, reset_token_expires=? WHERE id=?', 
                     (token, expires, uid))
        conn.commit()
        conn.close()
        send_password_reset(user_dict['email'], token)
        return jsonify({'message': f'Password reset email sent to {user_dict["email"]}'})
    
    elif action == 'set_temp':
        # Set a temporary password
        temp_password = data.get('temp_password')
        if not temp_password or len(temp_password) < 6:
            conn.close()
            return jsonify({'error': 'Temporary password must be at least 6 characters'}), 400
        
        conn.execute('UPDATE users SET password_hash=?, reset_token=NULL, reset_token_expires=NULL WHERE id=?'.replace('?', '%s') if is_postgres() else 'UPDATE users SET password_hash=?, reset_token=NULL, reset_token_expires=NULL WHERE id=?',
                     (generate_password_hash(temp_password), uid))
        conn.commit()
        conn.close()
        return jsonify({'message': f'Temporary password set for {user_dict["full_name"]}. Please share it securely.'})
    
    conn.close()
    return jsonify({'error': 'Invalid action'}), 400

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("The Peptide Wizard - Ordering Platform")
    print("="*60)
    print(f"\n📧 Email: {'Mailgun' if CONFIG['MAILGUN_API_KEY'] else 'Mock mode'}")
    print(f"📱 SMS: {'Twilio' if CONFIG['TWILIO_ACCOUNT_SID'] else 'Mock mode'}")
    
    init_db()
    if import_products():
        print("✓ Products imported (43 items)")
    
    print("\n🌐 Customer: http://localhost:5000")
    print("🔧 Admin: http://localhost:5000/admin")
    print("🔑 Login: admin@admin.com / admin123")
    print("\n" + "="*60 + "\n")
    
    app.run(debug=True, port=5000)
else:
    # Running under gunicorn - ensure tables exist
    try:
        init_db()
    except Exception as e:
        print(f"Database init error: {e}")
    
    try:
        import_products()
    except Exception as e:
        print(f"Product import error: {e}")
