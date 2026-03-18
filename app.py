"""
3D Print Shop - Flask Backend
Supports PostgreSQL (Supabase) and SQLite
"""

import os
import random
import string
from datetime import datetime
from functools import wraps

from flask import (Flask, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "3dprint-secret-key-change-in-production")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
STL_FOLDER = os.path.join(UPLOAD_FOLDER, "stl_files")
PAYMENT_FOLDER = os.path.join(UPLOAD_FOLDER, "payment_screenshots")
PRODUCT_IMAGE_FOLDER = os.path.join(BASE_DIR, "static", "images", "products")

ALLOWED_STL = {"stl", "obj"}
ALLOWED_IMAGES = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_SCREENSHOTS = {"png", "jpg", "jpeg", "gif", "webp"}

for folder in [STL_FOLDER, PAYMENT_FOLDER, PRODUCT_IMAGE_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# ---------------------------------------------------------------------------
# DATABASE URL — Add your Supabase URL here OR set as environment variable
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres.bpklpcrbzbmiopfcwcfy:MySecurePass12@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres")

# Detect which database to use
USE_POSTGRES = bool(DATABASE_URL)

import sqlite3
DATABASE = os.path.join(BASE_DIR, "database.db")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    # Test connection immediately on startup — will crash with clear error if wrong
    print(f"[DB] Connecting to PostgreSQL (Supabase)...")
    try:
        _test_conn = psycopg2.connect(DATABASE_URL)
        _test_conn.close()
        print(f"[DB] PostgreSQL connection successful!")
    except Exception as e:
        print(f"[DB] PostgreSQL connection FAILED: {e}")
        print(f"[DB] Falling back to SQLite")
        USE_POSTGRES = False
else:
    print(f"[DB] No DATABASE_URL found, using SQLite")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def allowed_file(filename, allowed_set):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set


def generate_order_id():
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(random.choices(chars, k=6))
    return f"PC-{suffix}"


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        if USE_POSTGRES:
            g.db = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
            g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        if USE_POSTGRES:
            db.close()
        else:
            db.close()


def db_execute(query, params=(), fetchone=False, fetchall=False, commit=False):
    """Unified query executor for both PostgreSQL and SQLite."""
    db = get_db()

    # Convert SQLite ? placeholders to PostgreSQL %s
    if USE_POSTGRES:
        query = query.replace("?", "%s")
        # Convert AUTOINCREMENT to SERIAL for table creation (handled in init_db)

    cur = db.cursor()
    cur.execute(query, params)

    result = None
    if fetchone:
        result = cur.fetchone()
    elif fetchall:
        result = cur.fetchall()

    if commit:
        db.commit()

    return result, cur


# ---------------------------------------------------------------------------
# Initialize database
# ---------------------------------------------------------------------------
def init_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                category TEXT,
                image TEXT,
                stock INTEGER DEFAULT 10,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                order_code TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                address TEXT NOT NULL,
                delivery_method TEXT DEFAULT 'Standard Delivery',
                delivery_charge REAL DEFAULT 0,
                notes TEXT,
                total_price REAL NOT NULL,
                payment_screenshot TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS custom_print_requests (
                id SERIAL PRIMARY KEY,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                description TEXT NOT NULL,
                size TEXT,
                quantity INTEGER DEFAULT 1,
                stl_file TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed admin
        cur.execute("SELECT COUNT(*) FROM admin")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO admin (username, password) VALUES (%s, %s)",
                ("admin", generate_password_hash("admin123")),
            )

        # Seed products
        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0:
            sample_products = [
                ("Custom Name Sign", "Beautiful personalized name signs perfect for home decor, nurseries, or gifts.", 15.99, "Name Signs", "name_sign.png", 20),
                ("Dragon Keychain", "Detailed 3D printed dragon keychain. Lightweight and durable PLA filament.", 4.99, "Keychains", "dragon_keychain.png", 50),
                ("Mini Eiffel Tower", "Iconic Eiffel Tower decorative model. Perfect desk ornament or gift.", 12.50, "Decorative Models", "eiffel_tower.png", 15),
                ("Phone Stand", "Adjustable phone stand compatible with all smartphone sizes.", 8.99, "Functional Products", "phone_stand.png", 30),
                ("Flower Pot", "Geometric hexagon flower pot. Modern design for succulents and small plants.", 11.00, "Decorative Models", "flower_pot.png", 25),
                ("Initial Keychain", "Personalized initial letter keychain. Choose your letter!", 3.99, "Keychains", "initial_keychain.png", 100),
                ("Cable Organizer", "Keep your desk tidy with this sleek cable management clip.", 5.50, "Functional Products", "cable_organizer.png", 40),
                ("Family Name Plaque", "Customized family name wall plaque. Makes a wonderful housewarming gift.", 22.00, "Name Signs", "family_plaque.png", 10),
            ]
            cur.executemany(
                "INSERT INTO products (name, description, price, category, image, stock) VALUES (%s,%s,%s,%s,%s,%s)",
                sample_products,
            )

        conn.commit()
        conn.close()

    else:
        # SQLite
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                category TEXT,
                image TEXT,
                stock INTEGER DEFAULT 10,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                address TEXT NOT NULL,
                delivery_method TEXT DEFAULT 'Standard Delivery',
                delivery_charge REAL DEFAULT 0,
                notes TEXT,
                total_price REAL NOT NULL,
                payment_screenshot TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_print_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                description TEXT NOT NULL,
                size TEXT,
                quantity INTEGER DEFAULT 1,
                stl_file TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("SELECT COUNT(*) FROM admin")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO admin (username, password) VALUES (?, ?)",
                ("admin", generate_password_hash("admin123")),
            )

        cursor.execute("SELECT COUNT(*) FROM products")
        if cursor.fetchone()[0] == 0:
            sample_products = [
                ("Custom Name Sign", "Beautiful personalized name signs perfect for home decor, nurseries, or gifts.", 15.99, "Name Signs", "name_sign.png", 20),
                ("Dragon Keychain", "Detailed 3D printed dragon keychain. Lightweight and durable PLA filament.", 4.99, "Keychains", "dragon_keychain.png", 50),
                ("Mini Eiffel Tower", "Iconic Eiffel Tower decorative model. Perfect desk ornament or gift.", 12.50, "Decorative Models", "eiffel_tower.png", 15),
                ("Phone Stand", "Adjustable phone stand compatible with all smartphone sizes.", 8.99, "Functional Products", "phone_stand.png", 30),
                ("Flower Pot", "Geometric hexagon flower pot. Modern design for succulents and small plants.", 11.00, "Decorative Models", "flower_pot.png", 25),
                ("Initial Keychain", "Personalized initial letter keychain. Choose your letter!", 3.99, "Keychains", "initial_keychain.png", 100),
                ("Cable Organizer", "Keep your desk tidy with this sleek cable management clip.", 5.50, "Functional Products", "cable_organizer.png", 40),
                ("Family Name Plaque", "Customized family name wall plaque. Makes a wonderful housewarming gift.", 22.00, "Name Signs", "family_plaque.png", 10),
            ]
            cursor.executemany(
                "INSERT INTO products (name, description, price, category, image, stock) VALUES (?,?,?,?,?,?)",
                sample_products,
            )

        db.commit()
        db.close()


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please log in to access the admin panel.", "error")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# Delivery options
DELIVERY_OPTIONS = [
    ("Pickup (Free)", 0),
    ("Inside Valley (Rs. 100)", 100),
    ("Outside Valley (Rs. 200)", 200),
    ("Same Day – KTM (Rs. 250)", 250),
    ("Express Courier (Rs. 350)", 350),
]


# ---------------------------------------------------------------------------
# Cart helpers
# ---------------------------------------------------------------------------
def get_cart():
    return session.get("cart", {})


def save_cart(cart):
    session["cart"] = cart
    session.modified = True


def cart_total(cart):
    db = get_db()
    total = 0.0
    if USE_POSTGRES:
        for product_id, qty in cart.items():
            cur = db.cursor()
            cur.execute("SELECT price FROM products WHERE id = %s", (product_id,))
            row = cur.fetchone()
            if row:
                total += row["price"] * qty
    else:
        for product_id, qty in cart.items():
            row = db.execute("SELECT price FROM products WHERE id = ?", (product_id,)).fetchone()
            if row:
                total += row["price"] * qty
    return round(total, 2)


def cart_items_detail(cart):
    db = get_db()
    items = []
    for product_id, qty in cart.items():
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            row = cur.fetchone()
        else:
            row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row:
            items.append({
                "id": row["id"],
                "name": row["name"],
                "price": row["price"],
                "image": row["image"],
                "quantity": qty,
                "subtotal": round(row["price"] * qty, 2),
            })
    return items


@app.context_processor
def inject_cart_count():
    cart = get_cart()
    return {"cart_count": sum(cart.values())}


# ===========================================================================
# PUBLIC ROUTES
# ===========================================================================

@app.route("/")
def index():
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM products ORDER BY RANDOM() LIMIT 4")
        featured = cur.fetchall()
    else:
        featured = db.execute("SELECT * FROM products ORDER BY RANDOM() LIMIT 4").fetchall()
    categories = ["Name Signs", "Keychains", "Decorative Models", "Functional Products"]
    return render_template("index.html", featured=featured, categories=categories)


@app.route("/products")
def products():
    db = get_db()
    category = request.args.get("category", "")
    search = request.args.get("search", "")

    if USE_POSTGRES:
        query = "SELECT * FROM products WHERE 1=1"
        params = []
        if category:
            query += " AND category = %s"
            params.append(category)
        if search:
            query += " AND (name ILIKE %s OR description ILIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY created_at DESC"
        cur = db.cursor()
        cur.execute(query, params)
        all_products = cur.fetchall()
    else:
        query = "SELECT * FROM products WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if search:
            query += " AND (name LIKE ? OR description LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY created_at DESC"
        all_products = db.execute(query, params).fetchall()

    categories = ["Name Signs", "Keychains", "Decorative Models", "Functional Products"]
    return render_template("products.html", products=all_products, categories=categories,
                           selected_category=category, search=search)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("products"))
        cur.execute("SELECT * FROM products WHERE category = %s AND id != %s ORDER BY RANDOM() LIMIT 4",
                    (product["category"], product_id))
        related = cur.fetchall()
    else:
        product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("products"))
        related = db.execute(
            "SELECT * FROM products WHERE category = ? AND id != ? ORDER BY RANDOM() LIMIT 4",
            (product["category"], product_id)
        ).fetchall()
    return render_template("product_detail.html", product=product, related=related)


# ---------------------------------------------------------------------------
# Cart routes
# ---------------------------------------------------------------------------
@app.route("/cart")
def cart():
    cart_data = get_cart()
    items = cart_items_detail(cart_data)
    total = cart_total(cart_data)
    return render_template("cart.html", items=items, total=total)


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    qty = int(request.form.get("quantity", 1))
    cart = get_cart()
    key = str(product_id)
    cart[key] = cart.get(key, 0) + qty
    save_cart(cart)
    flash("Item added to cart!", "success")
    return redirect(request.referrer or url_for("products"))


@app.route("/cart/update/<int:product_id>", methods=["POST"])
def update_cart(product_id):
    qty = int(request.form.get("quantity", 1))
    cart = get_cart()
    key = str(product_id)
    if qty <= 0:
        cart.pop(key, None)
    else:
        cart[key] = qty
    save_cart(cart)
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:product_id>")
def remove_from_cart(product_id):
    cart = get_cart()
    cart.pop(str(product_id), None)
    save_cart(cart)
    flash("Item removed from cart.", "info")
    return redirect(url_for("cart"))


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart_data = get_cart()
    if not cart_data:
        flash("Your cart is empty.", "info")
        return redirect(url_for("products"))

    items = cart_items_detail(cart_data)
    subtotal = cart_total(cart_data)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        notes = request.form.get("notes", "").strip()
        delivery_method = request.form.get("delivery_method", "Pickup (Free)")

        delivery_charge = 0
        for label, charge in DELIVERY_OPTIONS:
            if label == delivery_method:
                delivery_charge = charge
                break

        total = round(subtotal + delivery_charge, 2)

        if not all([name, phone, address]):
            flash("Please fill in all required fields.", "error")
            return render_template("checkout.html", items=items, subtotal=subtotal,
                                   delivery_options=DELIVERY_OPTIONS)

        screenshot_filename = None
        if "payment_screenshot" in request.files:
            file = request.files["payment_screenshot"]
            if file and file.filename and allowed_file(file.filename, ALLOWED_SCREENSHOTS):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                file.save(os.path.join(PAYMENT_FOLDER, filename))
                screenshot_filename = filename

        db = get_db()

        # Generate unique order code
        for _ in range(10):
            order_code = generate_order_id()
            if USE_POSTGRES:
                cur = db.cursor()
                cur.execute("SELECT id FROM orders WHERE order_code=%s", (order_code,))
                existing = cur.fetchone()
            else:
                existing = db.execute("SELECT id FROM orders WHERE order_code=?", (order_code,)).fetchone()
            if not existing:
                break

        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("""
                INSERT INTO orders (order_code, customer_name, phone, email, address,
                delivery_method, delivery_charge, notes, total_price, payment_screenshot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (order_code, name, phone, email, address,
                  delivery_method, delivery_charge, notes, total, screenshot_filename))
            order_id = cur.fetchone()["id"]
            for item in items:
                cur.execute("""
                    INSERT INTO order_items (order_id, product_id, product_name, quantity, price)
                    VALUES (%s,%s,%s,%s,%s)
                """, (order_id, item["id"], item["name"], item["quantity"], item["price"]))
            db.commit()
        else:
            cursor = db.execute("""
                INSERT INTO orders (order_code, customer_name, phone, email, address,
                delivery_method, delivery_charge, notes, total_price, payment_screenshot)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (order_code, name, phone, email, address,
                  delivery_method, delivery_charge, notes, total, screenshot_filename))
            order_id = cursor.lastrowid
            for item in items:
                db.execute("""
                    INSERT INTO order_items (order_id, product_id, product_name, quantity, price)
                    VALUES (?,?,?,?,?)
                """, (order_id, item["id"], item["name"], item["quantity"], item["price"]))
            db.commit()

        session.pop("cart", None)
        flash(f"Order {order_code} placed successfully! We'll contact you soon.", "success")
        return redirect(url_for("order_success", order_id=order_id))

    return render_template("checkout.html", items=items, subtotal=subtotal,
                           delivery_options=DELIVERY_OPTIONS)


@app.route("/order-success/<int:order_id>")
def order_success(order_id):
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
    else:
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return render_template("order_success.html", order=order)


# ---------------------------------------------------------------------------
# Custom print
# ---------------------------------------------------------------------------
@app.route("/custom-print", methods=["GET", "POST"])
def custom_print():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        description = request.form.get("description", "").strip()
        size = request.form.get("size", "")
        quantity = int(request.form.get("quantity", 1))

        if not all([name, email, description]):
            flash("Please fill in all required fields.", "error")
            return render_template("custom_print.html")

        stl_filename = None
        if "stl_file" in request.files:
            file = request.files["stl_file"]
            if file and file.filename and allowed_file(file.filename, ALLOWED_STL):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                file.save(os.path.join(STL_FOLDER, filename))
                stl_filename = filename

        db = get_db()
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("""
                INSERT INTO custom_print_requests
                (customer_name, email, phone, description, size, quantity, stl_file)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (name, email, phone, description, size, quantity, stl_filename))
            db.commit()
        else:
            db.execute("""
                INSERT INTO custom_print_requests
                (customer_name, email, phone, description, size, quantity, stl_file)
                VALUES (?,?,?,?,?,?,?)
            """, (name, email, phone, description, size, quantity, stl_filename))
            db.commit()

        flash("Your custom print request has been submitted! We'll get back to you shortly.", "success")
        return redirect(url_for("custom_print"))

    return render_template("custom_print.html")


# ===========================================================================
# ADMIN ROUTES
# ===========================================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        db = get_db()
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("SELECT * FROM admin WHERE username = %s", (username,))
            admin = cur.fetchone()
        else:
            admin = db.execute("SELECT * FROM admin WHERE username = ?", (username,)).fetchone()

        if admin and check_password_hash(admin["password"], password):
            session["admin_logged_in"] = True
            session["admin_username"] = username
            flash("Welcome back!", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.", "error")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) as c FROM orders"); total_orders = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM orders WHERE status='Pending'"); pending_orders = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM products"); total_products = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM custom_print_requests WHERE status='Pending'"); custom_requests = cur.fetchone()["c"]
        cur.execute("SELECT SUM(total_price) as s FROM orders WHERE status='Completed'"); revenue = cur.fetchone()["s"] or 0
        cur.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 5"); recent_orders = cur.fetchall()
    else:
        total_orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        pending_orders = db.execute("SELECT COUNT(*) FROM orders WHERE status='Pending'").fetchone()[0]
        total_products = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        custom_requests = db.execute("SELECT COUNT(*) FROM custom_print_requests WHERE status='Pending'").fetchone()[0]
        revenue = db.execute("SELECT SUM(total_price) FROM orders WHERE status='Completed'").fetchone()[0] or 0
        recent_orders = db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 5").fetchall()

    return render_template("admin_dashboard.html",
                           total_orders=total_orders,
                           pending_orders=pending_orders,
                           total_products=total_products,
                           custom_requests=custom_requests,
                           revenue=round(revenue, 2),
                           recent_orders=recent_orders)


@app.route("/admin/products")
@admin_required
def admin_products():
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM products ORDER BY created_at DESC")
        all_products = cur.fetchall()
    else:
        all_products = db.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
    return render_template("admin_products.html", products=all_products)


@app.route("/admin/products/add", methods=["GET", "POST"])
@admin_required
def admin_add_product():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = float(request.form.get("price", 0))
        category = request.form.get("category", "")
        stock = int(request.form.get("stock", 0))

        image_filename = "default.png"
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename, ALLOWED_IMAGES):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                file.save(os.path.join(PRODUCT_IMAGE_FOLDER, filename))
                image_filename = filename

        db = get_db()
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute(
                "INSERT INTO products (name, description, price, category, image, stock) VALUES (%s,%s,%s,%s,%s,%s)",
                (name, description, price, category, image_filename, stock))
            db.commit()
        else:
            db.execute(
                "INSERT INTO products (name, description, price, category, image, stock) VALUES (?,?,?,?,?,?)",
                (name, description, price, category, image_filename, stock))
            db.commit()

        flash("Product added successfully!", "success")
        return redirect(url_for("admin_products"))

    categories = ["Name Signs", "Keychains", "Decorative Models", "Functional Products"]
    return render_template("admin_add_product.html", categories=categories)


@app.route("/admin/products/edit/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id):
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
    else:
        product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()

    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("admin_products"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = float(request.form.get("price", 0))
        category = request.form.get("category", "")
        stock = int(request.form.get("stock", 0))

        image_filename = product["image"]
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename, ALLOWED_IMAGES):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                file.save(os.path.join(PRODUCT_IMAGE_FOLDER, filename))
                image_filename = filename

        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute(
                "UPDATE products SET name=%s, description=%s, price=%s, category=%s, image=%s, stock=%s WHERE id=%s",
                (name, description, price, category, image_filename, stock, product_id))
            db.commit()
        else:
            db.execute(
                "UPDATE products SET name=?, description=?, price=?, category=?, image=?, stock=? WHERE id=?",
                (name, description, price, category, image_filename, stock, product_id))
            db.commit()

        flash("Product updated!", "success")
        return redirect(url_for("admin_products"))

    categories = ["Name Signs", "Keychains", "Decorative Models", "Functional Products"]
    return render_template("admin_edit_product.html", product=product, categories=categories)


@app.route("/admin/products/delete/<int:product_id>", methods=["POST"])
@admin_required
def admin_delete_product(product_id):
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        db.commit()
    else:
        db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        db.commit()
    flash("Product deleted.", "info")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    db = get_db()
    status_filter = request.args.get("status", "")
    if USE_POSTGRES:
        cur = db.cursor()
        if status_filter:
            cur.execute("SELECT * FROM orders WHERE status=%s ORDER BY created_at DESC", (status_filter,))
        else:
            cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
        orders = cur.fetchall()
    else:
        if status_filter:
            orders = db.execute("SELECT * FROM orders WHERE status=? ORDER BY created_at DESC", (status_filter,)).fetchall()
        else:
            orders = db.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    return render_template("admin_orders.html", orders=orders, status_filter=status_filter)


@app.route("/admin/orders/<int:order_id>")
@admin_required
def admin_order_detail(order_id):
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        cur.execute("SELECT * FROM order_items WHERE order_id = %s", (order_id,))
        items = cur.fetchall()
    else:
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        items = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    return render_template("admin_order_detail.html", order=order, items=items)


@app.route("/admin/orders/<int:order_id>/print")
@admin_required
def admin_print_receipt(order_id):
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        cur.execute("SELECT * FROM order_items WHERE order_id = %s", (order_id,))
        items = cur.fetchall()
    else:
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        items = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    return render_template("receipt_print.html", order=order, items=items)


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def admin_update_order_status(order_id):
    status = request.form.get("status")
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
        db.commit()
    else:
        db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        db.commit()
    flash(f"Order status updated to {status}.", "success")
    return redirect(url_for("admin_order_detail", order_id=order_id))


@app.route("/admin/custom-requests")
@admin_required
def admin_custom_requests():
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM custom_print_requests ORDER BY created_at DESC")
        requests_list = cur.fetchall()
    else:
        requests_list = db.execute("SELECT * FROM custom_print_requests ORDER BY created_at DESC").fetchall()
    return render_template("admin_custom_requests.html", requests=requests_list)


@app.route("/admin/custom-requests/<int:req_id>/status", methods=["POST"])
@admin_required
def admin_update_request_status(req_id):
    status = request.form.get("status")
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("UPDATE custom_print_requests SET status = %s WHERE id = %s", (status, req_id))
        db.commit()
    else:
        db.execute("UPDATE custom_print_requests SET status = ? WHERE id = ?", (status, req_id))
        db.commit()
    flash("Status updated.", "success")
    return redirect(url_for("admin_custom_requests"))


@app.route("/uploads/payment/<filename>")
@admin_required
def uploaded_payment(filename):
    from flask import send_from_directory
    return send_from_directory(PAYMENT_FOLDER, filename)


@app.route("/uploads/stl/<filename>")
@admin_required
def uploaded_stl(filename):
    from flask import send_from_directory
    return send_from_directory(STL_FOLDER, filename)


# ---------------------------------------------------------------------------
# Initialize DB on startup
# ---------------------------------------------------------------------------
init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
