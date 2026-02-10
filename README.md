# Research Materials Ordering Platform

A production-ready Flask web application for ordering research peptides and materials. Features a customer storefront with compliance gates and an admin dashboard for management.

## Features

### Security
- ✅ **Rate Limiting** - Prevents abuse on login, registration, password reset, and orders
- ✅ **CSRF Protection** - Token-based protection for all state-changing operations
- ✅ **Email Verification** - Required before placing orders
- ✅ **Password Hashing** - Secure bcrypt-based password storage
- ✅ **Session Management** - Secure session cookies with configurable settings

### Customer Features
- 🛒 **Product Catalog** - 43 research peptides with category filtering
- 🏷️ **Discount Codes** - Percentage or fixed amount discounts
- 📧 **Order Notifications** - Email and SMS confirmations
- 📄 **PDF Invoices** - Downloadable invoices for each order
- ✅ **Compliance Gates** - Research-use acknowledgments required at checkout

### Admin Features
- 📊 **Dashboard** - Order stats, revenue, and low stock alerts
- 📦 **Product Management** - CRUD operations and bulk stock updates
- 🎟️ **Discount Codes** - Create and manage promotional codes
- 📋 **Order Management** - Update status, add tracking numbers
- 👥 **User Management** - View users, toggle admin privileges
- 📬 **Notification Log** - Track all email/SMS notifications

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py

# Open in browser:
# Customer: http://localhost:5000
# Admin: http://localhost:5000/admin

# Default admin login:
# Email: admin@admin.com
# Password: admin123
```

## Configuration

Set these environment variables for production:

### Required
```bash
SECRET_KEY=your-secret-key-here          # Flask session secret
APP_URL=https://yourdomain.com           # Base URL for email links
ADMIN_EMAIL=admin@yourdomain.com         # Receives low stock alerts
```

### Email (SendGrid)
```bash
SENDGRID_API_KEY=your-api-key
SENDGRID_FROM_EMAIL=orders@yourdomain.com
```

### SMS (Twilio)
```bash
TWILIO_ACCOUNT_SID=your-account-sid
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+1234567890
```

### Database (PostgreSQL - recommended for production)
```bash
DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

### Other Settings
```bash
LOW_STOCK_THRESHOLD=10                   # Alert when stock falls below
COMPANY_NAME=Your Company Name           # For PDF invoices
COMPANY_ADDRESS=Your Address             # For PDF invoices
PRODUCTION=true                          # Enable secure cookies
```

## Product Catalog

43 peptides included across categories:
- **Peptides** - BPC-157, TB500, GHK-Cu, KPV, and more
- **Growth Hormone** - CJC-1295, Ipamorelin, Tesamorelin
- **Weight Management** - Semaglutide, Tirzepatide, Retatrutide
- **Nootropics** - Cerebrolysin, Selank, Semax, Pinealon
- **Longevity** - NAD+, Epithalon, FOXO4
- **Blends** - GLOW, KLOW

## API Endpoints

### Public
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/csrf-token` | Get CSRF token |
| POST | `/api/register` | User registration |
| POST | `/api/verify-email/<token>` | Verify email |
| POST | `/api/login` | User login |
| POST | `/api/forgot-password` | Request password reset |
| POST | `/api/reset-password` | Reset password |

### Authenticated
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/me` | Current user info |
| GET | `/api/products` | List products |
| GET | `/api/categories` | List categories |
| POST | `/api/validate-discount` | Validate discount code |
| POST | `/api/orders` | Create order |
| GET | `/api/orders` | List user's orders |
| GET | `/api/orders/<id>/invoice` | Download PDF invoice |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/stats` | Dashboard statistics |
| GET/POST | `/api/admin/products` | List/add products |
| PUT/DELETE | `/api/admin/products/<id>` | Update/deactivate product |
| POST | `/api/admin/products/<id>/restore` | Restore product |
| POST | `/api/admin/products/bulk-update-stock` | Bulk stock update |
| GET/POST | `/api/admin/discount-codes` | List/add codes |
| PUT/DELETE | `/api/admin/discount-codes/<id>` | Update/deactivate code |
| GET | `/api/admin/orders` | List orders |
| PUT | `/api/admin/orders/<id>/status` | Update order status |
| GET | `/api/admin/users` | List users |
| POST | `/api/admin/users/<id>/toggle-admin` | Toggle admin status |
| GET | `/api/admin/notifications` | View notification log |

## Default Discount Codes

| Code | Discount | Min Order |
|------|----------|-----------|
| RESEARCH10 | 10% | None |
| FIRST20 | 20% | None |
| BULK15 | 15% | $500 |

## Production Deployment Checklist

1. [ ] Set all required environment variables
2. [ ] Configure SendGrid for email notifications
3. [ ] Configure Twilio for SMS notifications (optional)
4. [ ] Switch to PostgreSQL database
5. [ ] Set up SSL/HTTPS
6. [ ] Use a production WSGI server (gunicorn, uWSGI)
7. [ ] Set up logging and monitoring
8. [ ] Configure database backups
9. [ ] Change default admin password!

## Adding Stripe Payments (Future)

The order flow is designed for easy Stripe integration:
1. Install `stripe` package
2. Add Stripe API keys to config
3. Add checkout session creation before order confirmation
4. Handle webhooks for payment confirmation

Estimated implementation time: 30 minutes

## File Structure

```
peptide-app/
├── app.py              # Main Flask application (1195 lines)
├── requirements.txt    # Python dependencies
├── README.md           # This file
├── research_orders.db  # SQLite database (dev)
└── templates/
    ├── index.html      # Customer frontend
    └── admin.html      # Admin dashboard
```

## Database Schema

- **users** - User accounts with email verification
- **products** - Product catalog
- **orders** - Order records
- **order_items** - Line items for each order
- **discount_codes** - Promotional codes
- **acknowledgments** - Compliance acknowledgment records
- **notification_log** - Email/SMS log
- **rate_limits** - Rate limiting tracking
- **csrf_tokens** - CSRF token storage

## License


For research use only. Not for human consumption.
