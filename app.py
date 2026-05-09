"""
3D Print Shop - Flask Backend
Supports PostgreSQL (Supabase) + Supabase Storage for files
"""

import os
import random
import string
import hmac
import hashlib
import base64
import json
import uuid
import requests as http_requests
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
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY environment variable is not set. Add it to your .env or hosting config.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ALLOWED_STL = {"stl", "obj"}
ALLOWED_IMAGES = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_SCREENSHOTS = {"png", "jpg", "jpeg", "gif", "webp"}

# ---------------------------------------------------------------------------
# eSewa ePay configuration (UAT / Testing)
# ---------------------------------------------------------------------------
ESEWA_PRODUCT_CODE = os.environ.get("ESEWA_PRODUCT_CODE", "EPAYTEST")
ESEWA_SECRET_KEY   = os.environ.get("ESEWA_SECRET_KEY",   "8gBm/:&EnhH.1/q")
ESEWA_PAYMENT_URL  = os.environ.get("ESEWA_PAYMENT_URL",  "https://rc-epay.esewa.com.np/api/epay/main/v2/form")
ESEWA_STATUS_URL   = os.environ.get("ESEWA_STATUS_URL",   "https://rc.esewa.com.np/api/epay/transaction/status/")

# Keep local folders as fallback
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
STL_FOLDER = os.path.join(UPLOAD_FOLDER, "stl_files")
PAYMENT_FOLDER = os.path.join(UPLOAD_FOLDER, "payment_screenshots")
PRODUCT_IMAGE_FOLDER = os.path.join(BASE_DIR, "static", "images", "products")
for folder in [STL_FOLDER, PAYMENT_FOLDER, PRODUCT_IMAGE_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# ---------------------------------------------------------------------------
# Supabase config
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
import sqlite3
DATABASE = os.path.join(BASE_DIR, "database.db")

USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    print("[DB] Connecting to PostgreSQL (Supabase)...")
    try:
        _test_conn = psycopg2.connect(DATABASE_URL)
        _test_conn.close()
        print("[DB] PostgreSQL connection successful!")
    except Exception as e:
        print(f"[DB] PostgreSQL connection FAILED: {e}")
        print("[DB] Falling back to SQLite")
        USE_POSTGRES = False
else:
    print("[DB] No DATABASE_URL found, using SQLite")

# ---------------------------------------------------------------------------
# Supabase Storage setup
# ---------------------------------------------------------------------------
USE_SUPABASE_STORAGE = False
supabase_client = None

try:
    from supabase import create_client
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    USE_SUPABASE_STORAGE = True
    print("[STORAGE] Supabase Storage connected!")
except Exception as e:
    print(f"[STORAGE] Supabase Storage not available: {e}")
    print("[STORAGE] Using local file storage")


# ---------------------------------------------------------------------------
# File upload helper
# ---------------------------------------------------------------------------
def upload_file(file, bucket, filename):
    """Upload file to Supabase Storage or local folder. Returns URL or filename."""
    if USE_SUPABASE_STORAGE and supabase_client:
        try:
            file_bytes = file.read()
            path = f"{filename}"
            supabase_client.storage.from_(bucket).upload(
                path, file_bytes,
                file_options={"content-type": file.content_type or "application/octet-stream",
                              "upsert": "true"}
            )
            # Return public URL for products bucket, just filename for private buckets
            if bucket == "products":
                url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"
                return url
            else:
                return filename
        except Exception as e:
            print(f"[STORAGE] Upload failed: {e}, falling back to local")
            file.seek(0)

    # Local fallback
    if bucket == "products":
        save_path = os.path.join(PRODUCT_IMAGE_FOLDER, filename)
    elif bucket == "payments":
        save_path = os.path.join(PAYMENT_FOLDER, filename)
    else:
        save_path = os.path.join(STL_FOLDER, filename)
    file.save(save_path)
    return filename


def get_product_image_url(image_value):
    """Return full URL for product image."""
    if not image_value:
        return None
    if image_value.startswith("http"):
        return image_value
    return url_for('static', filename=f'images/products/{image_value}')


def get_payment_url(filename):
    """Return URL for payment screenshot."""
    if not filename:
        return None
    if filename.startswith("http"):
        return filename
    if USE_SUPABASE_STORAGE and supabase_client:
        try:
            result = supabase_client.storage.from_("payments").create_signed_url(filename, 3600)
            return result.get("signedURL") or result.get("signed_url")
        except:
            pass
    return url_for('uploaded_payment', filename=filename)


def get_stl_url(filename):
    """Return URL for STL file download."""
    if not filename:
        return None
    if filename.startswith("http"):
        return filename
    if USE_SUPABASE_STORAGE and supabase_client:
        try:
            result = supabase_client.storage.from_("stl-files").create_signed_url(filename, 3600)
            return result.get("signedURL") or result.get("signed_url")
        except:
            pass
    return url_for('uploaded_stl', filename=filename)


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
        db.close()


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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                extra_images TEXT DEFAULT '',
                is_lamp BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS extra_images TEXT DEFAULT ''")
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_lamp BOOLEAN DEFAULT FALSE")
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

        cur.execute("SELECT COUNT(*) FROM admin")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO admin (username, password) VALUES (%s, %s)",
                ("admin", generate_password_hash("admin123")))

        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0:
            sample_products = [
                ("Custom Name Sign", "Beautiful personalized name signs perfect for home decor.", 15.99, "Name Signs", "name_sign.png", 20),
                ("Dragon Keychain", "Detailed 3D printed dragon keychain. Lightweight and durable.", 4.99, "Keychains", "dragon_keychain.png", 50),
                ("Mini Eiffel Tower", "Iconic Eiffel Tower decorative model. Perfect desk ornament.", 12.50, "Decorative Models", "eiffel_tower.png", 15),
                ("Phone Stand", "Adjustable phone stand compatible with all smartphone sizes.", 8.99, "Functional Products", "phone_stand.png", 30),
                ("Flower Pot", "Geometric hexagon flower pot. Modern design for succulents.", 11.00, "Decorative Models", "flower_pot.png", 25),
                ("Initial Keychain", "Personalized initial letter keychain. Choose your letter!", 3.99, "Keychains", "initial_keychain.png", 100),
                ("Cable Organizer", "Keep your desk tidy with this sleek cable management clip.", 5.50, "Functional Products", "cable_organizer.png", 40),
                ("Family Name Plaque", "Customized family name wall plaque. Wonderful housewarming gift.", 22.00, "Name Signs", "family_plaque.png", 10),
            ]
            cur.executemany(
                "INSERT INTO products (name, description, price, category, image, stock) VALUES (%s,%s,%s,%s,%s,%s)",
                sample_products)

        conn.commit()
        conn.close()

    else:
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT,
            price REAL NOT NULL, category TEXT, image TEXT, stock INTEGER DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            extra_images TEXT DEFAULT '', is_lamp INTEGER DEFAULT 0)""")
        # Upgrade existing DB silently
        try: cursor.execute("ALTER TABLE products ADD COLUMN extra_images TEXT DEFAULT ''")
        except: pass
        try: cursor.execute("ALTER TABLE products ADD COLUMN is_lamp INTEGER DEFAULT 0")
        except: pass
        cursor.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_code TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT, address TEXT NOT NULL,
            delivery_method TEXT DEFAULT 'Standard Delivery', delivery_charge REAL DEFAULT 0,
            notes TEXT, total_price REAL NOT NULL, payment_screenshot TEXT,
            status TEXT DEFAULT 'Pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL, product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL, price REAL NOT NULL)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS custom_print_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL,
            email TEXT NOT NULL, phone TEXT, description TEXT NOT NULL, size TEXT,
            quantity INTEGER DEFAULT 1, stl_file TEXT, status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cursor.execute("SELECT COUNT(*) FROM admin")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO admin (username, password) VALUES (?, ?)",
                ("admin", generate_password_hash("admin123")))
        cursor.execute("SELECT COUNT(*) FROM products")
        if cursor.fetchone()[0] == 0:
            sample_products = [
                ("Custom Name Sign", "Beautiful personalized name signs.", 15.99, "Name Signs", "name_sign.png", 20),
                ("Dragon Keychain", "Detailed 3D printed dragon keychain.", 4.99, "Keychains", "dragon_keychain.png", 50),
                ("Mini Eiffel Tower", "Iconic Eiffel Tower decorative model.", 12.50, "Decorative Models", "eiffel_tower.png", 15),
                ("Phone Stand", "Adjustable phone stand.", 8.99, "Functional Products", "phone_stand.png", 30),
                ("Flower Pot", "Geometric hexagon flower pot.", 11.00, "Decorative Models", "flower_pot.png", 25),
                ("Initial Keychain", "Personalized initial letter keychain.", 3.99, "Keychains", "initial_keychain.png", 100),
                ("Cable Organizer", "Sleek cable management clip.", 5.50, "Functional Products", "cable_organizer.png", 40),
                ("Family Name Plaque", "Customized family name wall plaque.", 22.00, "Name Signs", "family_plaque.png", 10),
            ]
            cursor.executemany(
                "INSERT INTO products (name, description, price, category, image, stock) VALUES (?,?,?,?,?,?)",
                sample_products)
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
            query += " AND category = %s"; params.append(category)
        if search:
            query += " AND (name ILIKE %s OR description ILIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY created_at DESC"
        cur = db.cursor(); cur.execute(query, params)
        all_products = cur.fetchall()
    else:
        query = "SELECT * FROM products WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"; params.append(category)
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
            flash("Product not found.", "error"); return redirect(url_for("products"))
        cur.execute("SELECT * FROM products WHERE category = %s AND id != %s ORDER BY RANDOM() LIMIT 4",
                    (product["category"], product_id))
        related = cur.fetchall()
    else:
        product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not product:
            flash("Product not found.", "error"); return redirect(url_for("products"))
        related = db.execute(
            "SELECT * FROM products WHERE category = ? AND id != ? ORDER BY RANDOM() LIMIT 4",
            (product["category"], product_id)).fetchall()

    product = dict(product)
    # Parse extra_images into a list
    raw_extras = product.get("extra_images") or ""
    extra_images = [u.strip() for u in raw_extras.split(",") if u.strip()]
    is_lamp = bool(product.get("is_lamp"))

    return render_template("product_detail.html", product=product, related=related,
                           extra_images=extra_images, is_lamp=is_lamp)



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
        flash("Your cart is empty.", "info"); return redirect(url_for("products"))
    items = cart_items_detail(cart_data)
    subtotal = cart_total(cart_data)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        notes = request.form.get("notes", "").strip()
        delivery_method = request.form.get("delivery_method", "Pickup (Free)")
        delivery_charge = next((c for l, c in DELIVERY_OPTIONS if l == delivery_method), 0)
        total = round(subtotal + delivery_charge, 2)

        if not all([name, phone, address]):
            flash("Please fill in all required fields.", "error")
            return render_template("checkout.html", items=items, subtotal=subtotal,
                                   delivery_options=DELIVERY_OPTIONS)

        # Payment screenshot is REQUIRED
        screenshot_filename = None
        screenshot_file = request.files.get("payment_screenshot")
        if not screenshot_file or not screenshot_file.filename:
            flash("Payment screenshot is required. Please upload a screenshot of your payment.", "error")
            return render_template("checkout.html", items=items, subtotal=subtotal,
                                   delivery_options=DELIVERY_OPTIONS)
        if not allowed_file(screenshot_file.filename, ALLOWED_SCREENSHOTS):
            flash("Invalid file type for payment screenshot. Please upload a PNG, JPG, or GIF image.", "error")
            return render_template("checkout.html", items=items, subtotal=subtotal,
                                   delivery_options=DELIVERY_OPTIONS)
        filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{screenshot_file.filename}")
        screenshot_filename = upload_file(screenshot_file, "payments", filename)
        if not screenshot_filename:
            flash("Failed to upload payment screenshot. Please try again.", "error")
            return render_template("checkout.html", items=items, subtotal=subtotal,
                                   delivery_options=DELIVERY_OPTIONS)

        db = get_db()
        for _ in range(10):
            order_code = generate_order_id()
            if USE_POSTGRES:
                cur = db.cursor()
                cur.execute("SELECT id FROM orders WHERE order_code=%s", (order_code,))
                if not cur.fetchone(): break
            else:
                if not db.execute("SELECT id FROM orders WHERE order_code=?", (order_code,)).fetchone(): break

        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("""INSERT INTO orders (order_code, customer_name, phone, email, address,
                delivery_method, delivery_charge, notes, total_price, payment_screenshot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (order_code, name, phone, email, address, delivery_method, delivery_charge, notes, total, screenshot_filename))
            order_id = cur.fetchone()["id"]
            for item in items:
                cur.execute("INSERT INTO order_items (order_id, product_id, product_name, quantity, price) VALUES (%s,%s,%s,%s,%s)",
                    (order_id, item["id"], item["name"], item["quantity"], item["price"]))
            db.commit()
        else:
            cursor = db.execute("""INSERT INTO orders (order_code, customer_name, phone, email, address,
                delivery_method, delivery_charge, notes, total_price, payment_screenshot)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (order_code, name, phone, email, address, delivery_method, delivery_charge, notes, total, screenshot_filename))
            order_id = cursor.lastrowid
            for item in items:
                db.execute("INSERT INTO order_items (order_id, product_id, product_name, quantity, price) VALUES (?,?,?,?,?)",
                    (order_id, item["id"], item["name"], item["quantity"], item["price"]))
            db.commit()

        session.pop("cart", None)
        flash(f"Order {order_code} placed successfully! We'll contact you soon.", "success")
        return redirect(url_for("order_success", order_id=order_id))

    return render_template("checkout.html", items=items, subtotal=subtotal, delivery_options=DELIVERY_OPTIONS)


# ---------------------------------------------------------------------------
# eSewa ePay helpers & routes
# ---------------------------------------------------------------------------

def esewa_sign(total_amount, transaction_uuid, product_code):
    """Generate HMAC-SHA256 base64 signature for eSewa."""
    message = f"total_amount={total_amount},transaction_uuid={transaction_uuid},product_code={product_code}"
    sig = hmac.new(
        ESEWA_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(sig).decode("utf-8")


@app.route("/esewa/initiate", methods=["POST"])
def esewa_initiate():
    """Save pending order to session and redirect to eSewa."""
    cart_data = get_cart()
    if not cart_data:
        flash("Your cart is empty.", "info")
        return redirect(url_for("products"))

    items     = cart_items_detail(cart_data)
    subtotal  = cart_total(cart_data)

    name            = request.form.get("name", "").strip()
    phone           = request.form.get("phone", "").strip()
    email           = request.form.get("email", "").strip()
    address         = request.form.get("address", "").strip()
    notes           = request.form.get("notes", "").strip()
    delivery_method = request.form.get("delivery_method", "Pickup (Free)")
    delivery_charge = next((c for l, c in DELIVERY_OPTIONS if l == delivery_method), 0)
    total           = round(subtotal + delivery_charge, 2)

    if not all([name, phone, address]):
        flash("Please fill in all required fields.", "error")
        return render_template("checkout.html", items=items, subtotal=subtotal,
                               delivery_options=DELIVERY_OPTIONS)

    # Build a unique transaction ID  (date-time + short random)
    txn_uuid = datetime.now().strftime("%y%m%d-%H%M%S") + "-" + str(random.randint(100, 999))

    # Persist order info in session until eSewa confirms
    session["pending_esewa"] = {
        "name": name, "phone": phone, "email": email,
        "address": address, "notes": notes,
        "delivery_method": delivery_method,
        "delivery_charge": delivery_charge,
        "total": total, "txn_uuid": txn_uuid,
        "cart_snapshot": cart_data,
    }

    signature = esewa_sign(total, txn_uuid, ESEWA_PRODUCT_CODE)

    # Build the base_url for callbacks
    base = request.host_url.rstrip("/")

    return render_template("esewa_redirect.html",
        esewa_url        = ESEWA_PAYMENT_URL,
        amount           = total,          # no separate tax/service in this shop
        tax_amount       = 0,
        product_service_charge  = 0,
        product_delivery_charge = 0,
        total_amount     = total,
        transaction_uuid = txn_uuid,
        product_code     = ESEWA_PRODUCT_CODE,
        success_url      = base + url_for("esewa_success"),
        failure_url      = base + url_for("esewa_failure"),
        signed_field_names = "total_amount,transaction_uuid,product_code",
        signature        = signature,
    )


@app.route("/esewa/success")
def esewa_success():
    """eSewa redirects here after successful payment."""
    encoded = request.args.get("data", "")
    pending = session.get("pending_esewa")

    if not encoded or not pending:
        flash("Payment session expired. Please try again.", "error")
        return redirect(url_for("checkout"))

    try:
        decoded = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except Exception:
        flash("Invalid payment response. Please contact support.", "error")
        return redirect(url_for("checkout"))

    # Verify signature
    expected_sig = esewa_sign(
        decoded.get("total_amount", ""),
        decoded.get("transaction_uuid", ""),
        decoded.get("product_code", ""),
    )
    if decoded.get("signature") != expected_sig:
        flash("Payment signature mismatch. Contact support.", "error")
        return redirect(url_for("checkout"))

    if decoded.get("status") != "COMPLETE":
        flash("Payment not completed. Please try again.", "error")
        return redirect(url_for("checkout"))

    # --- Place the order ---
    db = get_db()
    name            = pending["name"]
    phone           = pending["phone"]
    email           = pending["email"]
    address         = pending["address"]
    notes           = pending["notes"]
    delivery_method = pending["delivery_method"]
    delivery_charge = pending["delivery_charge"]
    total           = pending["total"]
    esewa_ref       = decoded.get("transaction_code", "")
    cart_data       = pending["cart_snapshot"]
    items           = cart_items_detail(cart_data)

    for _ in range(10):
        order_code = generate_order_id()
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("SELECT id FROM orders WHERE order_code=%s", (order_code,))
            if not cur.fetchone(): break
        else:
            if not db.execute("SELECT id FROM orders WHERE order_code=?", (order_code,)).fetchone(): break

    esewa_note = f"eSewa | Ref: {esewa_ref} | TxnID: {decoded.get('transaction_uuid','')}"

    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("""INSERT INTO orders (order_code, customer_name, phone, email, address,
            delivery_method, delivery_charge, notes, total_price, payment_screenshot)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (order_code, name, phone, email, address, delivery_method, delivery_charge,
             f"{notes} [{esewa_note}]".strip(" []"), total, "esewa_paid"))
        order_id = cur.fetchone()["id"]
        for item in items:
            cur.execute("INSERT INTO order_items (order_id, product_id, product_name, quantity, price) VALUES (%s,%s,%s,%s,%s)",
                (order_id, item["id"], item["name"], item["quantity"], item["price"]))
        db.commit()
    else:
        cursor = db.execute("""INSERT INTO orders (order_code, customer_name, phone, email, address,
            delivery_method, delivery_charge, notes, total_price, payment_screenshot)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (order_code, name, phone, email, address, delivery_method, delivery_charge,
             f"{notes} [{esewa_note}]".strip(" []"), total, "esewa_paid"))
        order_id = cursor.lastrowid
        for item in items:
            db.execute("INSERT INTO order_items (order_id, product_id, product_name, quantity, price) VALUES (?,?,?,?,?)",
                (order_id, item["id"], item["name"], item["quantity"], item["price"]))
        db.commit()

    session.pop("cart", None)
    session.pop("pending_esewa", None)
    flash(f"✅ Payment confirmed via eSewa! Order {order_code} placed.", "success")
    return redirect(url_for("order_success", order_id=order_id))


@app.route("/esewa/failure")
def esewa_failure():
    session.pop("pending_esewa", None)
    flash("eSewa payment was cancelled or failed. Please try again.", "error")
    return redirect(url_for("checkout"))


@app.route("/track-order")
def track_order():
    query = request.args.get("q", "").strip()
    if not query:
        return render_template("track_order.html", query=None, orders=None, error_type=None)

    db = get_db()

    # Determine search type and fetch matching orders
    if query.upper().startswith("PC-"):
        # Search by order code
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("SELECT * FROM orders WHERE UPPER(order_code) = %s", (query.upper(),))
            orders = cur.fetchall()
        else:
            orders = db.execute("SELECT * FROM orders WHERE UPPER(order_code) = ?", (query.upper(),)).fetchall()
    elif "@" in query:
        # Search by email
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("SELECT * FROM orders WHERE LOWER(email) = %s ORDER BY created_at DESC", (query.lower(),))
            orders = cur.fetchall()
        else:
            orders = db.execute("SELECT * FROM orders WHERE LOWER(email) = ? ORDER BY created_at DESC", (query.lower(),)).fetchall()
    else:
        # Search by phone
        clean = query.replace(" ", "").replace("-", "")
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("SELECT * FROM orders WHERE REPLACE(REPLACE(phone, ' ', ''), '-', '') = %s ORDER BY created_at DESC", (clean,))
            orders = cur.fetchall()
        else:
            orders = db.execute("SELECT * FROM orders WHERE REPLACE(REPLACE(phone, ' ', ''), '-', '') = ? ORDER BY created_at DESC", (clean,)).fetchall()

    if not orders:
        return render_template("track_order.html", query=query, orders=None, error_type="not_found")

    orders = [dict(o) for o in orders]

    # Check if all orders are delivered or cancelled — show specific error
    statuses = [o["status"] for o in orders]
    if all(s == "Delivered" for s in statuses):
        return render_template("track_order.html", query=query, orders=orders, error_type="delivered")
    if all(s == "Cancelled" for s in statuses):
        return render_template("track_order.html", query=query, orders=orders, error_type="cancelled")

    # Filter out delivered/cancelled from main list, show active ones
    active = [o for o in orders if o["status"] not in ("Delivered", "Cancelled")]
    return render_template("track_order.html", query=query, orders=active or orders, error_type=None)



@app.route("/order-success/<int:order_id>")
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
                stl_filename = upload_file(file, "stl-files", filename)

        db = get_db()
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("""INSERT INTO custom_print_requests
                (customer_name, email, phone, description, size, quantity, stl_file)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (name, email, phone, description, size, quantity, stl_filename))
            db.commit()
        else:
            db.execute("""INSERT INTO custom_print_requests
                (customer_name, email, phone, description, size, quantity, stl_file)
                VALUES (?,?,?,?,?,?,?)""",
                (name, email, phone, description, size, quantity, stl_filename))
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
                           total_orders=total_orders, pending_orders=pending_orders,
                           total_products=total_products, custom_requests=custom_requests,
                           revenue=round(revenue, 2), recent_orders=recent_orders)


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
        name        = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price       = float(request.form.get("price", 0))
        category    = request.form.get("category", "")
        stock       = int(request.form.get("stock", 0))
        is_lamp     = 1 if request.form.get("is_lamp") == "on" else 0

        # Primary image (lamp-off or main)
        image_value = "default.png"
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename, ALLOWED_IMAGES):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_main_{file.filename}")
                image_value = upload_file(file, "products", filename)

        # Extra images (lamp-on + additional gallery)
        extra_urls = []
        for f in request.files.getlist("extra_images"):
            if f and f.filename and allowed_file(f.filename, ALLOWED_IMAGES):
                fname = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{f.filename}")
                url = upload_file(f, "products", fname)
                if url: extra_urls.append(url)
        extra_images = ",".join(extra_urls)

        db = get_db()
        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("INSERT INTO products (name, description, price, category, image, stock, extra_images, is_lamp) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (name, description, price, category, image_value, stock, extra_images, bool(is_lamp)))
            db.commit()
        else:
            db.execute("INSERT INTO products (name, description, price, category, image, stock, extra_images, is_lamp) VALUES (?,?,?,?,?,?,?,?)",
                (name, description, price, category, image_value, stock, extra_images, is_lamp))
            db.commit()

        flash("Product added successfully!", "success")
        return redirect(url_for("admin_products"))

    categories = ["Name Signs", "Keychains", "Decorative Models", "Functional Products", "Lamps"]
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
        flash("Product not found.", "error"); return redirect(url_for("admin_products"))

    if request.method == "POST":
        name        = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price       = float(request.form.get("price", 0))
        category    = request.form.get("category", "")
        stock       = int(request.form.get("stock", 0))
        is_lamp     = 1 if request.form.get("is_lamp") == "on" else 0

        image_value = product["image"]
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename, ALLOWED_IMAGES):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_main_{file.filename}")
                image_value = upload_file(file, "products", filename)

        existing_extra = product.get("extra_images") or ""
        new_extras = []
        for f in request.files.getlist("extra_images"):
            if f and f.filename and allowed_file(f.filename, ALLOWED_IMAGES):
                fname = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{f.filename}")
                url = upload_file(f, "products", fname)
                if url: new_extras.append(url)

        if request.form.get("clear_extras") == "yes":
            extra_images = ""
        elif new_extras:
            extra_images = ",".join(new_extras)
        else:
            extra_images = existing_extra

        if USE_POSTGRES:
            cur = db.cursor()
            cur.execute("UPDATE products SET name=%s, description=%s, price=%s, category=%s, image=%s, stock=%s, extra_images=%s, is_lamp=%s WHERE id=%s",
                (name, description, price, category, image_value, stock, extra_images, bool(is_lamp), product_id))
            db.commit()
        else:
            db.execute("UPDATE products SET name=?, description=?, price=?, category=?, image=?, stock=?, extra_images=?, is_lamp=? WHERE id=?",
                (name, description, price, category, image_value, stock, extra_images, is_lamp, product_id))
            db.commit()

        flash("Product updated!", "success")
        return redirect(url_for("admin_products"))

    categories = ["Name Signs", "Keychains", "Decorative Models", "Functional Products", "Lamps"]
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
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for("admin_orders"))
        cur.execute("SELECT * FROM order_items WHERE order_id = %s", (order_id,))
        items = cur.fetchall()
    else:
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for("admin_orders"))
        items = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()

    payment_url = get_payment_url(order["payment_screenshot"]) if order["payment_screenshot"] else None
    return render_template("admin_order_detail.html", order=order, items=items, payment_url=payment_url)


@app.route("/admin/orders/<int:order_id>/print")
@admin_required
def admin_print_receipt(order_id):
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for("admin_orders"))
        cur.execute("SELECT * FROM order_items WHERE order_id = %s", (order_id,))
        items = cur.fetchall()
    else:
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for("admin_orders"))
        items = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    return render_template("receipt_print.html", order=order, items=items)


@app.route("/admin/orders/<int:order_id>/delete", methods=["POST"])
@admin_required
def admin_delete_order(order_id):
    confirm_password = request.form.get("confirm_password", "")

    # Verify admin password before deleting
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT password FROM admin WHERE username = %s", (session.get("admin_username"),))
        admin = cur.fetchone()
    else:
        admin = db.execute("SELECT password FROM admin WHERE username = ?", (session.get("admin_username"),)).fetchone()

    if not admin or not check_password_hash(admin["password"], confirm_password):
        flash("Wrong password. Order was NOT deleted.", "error")
        return redirect(url_for("admin_order_detail", order_id=order_id))

    # Get order details before deleting (to remove storage files)
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
    else:
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    if not order:
        flash("Order not found.", "error")
        return redirect(url_for("admin_orders"))

    # Delete payment screenshot from Supabase Storage
    if USE_SUPABASE_STORAGE and supabase_client and order["payment_screenshot"]:
        try:
            filename = order["payment_screenshot"]
            if not filename.startswith("http"):
                supabase_client.storage.from_("payments").remove([filename])
                print(f"[STORAGE] Deleted payment screenshot: {filename}")
        except Exception as e:
            print(f"[STORAGE] Could not delete payment screenshot: {e}")

    # Delete STL file from Supabase Storage (via custom_print_requests)
    if USE_SUPABASE_STORAGE and supabase_client:
        try:
            if USE_POSTGRES:
                cur = db.cursor()
                cur.execute("SELECT stl_file FROM custom_print_requests WHERE email = %s", (order["email"],))
                stl_rows = cur.fetchall()
            else:
                stl_rows = db.execute("SELECT stl_file FROM custom_print_requests WHERE email = ?", (order["email"],)).fetchall()
            for row in stl_rows:
                if row["stl_file"] and not row["stl_file"].startswith("http"):
                    supabase_client.storage.from_("stl-files").remove([row["stl_file"]])
        except Exception as e:
            print(f"[STORAGE] Could not delete STL file: {e}")

    # Delete order items and order from database
    if USE_POSTGRES:
        cur = db.cursor()
        cur.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
        cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
        db.commit()
    else:
        db.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
        db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        db.commit()

    flash(f"Order {order['order_code']} and all associated files deleted permanently.", "info")
    return redirect(url_for("admin_orders"))


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

    # Add STL download URLs
    requests_with_urls = []
    for req in requests_list:
        req_dict = dict(req)
        if req_dict.get("stl_file"):
            req_dict["stl_url"] = get_stl_url(req_dict["stl_file"])
        else:
            req_dict["stl_url"] = None
        requests_with_urls.append(req_dict)

    return render_template("admin_custom_requests.html", requests=requests_with_urls)


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


# ---------------------------------------------------------------------------
# Serve local uploaded files (fallback when not using Supabase Storage)
# ---------------------------------------------------------------------------
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
