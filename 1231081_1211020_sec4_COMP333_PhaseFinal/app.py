# =======================
# Imports + App Setup
# =======================
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort
from functools import wraps
import mysql.connector
import os
from datetime import datetime, timedelta
from decimal import Decimal

# Optional: load .env if exists (recommended)
# This allows you to store DB_USER / DB_PASSWORD / SECRET_KEY in a .env file (not in code).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

app = Flask(__name__)

# Used for Flask session cookies (login/session data stored client-side, signed by this key).
app.secret_key = os.environ.get("SECRET_KEY", "any-secret")  # demo fallback only


# =======================
# DB Connection
# =======================
def get_db():
    """
    Creates a NEW DB connection (mysql.connector).
    IMPORTANT: every place you call get_db() => you must close() connection.
    """
    return mysql.connector.connect(
        user=os.environ.get("DB_USER", "root"),
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        password=os.environ.get("DB_PASSWORD", "baleelabaleela"),
        database=os.environ.get("DB_NAME", "bzulib"),
    )


@app.before_request
def clear_stale_session_user():
    """
    Runs BEFORE every request.
    Goal: if session has user_id but that user no longer exists in DB -> clear session.
    App <-> DB flow:
      - Read session user_id
      - SQL query to validate it exists
      - If not, session.clear()
    """
    uid = session.get("user_id")
    if not uid:
        return

    db = None
    cur = None
    try:
        db = get_db()
        cur = db.cursor()

        # SQL: check user existence
        cur.execute("SELECT 1 FROM users WHERE id=%s LIMIT 1", (uid,))
        ok = cur.fetchone() is not None

        if not ok:
            session.clear()
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


# =======================
# DB Health Check (Debugging)
# =======================
@app.route("/check/db")
def health_db():
    """
    Simple API to verify DB connection works.
    Query used: SELECT 1
    """
    try:
        db = get_db()
        cur = db.cursor()

        # SQL: always returns 1 row
        cur.execute("SELECT 1")
        cur.fetchone()

        cur.close()
        db.close()
        return jsonify({"ok": True, "db": "connected"})
    except Exception as e:
        return jsonify({"ok": False, "db": "error", "error": str(e)}), 500


@app.route("/check/db/info")
def check_db_info():
    """
    Debug endpoint: show what DB you're connected to.
    Queries:
      - SELECT DATABASE()
      - @@hostname
      - @@port
    """
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT DATABASE(), @@hostname, @@port")
    row = cur.fetchone()
    cur.close()
    db.close()
    return jsonify({"ok": True, "database": row[0], "host": row[1], "port": row[2]})


# =======================
# Auth Helpers / Decorators
# =======================
def get_logged_in_user_id():
    """Pulls user_id from Flask session."""
    return session.get("user_id")


def _is_api_request():
    """
    Any route starting with /api/ is treated as an API request:
      - APIs return JSON + HTTP status codes
      - Pages return redirect/HTML
    """
    return request.path.startswith("/api/")


def login_required(view_func):
    """
    Decorator for routes that require login.
    If not logged-in:
      - API => JSON error 401
      - Page => redirect to /login
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            if _is_api_request():
                return jsonify({"ok": False, "error": "NOT_LOGGED_IN"}), 401
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


def admin_required(view_func):
    """
    Decorator for routes that require admin role.
    Checks:
      1) logged in?
      2) session["role"] == "admin" ?
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            if _is_api_request():
                return jsonify({"ok": False, "error": "NOT_LOGGED_IN"}), 401
            flash("Please log in first.", "error")
            return redirect(url_for("login", next=request.path))

        if session.get("role") != "admin":
            if _is_api_request():
                return jsonify({"ok": False, "error": "FORBIDDEN"}), 403
            abort(403)

        return view_func(*args, **kwargs)
    return wrapper


@app.errorhandler(403)
def forbidden(e):
    """Consistent forbidden handling for API vs Pages."""
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "FORBIDDEN"}), 403
    return render_template("403.html"), 403


# =======================
# Shared DB Helpers (Products + Cart Order)
# =======================
def fetch_products(product_type=None, q=None):
    """
    Used by pages: /stationery /ebooks /services /search
    This is the MAIN "product listing query".
    App flow:
      Browser -> route -> fetch_products() -> SQL -> list of dict rows -> render_template
    """
    db = get_db()

    # dictionary=True => rows return as dict: {"id":..., "name":...}
    # (Feature of mysql-connector cursor) :contentReference[oaicite:1]{index=1}
    cur = db.cursor(dictionary=True)

    where = ["p.is_available = 'yes'"]
    params = []

    if product_type:
        where.append("p.product_type = %s")
        params.append(product_type)

    if q:
        where.append("(p.name LIKE %s OR p.description LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like])

    # SQL: list products + join categories to show category_name
    sql = f"""
        SELECT
            p.id, p.name, p.description, p.price, p.product_type,
            p.image_filename, p.is_available,
            p.category_id,
            c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE {" AND ".join(where)}
        ORDER BY p.created_at DESC
    """

    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    db.close()
    return rows


def get_or_create_cart_order_id(user_id):
    """
    Cart design in your app:
      - Cart is stored as an "orders" row with status='pending'
      - order_items holds the cart line items
    This function:
      1) verifies user exists
      2) finds existing pending order
      3) else creates it
    """
    if not user_id:
        raise ValueError("Missing user_id")

    db = None
    cur = None
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)

        # SQL: verify user exists (prevents FK error 1452)
        cur.execute("SELECT id FROM users WHERE id=%s LIMIT 1", (user_id,))
        if not cur.fetchone():
            session.clear()
            raise PermissionError("SESSION_USER_NOT_FOUND_IN_DB")

        # SQL: find pending cart order
        cur.execute(
            "SELECT id FROM orders WHERE user_id=%s AND LOWER(status)='pending' ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = cur.fetchone()
        if row:
            return row["id"]

        # SQL: create new pending cart order
        cur.execute(
            """
            INSERT INTO orders (user_id, total_price, status, notes, order_date)
            VALUES (%s, %s, 'pending', %s, NOW())
            """,
            (user_id, 0, "Cart order")
        )
        db.commit()
        return cur.lastrowid

    except Exception:
        if db:
            db.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


def compute_order_total(order_id):
    """
    Total = SUM(quantity * unit_price) from order_items.
    Query:
      SELECT COALESCE(SUM(quantity * unit_price), 0) ...
      COALESCE() is the “pick the first non-NULL value” function.
    """
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(quantity * unit_price), 0) 
        FROM order_items
        WHERE order_id = %s
    """, (order_id,))
    total = cur.fetchone()[0] or 0
    cur.close()
    db.close()
    return float(total)


def update_order_total_in_db(order_id):
    """
    Recalculate total then persist into orders.total_price.
    Queries:
      1) compute_order_total -> SELECT SUM(...)
      2) UPDATE orders SET total_price=...
    """
    total = compute_order_total(order_id)
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE orders SET total_price=%s WHERE id=%s", (total, order_id))
    db.commit()
    cur.close()
    db.close()
    return total


# =======================
# Inventory Helpers (Admin-ish logic)
# =======================
def get_inventory_stats():
    """
    Inventory dashboard numbers.
    Multiple queries:
      - total products
      - low stock
      - out of stock
      - inventory value
    """
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT COUNT(*) as total FROM products WHERE is_available = 'yes'")
    total_products = cur.fetchone()['total']

    cur.execute("""
        SELECT COUNT(*) as low_stock
        FROM products
        WHERE is_available = 'yes'
        AND stock <= min_stock
    """)
    low_stock = cur.fetchone()['low_stock']

    cur.execute("""
        SELECT COUNT(*) as out_of_stock
        FROM products
        WHERE is_available = 'yes'
        AND stock = 0
    """)
    out_of_stock = cur.fetchone()['out_of_stock']

    cur.execute("""
        SELECT SUM(stock * price) as inventory_value
        FROM products
        WHERE is_available = 'yes'
    """)
    result = cur.fetchone()
    inventory_value = result['inventory_value'] if result['inventory_value'] else 0

    cur.close()
    db.close()

    return {
        'total_products': total_products,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'inventory_value': inventory_value
    }


def get_low_stock_products(limit=10):
    """
    Returns products where stock <= min_stock.
    Query uses JOIN categories for category_name.
    """
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT
            p.id, p.name, p.description, p.price,
            p.product_type, p.stock, p.min_stock,
            p.category_id, c.name as category_name,
            p.image_filename
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_available = 'yes'
        AND p.stock <= p.min_stock
        ORDER BY p.stock ASC
        LIMIT %s
    """, (limit,))

    products = cur.fetchall()
    cur.close()
    db.close()
    return products


# =======================
# Public Pages: Home + Browsing + Product Details
# =======================
@app.route("/")
def index():
    """
    Home page shows featured products (latest 3).
    Query: SELECT ... FROM products LEFT JOIN categories ... LIMIT 3
    """
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT
            p.id,
            p.name,
            p.description,
            p.price,
            p.product_type,
            p.image_filename,
            c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_available = 'yes'
        ORDER BY p.created_at DESC
        LIMIT 3
    """)
    featured_products = cur.fetchall()

    cur.close()
    db.close()
    return render_template("index.html", featured_products=featured_products)


@app.route("/search", endpoint="search")
def search_page():
    """
    Search page uses fetch_products(q=...).
    That helper runs a SQL with LIKE.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return redirect(url_for("index"))

    products = fetch_products(product_type=None, q=q)

    # Returns simple HTML (not a template) - still fine.
    html = [f"<h2>Search results for: {q}</h2>"]
    if not products:
        html.append("<p>No products found.</p>")
        html.append(f'<p><a href="{url_for("index")}">Back to home</a></p>')
        return "\n".join(html)

    html.append("<ul>")
    for p in products:
        pid = p["id"]
        name = p["name"]
        price = p["price"]
        html.append(f'<li><a href="/product/{pid}">{name}</a> — {price}</li>')
    html.append("</ul>")
    html.append(f'<p><a href="{url_for("index")}">Back to home</a></p>')
    return "\n".join(html)


@app.route("/stationery")
def stationery():
    """Stationery page => fetch_products('stationery') => SQL query in helper."""
    q = request.args.get("q", "").strip()
    products = fetch_products("stationery", q=q)
    return render_template("stationery.html", products=products, q=q)


@app.route("/ebooks")
def ebooks():
    """Ebooks page => fetch_products('ebook') => SQL query in helper."""
    q = request.args.get("q", "").strip()
    products = fetch_products("ebook", q=q)
    return render_template("ebooks.html", products=products, q=q)


@app.route("/services")
def services():
    """Services page => fetch_products('service') => SQL query in helper."""
    q = request.args.get("q", "").strip()
    products = fetch_products("service", q=q)
    return render_template("services.html", products=products, q=q)


@app.route("/product/<int:pid>")
def product_details(pid):
    """
    Product details page.
    Query: SELECT p.* + category_name using LEFT JOIN categories
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            p.*,
            c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.id = %s
    """, (pid,))
    product = cur.fetchone()
    cur.close()
    db.close()
    return render_template("product-details.html", product=product)


@app.route("/about")
def about():
    return render_template("about.html")


# =======================
# Public Pages: Branches (read-only)
# =======================
@app.route("/branches")
def branches():
    """
    Public branches list.
    Query: SELECT ... FROM branches ORDER BY id DESC
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT id,name,address,phone,manager_name,open_time,close_time,is_active,monthly_sales,staff_count
        FROM branches
        ORDER BY id DESC
    """)
    branches = cur.fetchall()
    cur.close()
    db.close()
    return render_template("branch.html", branches=branches)


# =======================
# Books Page (Special case: hardcoded list + favorites from DB)
# =======================
@app.route('/books')
def books():
    """
    NOTE: This page is NOT reading books from DB (it uses a hardcoded list).
    But it DOES query favorites table if user logged in to mark favorites.

    DB query here:
      SELECT product_id FROM favorites WHERE user_id=%s
    """
    q = (request.args.get('q') or '').strip()

    products = [
        # هندسة
        {"id": 1, "name": "حساب التفاضل والتكامل المتقدم", "category": "هندسة",
         "description": "كتاب جامعي شامل لطلاب الهندسة", "price": 45.00, "rating": 5,
         "reviews": 128, "stock": 15, "is_new": True, "is_bestseller": True, "discount": 10, "icon": "📚"},

        {"id": 3, "name": "تحليل الدوائر الكهربائية 1", "category": "هندسة",
         "description": "أساسيات تحليل الدوائر الكهربائية مع أمثلة محلولة", "price": 39.00, "rating": 4,
         "reviews": 74, "stock": 12, "is_new": False, "is_bestseller": True, "discount": 0, "icon": "⚡"},

        {"id": 4, "name": "هياكل البيانات والخوارزميات", "category": "هندسة",
         "description": "شرح عملي لهياكل البيانات والخوارزميات مع تمارين", "price": 42.00, "rating": 5,
         "reviews": 210, "stock": 9, "is_new": True, "is_bestseller": True, "discount": 5, "icon": "💻"},

        # علوم
        {"id": 2, "name": "مبادئ الفيزياء العامة", "category": "علوم",
         "description": "كتاب أساسي لطلاب العلوم والهندسة", "price": 35.00, "rating": 4,
         "reviews": 89, "stock": 5, "is_new": False, "is_bestseller": True, "discount": 0, "icon": "🔬"},

        {"id": 5, "name": "الكيمياء العضوية للمبتدئين", "category": "علوم",
         "description": "مدخل للكيمياء العضوية وتطبيقاتها الطبية", "price": 37.50, "rating": 4,
         "reviews": 56, "stock": 18, "is_new": True, "is_bestseller": False, "discount": 0, "icon": "🧪"},

        {"id": 6, "name": "الإحصاء التطبيقي", "category": "علوم",
         "description": "مفاهيم الإحصاء + تطبيقات عملية للطلاب", "price": 29.99, "rating": 4,
         "reviews": 102, "stock": 7, "is_new": False, "is_bestseller": True, "discount": 15, "icon": "📊"},

        # طب
        {"id": 7, "name": "مدخل إلى علم التشريح", "category": "طب",
         "description": "أساسيات التشريح البشري مع رسومات توضيحية", "price": 55.00, "rating": 5,
         "reviews": 140, "stock": 6, "is_new": True, "is_bestseller": True, "discount": 0, "icon": "🫀"},

        {"id": 8, "name": "أساسيات علم الأدوية", "category": "طب",
         "description": "مبادئ علم الأدوية والجرعات والتداخلات", "price": 49.00, "rating": 4,
         "reviews": 91, "stock": 10, "is_new": False, "is_bestseller": False, "discount": 10, "icon": "💊"},

        # آداب
        {"id": 9, "name": "مهارات الكتابة الأكاديمية", "category": "الآداب",
         "description": "كتابة الأبحاث الجامعية والتوثيق والاقتباس", "price": 22.00, "rating": 4,
         "reviews": 65, "stock": 20, "is_new": True, "is_bestseller": False, "discount": 0, "icon": "✍️"},

        {"id": 10, "name": "مدخل إلى علم النفس", "category": "الآداب",
         "description": "نظريات ومفاهيم أساسية في علم النفس", "price": 28.00, "rating": 4,
         "reviews": 77, "stock": 11, "is_new": False, "is_bestseller": True, "discount": 0, "icon": "🧠"},

        # إدارة
        {"id": 11, "name": "مبادئ الإدارة", "category": "إدارة",
         "description": "أساسيات الإدارة والتخطيط والتنظيم والقيادة", "price": 26.50, "rating": 4,
         "reviews": 58, "stock": 14, "is_new": False, "is_bestseller": False, "discount": 5, "icon": "📌"},

        {"id": 12, "name": "المحاسبة المالية 1", "category": "إدارة",
         "description": "مبادئ المحاسبة والقوائم المالية مع أمثلة", "price": 33.00, "rating": 5,
         "reviews": 119, "stock": 8, "is_new": True, "is_bestseller": True, "discount": 0, "icon": "🧾"},
    ]

    # Simple search inside the hardcoded list
    if q:
        qq = q.lower()
        products = [
            p for p in products
            if qq in (p.get("name","").lower() + " " + p.get("description","").lower() + " " + p.get("category","").lower())
        ]

    # Favorites from DB (only if logged in)
    fav_ids = set()
    if session.get("user_id"):
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT product_id FROM favorites WHERE user_id=%s", (session["user_id"],))
        fav_ids = {int(r[0]) for r in cur.fetchall()}
        cur.close()
        db.close()

    for p in products:
        p["is_favorite"] = (int(p.get("id", 0)) in fav_ids)

    return render_template("book.html", products=products, q=q)


# =======================
# Favorites APIs (Student)
# =======================
@app.route("/api/favorites/toggle", methods=["POST"])
@login_required
def api_favorites_toggle():
    """
    App<->DB flow:
      Frontend sends JSON {product_id}
      Backend:
        - SELECT to see if favorite exists
        - DELETE if exists / INSERT if not
      Returns JSON {favorited: true/false}
    """
    user_id = get_logged_in_user_id()
    data = request.get_json(silent=True) or {}
    pid = int(data.get("product_id") or 0)
    if pid <= 0:
        return jsonify({"ok": False, "error": "INVALID_PRODUCT"}), 400

    db = get_db()
    cur = db.cursor()

    # SQL: check existence
    cur.execute("SELECT 1 FROM favorites WHERE user_id=%s AND product_id=%s", (user_id, pid))
    exists = cur.fetchone() is not None

    if exists:
        # SQL: delete favorite
        cur.execute("DELETE FROM favorites WHERE user_id=%s AND product_id=%s", (user_id, pid))
        db.commit()
        cur.close()
        db.close()
        return jsonify({"ok": True, "favorited": False})
    else:
        # SQL: insert favorite
        cur.execute("INSERT INTO favorites (user_id, product_id) VALUES (%s, %s)", (user_id, pid))
        db.commit()
        cur.close()
        db.close()
        return jsonify({"ok": True, "favorited": True})


@app.route("/api/favorites/count", methods=["GET"])
@login_required
def api_favorites_count():
    """Query: COUNT(*) from favorites for logged-in user."""
    user_id = get_logged_in_user_id()
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM favorites WHERE user_id=%s", (user_id,))
    cnt = int(cur.fetchone()[0] or 0)
    cur.close()
    db.close()
    return jsonify({"ok": True, "count": cnt})


# =======================
# Cart Pages (HTML)
# =======================
@app.route("/cart")
@login_required
def cart():
    """
    Cart page reads items from order_items for the user's pending order.
    Queries:
      - get_or_create_cart_order_id -> SELECT/INSERT orders
      - SELECT order_items JOIN products
      - UPDATE orders total
    """
    user_id = get_logged_in_user_id()
    order_id = get_or_create_cart_order_id(user_id)

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            oi.product_id,
            oi.quantity,
            oi.unit_price,
            (oi.quantity * oi.unit_price) AS line_total,
            p.name,
            p.image_filename,
            p.product_type
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = %s
        ORDER BY p.name
    """, (order_id,))
    items = cur.fetchall()
    cur.close()
    db.close()

    total = update_order_total_in_db(order_id)
    return render_template("cart.html", order_id=order_id, items=items, total=total)


# =======================
# Checkout (HTML GET/POST)
# =======================
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    """
    Checkout does:
      GET:
        - show cart items + total
      POST:
        - UPDATE orders status pending -> processing (confirm)
    """
    user_id = get_logged_in_user_id()
    order_id = get_or_create_cart_order_id(user_id)

    # Query: get items in cart
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            oi.product_id,
            oi.quantity,
            oi.unit_price,
            (oi.quantity * oi.unit_price) AS line_total,
            p.name,
            p.image_filename,
            p.product_type
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = %s
        ORDER BY p.name
    """, (order_id,))
    items = cur.fetchall()
    cur.close()
    db.close()

    if not items:
        return render_template("checkout.html", order_id=order_id, items=[], total=0)

    total = update_order_total_in_db(order_id)

    if request.method == "GET":
        return render_template("checkout.html", order_id=order_id, items=items, total=total)

    # POST confirm
    db = get_db()
    cur = db.cursor()

    # SQL: confirm only if currently pending
    cur.execute(
        "UPDATE orders SET status='processing' WHERE id=%s AND user_id=%s AND LOWER(status)='pending'",
        (order_id, user_id)
    )
    db.commit()
    changed = cur.rowcount
    cur.close()
    db.close()

    if changed == 0:
        flash("This order was already confirmed or is no longer pending.", "error")
        return redirect(url_for("cart"))

    flash(f"Order confirmed ✅ Order ID: {order_id}", "success")
    return redirect(url_for("index"))


# =======================
# Cart APIs (JSON) - add / remove / update / get
# =======================
@app.route("/api/cart/items", methods=["POST"])
@login_required
def api_cart_items_add_compat():
    """
    Compatibility endpoint (supports quantity/qty field names).
    Flow:
      - find/create pending order
      - validate product exists + available
      - UPDATE existing order_items row OR INSERT new
      - compute + UPDATE total
      - return total + item count
    """
    user_id = get_logged_in_user_id()

    data = request.get_json(silent=True) or {}
    product_id = int(data.get("product_id") or 0)
    qty = int(data.get("quantity") or data.get("qty") or 1)

    if product_id <= 0 or qty <= 0:
        return jsonify({"ok": False, "error": "INVALID_INPUT"}), 400

    order_id = get_or_create_cart_order_id(user_id)

    db = get_db()
    cur = db.cursor(dictionary=True)

    # SQL: product validation
    cur.execute("SELECT id, price, is_available FROM products WHERE id=%s", (product_id,))
    p = cur.fetchone()
    if not p:
        cur.close()
        db.close()
        return jsonify({"ok": False, "error": "PRODUCT_NOT_FOUND"}), 404
    if p.get("is_available") != "yes":
        cur.close()
        db.close()
        return jsonify({"ok": False, "error": "PRODUCT_NOT_AVAILABLE"}), 400

    unit_price = float(p["price"])

    # SQL: check if item already in cart
    cur.execute(
        "SELECT quantity FROM order_items WHERE order_id=%s AND product_id=%s",
        (order_id, product_id)
    )
    row = cur.fetchone()

    if row:
        # SQL: update qty
        cur.execute(
            "UPDATE order_items SET quantity = quantity + %s WHERE order_id=%s AND product_id=%s",
            (qty, order_id, product_id)
        )
    else:
        # SQL: insert new row
        cur.execute(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
            (order_id, product_id, qty, unit_price)
        )

    db.commit()
    cur.close()
    db.close()

    total = update_order_total_in_db(order_id)

    # Query: count items in cart
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COALESCE(SUM(quantity),0) FROM order_items WHERE order_id=%s", (order_id,))
    count = int(cur.fetchone()[0] or 0)
    cur.close()
    db.close()

    return jsonify({"ok": True, "order_id": order_id, "total": total, "count": count})


@app.route("/api/cart/add", methods=["POST"])
@login_required
def api_cart_add():
    """
    Same logic as compat but expects {product_id, qty}.
    Queries:
      - SELECT product
      - SELECT order_items
      - UPDATE/INSERT order_items
      - UPDATE orders total
    """
    user_id = get_logged_in_user_id()

    data = request.get_json(silent=True) or {}
    product_id = int(data.get("product_id") or 0)
    qty = int(data.get("qty") or 1)
    if product_id <= 0 or qty <= 0:
        return jsonify({"ok": False, "error": "INVALID_INPUT"}), 400

    order_id = get_or_create_cart_order_id(user_id)

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT id, price, is_available FROM products WHERE id=%s", (product_id,))
    p = cur.fetchone()
    if not p:
        cur.close()
        db.close()
        return jsonify({"ok": False, "error": "PRODUCT_NOT_FOUND"}), 404
    if p.get("is_available") != "yes":
        cur.close()
        db.close()
        return jsonify({"ok": False, "error": "PRODUCT_NOT_AVAILABLE"}), 400

    unit_price = float(p["price"])

    cur.execute(
        "SELECT quantity FROM order_items WHERE order_id=%s AND product_id=%s",
        (order_id, product_id)
    )
    row = cur.fetchone()

    if row:
        cur.execute(
            "UPDATE order_items SET quantity = quantity + %s WHERE order_id=%s AND product_id=%s",
            (qty, order_id, product_id)
        )
    else:
        cur.execute(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
            (order_id, product_id, qty, unit_price)
        )

    db.commit()
    cur.close()
    db.close()

    total = update_order_total_in_db(order_id)
    return jsonify({"ok": True, "order_id": order_id, "total": total})


@app.route("/api/cart/remove", methods=["POST"])
@login_required
def api_cart_remove():
    """
    Remove an item from cart.
    Query: DELETE FROM order_items WHERE order_id=? AND product_id=?
    """
    user_id = get_logged_in_user_id()

    data = request.get_json(silent=True) or {}
    product_id = int(data.get("product_id") or 0)
    if product_id <= 0:
        return jsonify({"ok": False, "error": "INVALID_INPUT"}), 400

    order_id = get_or_create_cart_order_id(user_id)

    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM order_items WHERE order_id=%s AND product_id=%s", (order_id, product_id))
    db.commit()
    cur.close()
    db.close()

    total = update_order_total_in_db(order_id)
    return jsonify({"ok": True, "order_id": order_id, "total": total})


@app.route("/api/cart/update", methods=["POST"])
@login_required
def api_cart_update():
    """
    Update quantity:
      - if qty <= 0 => delete row
      - else => update row qty
    """
    user_id = get_logged_in_user_id()

    data = request.get_json(silent=True) or {}
    product_id = int(data.get("product_id") or 0)
    qty = int(data.get("qty") or 0)
    if product_id <= 0:
        return jsonify({"ok": False, "error": "INVALID_INPUT"}), 400

    order_id = get_or_create_cart_order_id(user_id)

    db = get_db()
    cur = db.cursor()
    if qty <= 0:
        cur.execute("DELETE FROM order_items WHERE order_id=%s AND product_id=%s", (order_id, product_id))
    else:
        cur.execute(
            "UPDATE order_items SET quantity=%s WHERE order_id=%s AND product_id=%s",
            (qty, order_id, product_id)
        )
    db.commit()
    cur.close()
    db.close()

    total = update_order_total_in_db(order_id)
    return jsonify({"ok": True, "order_id": order_id, "total": total})


@app.route("/api/cart", methods=["GET"])
@login_required
def api_cart_get():
    """
    Returns cart state as JSON (used by frontend JS).
    Query: SELECT order_items JOIN products
    """
    user_id = get_logged_in_user_id()
    order_id = get_or_create_cart_order_id(user_id)

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            oi.product_id,
            oi.quantity,
            oi.unit_price,
            (oi.quantity * oi.unit_price) AS line_total,
            p.name,
            p.image_filename,
            p.product_type
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = %s
        ORDER BY p.name
    """, (order_id,))
    items = cur.fetchall()
    cur.close()
    db.close()

    total = compute_order_total(order_id)
    count = sum(int(it.get("quantity") or 0) for it in items)
    return jsonify({"ok": True, "order_id": order_id, "items": items, "total": total, "count": count})


# =======================
# Student: My Orders (HTML)
# =======================
@app.route("/my-orders")
@login_required
def my_orders():
    """
    List confirmed orders (exclude pending cart).
    Query:
      SELECT ... FROM orders WHERE user_id=? AND status <> 'pending'
    """
    user_id = get_logged_in_user_id()

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            o.id,
            o.order_date,
            o.status,
            o.total_price,
            o.notes
        FROM orders o
        WHERE o.user_id = %s
         AND LOWER(o.status) <> 'pending'
        ORDER BY o.order_date DESC, o.id DESC
    """, (user_id,))
    orders = cur.fetchall()
    cur.close()
    db.close()

    return render_template("my-orders.html", orders=orders)


@app.route("/my-orders/<int:order_id>")
@login_required
def my_order_details(order_id):
    """
    Order details for a specific order (must belong to logged-in user).
    Queries:
      1) SELECT order by id + user_id
      2) SELECT items JOIN products
    """
    user_id = get_logged_in_user_id()

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT id, user_id, order_date, status, total_price, notes
        FROM orders
        WHERE id = %s AND user_id = %s
        LIMIT 1
    """, (order_id, user_id))
    order = cur.fetchone()

    if not order:
        cur.close()
        db.close()
        flash("Order not found or not allowed.", "error")
        return redirect(url_for("my_orders"))

    cur.execute("""
        SELECT
            oi.product_id,
            p.name,
            p.product_type,
            oi.quantity,
            oi.unit_price,
            (oi.quantity * oi.unit_price) AS line_total
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = %s
        ORDER BY p.name
    """, (order_id,))
    items = cur.fetchall()

    cur.close()
    db.close()

    computed_total = sum(float(it["line_total"]) for it in items) if items else 0.0
    total_to_show = float(order["total_price"] or 0)
    if total_to_show <= 0:
        total_to_show = computed_total

    return render_template("order-details.html", order=order, items=items, total=total_to_show)


# =======================
# Student Dashboard (HTML)
# =======================
@app.route("/student/dashboard")
@login_required
def student_dashboard():
    """
    Dashboard counts are computed with queries and stored in session for HTML.
    Queries:
      - COUNT favorites
      - COUNT orders (exclude pending)
    """
    if session.get("role") != "student":
        abort(403)

    user_id = get_logged_in_user_id()

    # defaults
    orders_count = 0
    books_count = 0
    points = 0
    favorites_count = 0

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT COUNT(*) FROM favorites WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    favorites_count = int(row[0] or 0) if row else 0

    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE user_id=%s AND LOWER(status) <> 'pending'
    """, (user_id,))
    row = cur.fetchone()
    orders_count = int(row[0] or 0) if row else 0

    cur.close()
    db.close()

    session["favorites"] = favorites_count
    session["orders_count"] = orders_count
    session["books_count"] = books_count
    session["points"] = points

    return render_template("student-dashboard.html")


# =======================
# Student API: Create Direct Order (not cart)
# =======================
@app.route("/api/orders/create", methods=["POST"])
@login_required
def api_orders_create():
    """
    Creates an order immediately (status='processing') for one product.
    Queries:
      - SELECT product price + availability
      - INSERT INTO orders (...) status='processing'
    """
    user_id = get_logged_in_user_id()
    data = request.get_json(silent=True) or {}

    product_id = int(data.get("product_id") or 0)
    order_type = (data.get("order_type") or "").strip()
    pickup_branch = (data.get("pickup_branch") or "").strip()
    pickup_date = (data.get("pickup_date") or "").strip()
    notes = (data.get("notes") or "").strip()

    if product_id <= 0 or not order_type or not pickup_branch or not pickup_date:
        return jsonify({"ok": False, "error": "MISSING_FIELDS"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT price, is_available FROM products WHERE id=%s", (product_id,))
    p = cur.fetchone()
    if not p:
        cur.close()
        db.close()
        return jsonify({"ok": False, "error": "PRODUCT_NOT_FOUND"}), 404

    if (p.get("is_available") or "") != "yes":
        cur.close()
        db.close()
        return jsonify({"ok": False, "error": "PRODUCT_NOT_AVAILABLE"}), 400

    price = float(p.get("price") or 0)

    cur2 = db.cursor()
    cur2.execute("""
        INSERT INTO orders (user_id, total_price, status, notes, order_date)
        VALUES (%s, %s, 'processing', %s, NOW())
    """, (user_id, price, f"TYPE={order_type} | BRANCH={pickup_branch} | DATE={pickup_date} | {notes}"))
    db.commit()
    order_id = cur2.lastrowid

    cur2.close()
    cur.close()
    db.close()

    return jsonify({"ok": True, "order_id": order_id})


# =======================
# Auth Pages: Login / Register / Logout
# =======================
@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Login reads user from DB and stores user info in session.
    Query:
      SELECT id, full_name, email, role, status FROM users WHERE email/password/role...
    """
    next_url = (request.args.get("next") or "").strip()

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        role = (request.form.get("role") or "student").strip().lower()
        next_url = (request.form.get("next") or next_url or "").strip()

        db = get_db()
        cur = db.cursor(dictionary=True)

        cur.execute(
            """
            SELECT id, full_name, email, role, status
            FROM users
            WHERE LOWER(email) = %s
              AND password = %s
              AND LOWER(role) = %s
            LIMIT 1
            """,
            (email, password, role)
        )
        user = cur.fetchone()
        cur.close()
        db.close()

        if not user:
            flash("بيانات الدخول غير صحيحة (الإيميل / كلمة المرور / نوع الحساب).", "error")
            return render_template("login.html", next=next_url, email=email, role=role)

        if (user.get("status") or "").lower() != "active":
            flash("هذا الحساب غير مفعل.", "error")
            return render_template("login.html", next=next_url, email=email, role=role)

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["full_name"]
        session["role"] = (user["role"] or "").lower()

        # If student, ensure they have a pending cart order
        if session["role"] == "student":
            get_or_create_cart_order_id(user["id"])

        if next_url.startswith("/"):
            return redirect(next_url)

        if session["role"] == "admin":
            return redirect(url_for("admin_dashboard"))

        return redirect(url_for("student_dashboard"))

    return render_template("login.html", next=next_url)


@app.route("/register", methods=["GET", "POST"])
def register():
    """
    Registration creates a new user in DB.
    Queries:
      - SELECT id FROM users WHERE email=?
      - INSERT INTO users(...)
    """
    if request.method == "POST":
        full_name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "student").strip()

        if not full_name or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for("register"))

        db = get_db()
        cur = db.cursor(dictionary=True)

        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close()
            db.close()
            flash("Email already used. Please login.", "error")
            return redirect(url_for("login"))

        cur.execute(
            "INSERT INTO users (full_name, email, password, role, status) VALUES (%s, %s, %s, %s, 'active')",
            (full_name, email, password, role)
        )
        db.commit()
        cur.close()
        db.close()

        flash("Account created! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    """Clear session => user logged out."""
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


# =======================
# Admin Pages (HTML)
# =======================
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    return render_template("admin-dashboard.html")


@app.route("/admin/orders")
@admin_required
def admin_orders():
    """
    Admin orders page.
    Query:
      SELECT orders JOIN users (show customer_name)
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            o.id          AS order_id,
            u.full_name   AS customer_name,
            o.total_price AS total_price,
            o.status      AS status,
            o.order_date  AS order_date,
            o.notes       AS notes
        FROM orders o
        JOIN users u ON o.user_id = u.id
        ORDER BY o.order_date DESC
    """)
    orders = cur.fetchall()
    cur.close()
    db.close()
    return render_template("orders.html", orders=orders)


@app.route("/admin/products")
@admin_required
def admin_products():
    """
    Admin products management page.
    Queries:
      - SELECT products + categories
      - SELECT categories list for dropdown
    """
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT
            p.id, p.name, p.description, p.price, p.product_type,
            p.category_id,
            p.image_filename, p.is_available, p.created_at,
            p.stock, p.min_stock,
            c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.is_available = 'yes'
        ORDER BY p.created_at DESC, p.id DESC
    """)
    products = cur.fetchall()

    cur.execute("SELECT id, name FROM categories ORDER BY name")
    categories = cur.fetchall()

    cur.close()
    db.close()

    return render_template("admin-products.html", products=products, categories=categories)


@app.route("/admin/reports")
@admin_required
def admin_reports():
    return render_template("reports.html")


@app.route("/admin/settings")
@admin_required
def admin_settings():
    return render_template("settings.html")


def _time_to_hhmm(v):
    """Helper to convert time/timedelta to 'HH:MM' for HTML/JS."""
    if v is None:
        return None
    if isinstance(v, timedelta):
        total = int(v.total_seconds())
        h = (total // 3600) % 24
        m = (total % 3600) // 60
        return f"{h:02d}:{m:02d}"
    s = str(v)
    return s[:5]


@app.route("/admin/branches")
@admin_required
def admin_branches():
    """
    Admin branches page (HTML).
    Query: SELECT branches...
    Then convert times + decimals for JSON usage in templates.
    """
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT id, name, city, address, phone, manager_name, open_time, close_time, is_active, monthly_sales, staff_count
        FROM branches
        ORDER BY id DESC
    """)
    branches = cur.fetchall()
    cur.close()
    db.close()

    for b in branches:
        b["open_time"] = _time_to_hhmm(b.get("open_time"))
        b["close_time"] = _time_to_hhmm(b.get("close_time"))

        ms = b.get("monthly_sales")
        if isinstance(ms, Decimal):
            b["monthly_sales"] = float(ms)

        try:
            b["is_active"] = int(b.get("is_active") or 0)
        except Exception:
            b["is_active"] = 0

    total = len(branches)
    active = sum(1 for b in branches if int(b.get("is_active") or 0) == 1)
    staff_total = sum(int(b.get("staff_count") or 0) for b in branches)
    sales_total = sum(float(b.get("monthly_sales") or 0) for b in branches)

    stats = {
        "total": total,
        "active": active,
        "staff_total": staff_total,
        "sales_total": sales_total
    }

    return render_template("branches-admin.html", branches=branches, stats=stats)


@app.route("/admin/ebooks")
@admin_required
def admin_ebooks():
    return render_template("ebooks.html")


@app.route("/inventory_management.html")
def inventory():
    # Placeholder page: (no DB query here yet)
    return render_template("inventory_management.html")


# =======================
# Admin APIs: Products (JSON CRUD)
# =======================
@app.route("/api/admin/products", methods=["GET"])
@admin_required
def api_admin_list_products():
    """
    Query: SELECT products LEFT JOIN categories
    Returns JSON list for admin frontend.
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            p.id, p.name, p.description, p.price, p.product_type,
            p.category_id,
            p.image_filename, p.is_available,
            p.created_at, p.stock, p.min_stock, p.last_restock,
            c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        ORDER BY p.created_at DESC, p.id DESC
    """)
    products = cur.fetchall()
    cur.close()
    db.close()
    return jsonify({"ok": True, "products": products})


@app.route("/api/admin/products", methods=["POST"])
@admin_required
def api_admin_create_product():
    """
    Create product.
    Query: INSERT INTO products(...)
    """
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    product_type = (data.get("product_type") or "").strip()
    is_available = (data.get("is_available") or "yes").strip()
    category_id = data.get("category_id", None)
    price = data.get("price", None)
    stock = data.get("stock", 0)
    min_stock = data.get("min_stock", 10)

    if not name or not product_type or price is None:
        return jsonify({"ok": False, "error": "Missing required fields (name, product_type, price)."}), 400

    try:
        price = float(price)
        stock = int(stock)
        min_stock = int(min_stock)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid numeric fields."}), 400

    if is_available not in ("yes", "no"):
        return jsonify({"ok": False, "error": "is_available must be 'yes' or 'no'."}), 400

    if category_id in ("", None):
        category_id = None
    else:
        try:
            category_id = int(category_id)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid category_id."}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        INSERT INTO products (name, description, price, product_type, category_id,
                              is_available, stock, min_stock, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """, (name, description, price, product_type, category_id, is_available, stock, min_stock))

    db.commit()
    new_id = cur.lastrowid

    cur.close()
    db.close()

    return api_admin_get_product(new_id)


@app.route("/api/admin/products/<int:pid>", methods=["GET"])
@admin_required
def api_admin_get_product(pid):
    """
    Query: SELECT single product by id
    """
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT
            p.id, p.name, p.description, p.price, p.product_type,
            p.category_id, p.image_filename, p.is_available,
            p.created_at, p.stock, p.min_stock, p.last_restock,
            c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.id = %s
        LIMIT 1
    """, (pid,))
    product = cur.fetchone()

    cur.close()
    db.close()

    if not product:
        return jsonify({"ok": False, "error": "Product not found"}), 404

    return jsonify({"ok": True, "product": product})


@app.route("/api/admin/products/<int:pid>", methods=["PUT"])
@admin_required
def api_admin_update_product(pid):
    """
    Update product.
    Query: UPDATE products SET ... WHERE id=?
    """
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    product_type = (data.get("product_type") or "").strip()
    is_available = (data.get("is_available") or "").strip()
    category_id = data.get("category_id", None)
    price = data.get("price", None)
    stock = data.get("stock", None)
    min_stock = data.get("min_stock", None)

    if not name or not product_type or price is None:
        return jsonify({"ok": False, "error": "Missing required fields (name, product_type, price)."}), 400

    try:
        price = float(price)
        if stock is not None:
            stock = int(stock)
        if min_stock is not None:
            min_stock = int(min_stock)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid numeric fields."}), 400

    if is_available not in ("yes", "no"):
        return jsonify({"ok": False, "error": "is_available must be 'yes' or 'no'."}), 400

    if category_id in ("", None):
        category_id = None
    else:
        try:
            category_id = int(category_id)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid category_id."}), 400

    db = get_db()
    cur = db.cursor()

    update_fields = []
    params = []

    update_fields.append("name = %s"); params.append(name)
    update_fields.append("description = %s"); params.append(description)
    update_fields.append("price = %s"); params.append(price)
    update_fields.append("product_type = %s"); params.append(product_type)
    update_fields.append("category_id = %s"); params.append(category_id)
    update_fields.append("is_available = %s"); params.append(is_available)

    if stock is not None:
        update_fields.append("stock = %s"); params.append(stock)
    if min_stock is not None:
        update_fields.append("min_stock = %s"); params.append(min_stock)

    params.append(pid)

    sql = f"UPDATE products SET {', '.join(update_fields)} WHERE id = %s"
    cur.execute(sql, params)
    db.commit()
    changed = cur.rowcount

    cur.close()
    db.close()

    if changed == 0:
        return jsonify({"ok": False, "error": "Product not found or no changes."}), 404

    return api_admin_get_product(pid)


@app.route("/api/admin/products/<int:pid>", methods=["DELETE"])
@admin_required
def api_admin_delete_product(pid):
    """
    Delete product.
    Query: DELETE FROM products WHERE id=?
    """
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM products WHERE id=%s", (pid,))
    db.commit()
    changed = cur.rowcount
    cur.close()
    db.close()

    if changed == 0:
        return jsonify({"ok": False, "error": "Product not found."}), 404
    return jsonify({"ok": True})


# =======================
# Admin APIs: Branches (JSON CRUD)
# =======================
def _parse_hhmm(s):
    """Accept 'HH:MM' or 'HH:MM:SS' and return 'HH:MM:SS' (or None)."""
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) < 2:
        return None
    h = parts[0].zfill(2)
    m = parts[1].zfill(2)
    sec = "00"
    if len(parts) >= 3:
        sec = parts[2].zfill(2)
    return f"{h}:{m}:{sec}"


@app.route("/api/admin/branches", methods=["GET"])
@admin_required
def api_admin_list_branches():
    """
    Query: SELECT branches list
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT id, name, city, address, phone, manager_name,
               open_time, close_time, is_active, monthly_sales, staff_count, created_at
        FROM branches
        ORDER BY id DESC
    """)
    rows = cur.fetchall()
    cur.close()
    db.close()

    for b in rows:
        b["open_time"] = _time_to_hhmm(b.get("open_time"))
        b["close_time"] = _time_to_hhmm(b.get("close_time"))

        ms = b.get("monthly_sales")
        if isinstance(ms, Decimal):
            b["monthly_sales"] = float(ms)
        try:
            b["is_active"] = int(b.get("is_active") or 0)
        except Exception:
            b["is_active"] = 0

    return jsonify({"ok": True, "branches": rows})


@app.route("/api/admin/branches", methods=["POST"])
@admin_required
def api_admin_create_branch():
    """
    Create branch.
    Query: INSERT INTO branches(...)
    """
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    city = (data.get("city") or "").strip()
    address = (data.get("address") or "").strip()
    phone = (data.get("phone") or "").strip()
    manager_name = (data.get("manager_name") or "").strip()

    open_time = _parse_hhmm((data.get("open_time") or "").strip())
    close_time = _parse_hhmm((data.get("close_time") or "").strip())

    is_active = data.get("is_active", 1)
    staff_count = data.get("staff_count", 0)
    monthly_sales = data.get("monthly_sales", 0)

    if not name:
        return jsonify({"ok": False, "error": "Missing required field: name"}), 400

    try:
        is_active = int(is_active)
        staff_count = int(staff_count)
        monthly_sales = float(monthly_sales)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid numeric fields"}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO branches
          (name, city, address, phone, manager_name, open_time, close_time, is_active, monthly_sales, staff_count, created_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """, (name, city or None, address or None, phone or None, manager_name or None,
          open_time, close_time, is_active, monthly_sales, staff_count))
    db.commit()
    new_id = cur.lastrowid
    cur.close()
    db.close()

    return api_admin_get_branch(new_id)


@app.route("/api/admin/branches/<int:bid>", methods=["GET"])
@admin_required
def api_admin_get_branch(bid):
    """
    Query: SELECT branch by id
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT id, name, city, address, phone, manager_name,
               open_time, close_time, is_active, monthly_sales, staff_count, created_at
        FROM branches
        WHERE id=%s
        LIMIT 1
    """, (bid,))
    b = cur.fetchone()
    cur.close()
    db.close()

    if not b:
        return jsonify({"ok": False, "error": "Branch not found"}), 404

    b["open_time"] = _time_to_hhmm(b.get("open_time"))
    b["close_time"] = _time_to_hhmm(b.get("close_time"))

    ms = b.get("monthly_sales")
    if isinstance(ms, Decimal):
        b["monthly_sales"] = float(ms)

    try:
        b["is_active"] = int(b.get("is_active") or 0)
    except Exception:
        b["is_active"] = 0

    return jsonify({"ok": True, "branch": b})


@app.route("/api/admin/branches/<int:bid>", methods=["PUT"])
@admin_required
def api_admin_update_branch(bid):
    """
    Update branch.
    Query: UPDATE branches SET ... WHERE id=?
    """
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    city = (data.get("city") or "").strip()
    address = (data.get("address") or "").strip()
    phone = (data.get("phone") or "").strip()
    manager_name = (data.get("manager_name") or "").strip()

    open_time = _parse_hhmm((data.get("open_time") or "").strip())
    close_time = _parse_hhmm((data.get("close_time") or "").strip())

    is_active = data.get("is_active", None)
    staff_count = data.get("staff_count", None)
    monthly_sales = data.get("monthly_sales", None)

    if not name:
        return jsonify({"ok": False, "error": "Missing required field: name"}), 400

    update_fields = []
    params = []

    update_fields.append("name=%s"); params.append(name)
    update_fields.append("city=%s"); params.append(city or None)
    update_fields.append("address=%s"); params.append(address or None)
    update_fields.append("phone=%s"); params.append(phone or None)
    update_fields.append("manager_name=%s"); params.append(manager_name or None)

    update_fields.append("open_time=%s"); params.append(open_time)
    update_fields.append("close_time=%s"); params.append(close_time)

    if is_active is not None:
        try:
            is_active = int(is_active)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid is_active"}), 400
        update_fields.append("is_active=%s"); params.append(is_active)

    if staff_count is not None:
        try:
            staff_count = int(staff_count)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid staff_count"}), 400
        update_fields.append("staff_count=%s"); params.append(staff_count)

    if monthly_sales is not None:
        try:
            monthly_sales = float(monthly_sales)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid monthly_sales"}), 400
        update_fields.append("monthly_sales=%s"); params.append(monthly_sales)

    params.append(bid)

    db = get_db()
    cur = db.cursor()
    sql = f"UPDATE branches SET {', '.join(update_fields)} WHERE id=%s"
    cur.execute(sql, params)
    db.commit()
    changed = cur.rowcount
    cur.close()
    db.close()

    if changed == 0:
        return jsonify({"ok": False, "error": "Branch not found or no changes"}), 404

    return api_admin_get_branch(bid)


@app.route("/api/admin/branches/<int:bid>", methods=["DELETE"])
@admin_required
def api_admin_delete_branch(bid):
    """
    Delete branch.
    Query: DELETE FROM branches WHERE id=?
    """
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM branches WHERE id=%s", (bid,))
    db.commit()
    changed = cur.rowcount
    cur.close()
    db.close()

    if changed == 0:
        return jsonify({"ok": False, "error": "Branch not found"}), 404
    return jsonify({"ok": True})


# =======================
# Admin API: Orders (JSON)
# =======================
@app.route("/api/orders", methods=["GET"])
@admin_required
def api_get_orders():
    """
    Query: SELECT orders JOIN users
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            o.id          AS order_id,
            u.full_name   AS customer_name,
            o.total_price AS total_price,
            o.status      AS status,
            o.order_date  AS order_date,
            o.notes       AS notes
        FROM orders o
        JOIN users u ON o.user_id = u.id
        ORDER BY o.order_date DESC
    """)
    orders = cur.fetchall()
    cur.close()
    db.close()
    return jsonify({"ok": True, "orders": orders})


@app.route("/api/orders/<int:order_id>", methods=["PUT"])
@admin_required
def api_update_order(order_id):
    """
    Update order status/notes (admin).
    Query: UPDATE orders SET status=?, notes=? WHERE id=?
    """
    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").strip()
    new_notes = (data.get("notes") or "").strip()

    allowed = {"pending", "processing", "completed", "canceled"}
    if new_status and new_status not in allowed:
        return jsonify({"ok": False, "error": f"Invalid status '{new_status}'"}), 400

    db = get_db()
    cur = db.cursor()

    if new_status:
        cur.execute(
            "UPDATE orders SET status=%s, notes=%s WHERE id=%s",
            (new_status, new_notes, order_id)
        )
    else:
        cur.execute(
            "UPDATE orders SET notes=%s WHERE id=%s",
            (new_notes, order_id)
        )

    db.commit()
    cur.close()
    db.close()

    return jsonify({"ok": True})


# =======================
# Compatibility Routes (Old HTML file names)
# =======================
@app.route("/index.html")
def index_html():
    return redirect(url_for("index"))

@app.route("/book.html")
def book_html():
    return redirect(url_for("books"))

@app.route("/stationery.html")
def stationery_html():
    return redirect(url_for("stationery"))

@app.route("/ebooks.html")
def ebooks_html():
    return redirect(url_for("ebooks"))

@app.route("/services.html")
def services_html():
    return redirect(url_for("services"))

@app.route("/branch.html")
def branch_html():
    return redirect(url_for("branches"))

@app.route("/about.html")
def about_html():
    return redirect(url_for("about"))

@app.route("/cart.html")
def cart_html():
    return redirect(url_for("cart"))

@app.route("/checkout.html")
def checkout_html():
    return redirect(url_for("checkout"))

@app.route("/login.html")
def login_html():
    return redirect(url_for("login"))

@app.route("/register.html")
def register_html():
    return redirect(url_for("register"))

# Admin old file links
@app.route("/admin-dashboard.html")
def admin_dashboard_html():
    return redirect(url_for("admin_dashboard"))

@app.route("/admin-orders.html")
def admin_orders_html():
    return redirect(url_for("admin_orders"))

@app.route("/admin/admin-orders.html")
def admin_admin_orders_html():
    return redirect(url_for("admin_orders"))

@app.route("/admin/admin-ebooks.html")
def admin_admin_ebooks_html():
    return redirect(url_for("admin_ebooks"))

@app.route("/admin/admin-products.html")
def admin_admin_products_html():
    return redirect(url_for("admin_products"))


# =======================
# Run App
# =======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=port)
