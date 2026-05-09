# 🖨️ Torque and Tech — Full-Stack E-Commerce for 3D Printing

A complete Flask + SQLite e-commerce website for a 3D printing business.

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app (auto-initializes DB with sample data)
python app.py

# 3. Open in browser
# Store:  http://localhost:5000
# Admin:  http://localhost:5000/admin/login
```

## 🔐 Admin Login
- **Username:** admin
- **Password:** admin123

## 📁 Project Structure
```
project/
├── app.py                    # Flask application & routes
├── database.db               # SQLite database (auto-created)
├── requirements.txt
├── templates/
│   ├── base.html             # Public layout (navbar + footer)
│   ├── admin_base.html       # Admin layout (sidebar)
│   ├── index.html            # Home page
│   ├── products.html         # Product listing
│   ├── product_detail.html   # Product detail
│   ├── cart.html             # Shopping cart
│   ├── checkout.html         # Checkout + QR payment
│   ├── order_success.html    # Order confirmation
│   ├── custom_print.html     # Custom 3D print request
│   ├── admin_login.html      # Admin login
│   ├── admin_dashboard.html  # Admin dashboard
│   ├── admin_products.html   # Manage products
│   ├── admin_add_product.html
│   ├── admin_edit_product.html
│   ├── admin_orders.html     # View orders
│   ├── admin_order_detail.html
│   ├── admin_custom_requests.html
│   └── partials/
│       └── product_card.html
├── static/
│   ├── css/style.css
│   ├── js/script.js
│   └── images/products/      # Upload product images here
└── uploads/
    ├── stl_files/            # Customer-uploaded STL/OBJ files
    └── payment_screenshots/  # Customer payment proofs
```

## ✨ Features
- **Home** — Hero, categories, featured products, stats
- **Products** — Grid layout, search, category filter
- **Product Detail** — Image, qty selector, related items
- **Cart** — Session-based, update/remove items
- **Checkout** — Customer info, QR code payment, screenshot upload
- **Custom Print** — STL/OBJ upload, description, size, qty
- **Admin Panel** — Login-protected dashboard with full CRUD
