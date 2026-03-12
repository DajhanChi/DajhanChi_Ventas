import os
import sqlite3
import threading
import time
import json
from collections import defaultdict
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from dotenv import load_dotenv

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress
from werkzeug.security import generate_password_hash, check_password_hash

# Cargar variables de entorno desde archivo .env
load_dotenv()


app = Flask(__name__)
Compress(app)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-in-production")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["COMPRESS_LEVEL"] = 4
app.config["COMPRESS_MIN_SIZE"] = 1000

# Configuración de protección de usuario (usar variables de entorno en producción)
PROTECTED_USERNAME = os.getenv("PROTECTED_USERNAME", "dajhanchi")
PROTECTED_USER_SECRET = os.getenv("PROTECTED_USER_SECRET", "default-insecure-key-change-in-production")

# Solo configurar la base de datos si no se ha configurado externamente
if not app.config.get("SQLALCHEMY_DATABASE_URI"):
    instance_db_path = os.path.join(app.instance_path, "app.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{instance_db_path}"


db = SQLAlchemy(app)
migrate = Migrate(app, db)
_db_initialized = False
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
BACKUP_RETENTION = 7
BACKUP_TIME = "00:00"


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="admin")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    sku = db.Column(db.String(64), nullable=True, index=True)
    package_cost_cents = db.Column(db.Integer, nullable=False, default=0)
    package_quantity = db.Column(db.Integer, nullable=False, default=1)
    cost_cents = db.Column(db.Integer, nullable=False, default=0)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0, index=True)
    minimum_stock = db.Column(db.Integer, nullable=False, default=5)
    
    user = db.relationship("User", backref=db.backref("products", lazy=True))


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    customer_name = db.Column(db.String(160))
    payment_method = db.Column(db.String(20), nullable=False, default="efectivo")  # efectivo, yape, fiado
    total_cents = db.Column(db.Integer, nullable=False, default=0)
    paid_cents = db.Column(db.Integer, nullable=False, default=0)
    payment_status = db.Column(db.String(20), nullable=False, default="pagado")  # pagado, pendiente, parcial
    
    user = db.relationship("User", backref=db.backref("sales", lazy=True))
    
    @property
    def pending_cents(self):
        return max(0, self.total_cents - self.paid_cents)


class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    unit_price_cents = db.Column(db.Integer, nullable=False, default=0)
    line_total_cents = db.Column(db.Integer, nullable=False, default=0)

    sale = db.relationship("Sale", backref=db.backref("items", lazy=True))
    product = db.relationship("Product")


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(20), nullable=False, default="efectivo")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    notes = db.Column(db.String(255))
    
    sale = db.relationship("Sale", backref=db.backref("payments", lazy=True, cascade="all, delete-orphan"))


class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True, index=True)
    stock_yellow_threshold = db.Column(db.Integer, nullable=False, default=10)
    
    # Permisos por rol: JSON con estructura {modulo: bool}
    admin_permissions = db.Column(db.String(500), nullable=False, default='{"dashboard":true,"products":true,"sales":true,"debts":true,"reports":true,"users":true,"settings":true}')
    gerente_permissions = db.Column(db.String(500), nullable=False, default='{"dashboard":true,"products":true,"sales":true,"debts":true,"reports":true,"users":false,"settings":false}')
    vendedor_permissions = db.Column(db.String(500), nullable=False, default='{"dashboard":false,"products":true,"sales":true,"debts":false,"reports":false,"users":false,"settings":false}')
    
    user = db.relationship("User", backref=db.backref("settings", uselist=False))
    
    def get_role_permissions(self, role):
        """Get permissions for a specific role"""
        if role == "admin":
            perms = self.admin_permissions
        elif role == "gerente":
            perms = self.gerente_permissions
        else:  # vendedor
            perms = self.vendedor_permissions
        
        try:
            return json.loads(perms) if isinstance(perms, str) else perms
        except:
            # Default permissions if JSON is invalid
            return {"dashboard": False, "products": False, "sales": False, "debts": False, "reports": False, "users": False, "settings": False}


@app.before_request
def init_db_once():
    global _db_initialized
    if _db_initialized:
        return
    os.makedirs(app.instance_path, exist_ok=True)
    db.create_all()
    if not User.query.first():
        admin = User(
            username="admin",
            password_hash=generate_password_hash("admin123"),
            role="admin",
        )
        db.session.add(admin)
        db.session.commit()
    _db_initialized = True


@app.context_processor
def inject_user_permissions():
    """Inject user permissions into all templates"""
    user_id = session.get("user_id")
    user_role = session.get("role", "vendedor")
    
    # Default permissions by role
    default_permissions = {
        "admin": {
            "dashboard": True,
            "products": True,
            "sales": True,
            "debts": True,
            "reports": True,
            "users": True,
            "settings": True
        },
        "gerente": {
            "dashboard": True,
            "products": True,
            "sales": True,
            "debts": True,
            "reports": True,
            "users": False,
            "settings": False
        },
        "vendedor": {
            "dashboard": False,
            "products": True,
            "sales": True,
            "debts": False,
            "reports": False,
            "users": False,
            "settings": False
        }
    }
    
    permissions = default_permissions.get(user_role, default_permissions["vendedor"])
    
    if user_id:
        try:
            settings = get_user_settings(user_id)
            permissions = settings.get_role_permissions(user_role)
        except Exception as e:
            # Log error for debugging but use defaults
            print(f"Error getting user permissions: {e}")
    
    return {"user_permissions": permissions, "now": datetime.now}


@app.template_filter("money")
def format_money(cents):
    if cents is None:
        return "$0.00"
    return f"${cents / 100:.2f}"


def parse_price(value):
    if not value:
        return None
    clean = value.strip().replace(",", ".")
    try:
        amount = Decimal(clean)
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    cents = int((amount * 100).quantize(Decimal("1")))
    return cents


def get_user_settings(user_id):
    """Get or create user settings with defaults"""
    settings = Settings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = Settings(user_id=user_id, stock_yellow_threshold=10)
        db.session.add(settings)
        db.session.commit()
    return settings


def serialize_products(products):
    return [
        {
            "id": product.id,
            "name": product.name,
            "stock": product.stock,
        }
        for product in products
    ]


def get_customer_filter_from_key(customer_key):
    if customer_key == "__SIN_NOMBRE__":
        return "Sin nombre", (Sale.customer_name.is_(None)) | (Sale.customer_name == "")
    return customer_key, Sale.customer_name == customer_key


def _get_sqlite_db_path():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "", 1)
    return None


def _prune_backups():
    if not os.path.isdir(BACKUP_DIR):
        return
    backups = [
        os.path.join(BACKUP_DIR, name)
        for name in os.listdir(BACKUP_DIR)
        if name.startswith("app-") and name.endswith(".db")
    ]
    backups.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for old in backups[BACKUP_RETENTION:]:
        try:
            os.remove(old)
        except OSError:
            pass


def create_backup():
    db_path = _get_sqlite_db_path()
    if not db_path or not os.path.exists(db_path):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"app-{timestamp}.db")

    try:
        with sqlite3.connect(db_path) as src, sqlite3.connect(backup_path) as dst:
            src.backup(dst)
    except sqlite3.Error:
        return

    _prune_backups()


def _next_backup_delay():
    try:
        hour_str, minute_str = BACKUP_TIME.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError):
        hour, minute = 0, 0

    now = datetime.now()
    next_run = datetime.combine(now.date(), datetime.min.time()).replace(hour=hour, minute=minute)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


def start_backup_scheduler():
    def worker():
        while True:
            delay = _next_backup_delay()
            time.sleep(delay)
            create_backup()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def ensure_recent_backup():
    if not os.path.isdir(BACKUP_DIR):
        create_backup()
        return
    backups = [
        os.path.join(BACKUP_DIR, name)
        for name in os.listdir(BACKUP_DIR)
        if name.startswith("app-") and name.endswith(".db")
    ]
    if not backups:
        create_backup()
        return
    latest = max(backups, key=lambda p: os.path.getmtime(p))
    age_seconds = time.time() - os.path.getmtime(latest)
    if age_seconds >= 24 * 60 * 60:
        create_backup()


def get_home_page_for_user(user_id, role):
    """Get the appropriate home page based on user permissions"""
    settings = get_user_settings(user_id)
    permissions = settings.get_role_permissions(role)
    
    # Priority order for home page
    if permissions.get("dashboard", False):
        return "dashboard"
    elif permissions.get("sales", False):
        return "sales"
    elif permissions.get("products", False):
        return "products"
    elif permissions.get("debts", False):
        return "debts"
    elif permissions.get("reports", False):
        return "reports"
    else:
        return "logout"  # If no permissions, logout


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def require_permission(module):
    """Decorador para verificar permisos de acceso a módulos específicos"""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = session.get("user_id")
            role = session.get("role")
            
            if not user_id or not role:
                return redirect(url_for("login"))
            
            settings = get_user_settings(user_id)
            permissions = settings.get_role_permissions(role)
            
            if not permissions.get(module, False):
                flash("❌ No tienes permiso para acceder a esta sección", "error")
                # Redirect to user's home page instead of dashboard
                home_page = get_home_page_for_user(user_id, role)
                return redirect(url_for(home_page))
            
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role
            # Redirect to appropriate home page based on user permissions
            home_page = get_home_page_for_user(user.id, user.role)
            return redirect(url_for(home_page))
        flash("Credenciales invalidas", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
@require_permission("dashboard")
def dashboard():
    user_id = session.get("user_id")
    settings = get_user_settings(user_id)
    
    # Fechas para rangos (usar datetime.now para coincidir con la zona horaria local)
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    
    # KPIs del día
    sales_today = Sale.query.filter(
        Sale.user_id == user_id,
        Sale.created_at >= today_start,
        Sale.created_at < today_start + timedelta(days=1)
    ).all()
    total_today = sum((sale.total_cents or 0) for sale in sales_today)
    count_today = len(sales_today)
    
    # KPIs del mes
    sales_month = Sale.query.filter(
        Sale.user_id == user_id,
        Sale.created_at >= month_start
    ).all()
    total_month = sum((sale.total_cents or 0) for sale in sales_month)
    count_month = len(sales_month)
    
    # Deudas pendientes (solo ventas fiadas)
    pending_debts = Sale.query.filter(
        Sale.user_id == user_id,
        Sale.payment_method == "fiado",
        Sale.payment_status.in_(["pendiente", "parcial"])
    ).all()
    total_debt = sum((sale.pending_cents or 0) for sale in pending_debts)
    
    # Contar clientes únicos con deuda (igual que en la página de deudas)
    debts_by_customer = {}
    for sale in pending_debts:
        customer = sale.customer_name or "Sin nombre"
        if customer not in debts_by_customer:
            debts_by_customer[customer] = {'debt': 0}
        debts_by_customer[customer]['debt'] += sale.pending_cents
    
    count_debts = len(debts_by_customer)
    
    # Ventas recientes
    recent_sales = Sale.query.filter_by(user_id=user_id).options(
        db.joinedload(Sale.items)
    ).order_by(Sale.created_at.desc()).limit(5).all()
    
    # Stock bajo
    low_stock = Product.query.filter(
        Product.user_id == user_id,
        Product.stock < settings.stock_yellow_threshold
    ).order_by(Product.stock.asc()).limit(10).all()
    
    # Productos más vendidos (últimos 30 días)
    thirty_days_ago = now - timedelta(days=30)
    try:
        top_products_query = db.session.query(
            Product.name,
            db.func.sum(SaleItem.qty).label('total_sold')
        ).join(SaleItem, Product.id == SaleItem.product_id
        ).join(Sale, SaleItem.sale_id == Sale.id
        ).filter(
            Sale.user_id == user_id,
            Product.user_id == user_id,
            Sale.created_at >= thirty_days_ago
        ).group_by(Product.id, Product.name
        ).order_by(db.desc('total_sold')
        ).limit(5).all()
    except Exception as e:
        print(f"Error querying top products: {e}")
        top_products_query = []
    
    # Ventas por día (últimos 7 días)
    daily_sales = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        sales_day = Sale.query.filter(
            Sale.user_id == user_id,
            Sale.created_at >= day_start,
            Sale.created_at < day_end
        ).all()
        
        total = sum((sale.total_cents or 0) for sale in sales_day)
        daily_sales.append({
            'date': day.strftime('%d/%m'),
            'total': total / 100.0,
            'count': len(sales_day)
        })
    
    # Total de productos
    total_products = Product.query.filter_by(user_id=user_id).count()
    products = Product.query.filter_by(user_id=user_id).order_by(Product.name.asc()).all()
    products_data = serialize_products(products)
    
    response = make_response(render_template(
        "dashboard.html",
        recent_sales=recent_sales,
        low_stock=low_stock,
        total_today=total_today,
        count_today=count_today,
        total_month=total_month,
        count_month=count_month,
        total_debt=total_debt,
        count_debts=count_debts,
        top_products=top_products_query,
        daily_sales=daily_sales,
        total_products=total_products,
        products=products_data
    ))
    # Evita que el navegador reutilice una vista antigua del inicio.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/products")
@login_required
@require_permission("products")
def products():
    user_id = session.get("user_id")
    items = Product.query.filter_by(user_id=user_id).order_by(Product.name.asc()).limit(200).all()
    settings = get_user_settings(user_id)
    return render_template("products.html", products=items, settings=settings)


@app.route("/products/new", methods=["GET", "POST"])
@login_required
@require_permission("products")
def product_new():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _new_product_error(message):
        flash(message, "error")
        if is_ajax:
            return jsonify({"success": False, "message": message}), 400
        return render_template("product_form.html", product=None)
    
    if request.method == "POST":
        user_id = session.get("user_id")
        name = " ".join(request.form.get("name", "").split())
        sku = request.form.get("sku", "").strip() or None
        package_cost_cents = parse_price(request.form.get("package_cost"))
        package_qty = request.form.get("package_qty", "1").strip()
        price_cents = parse_price(request.form.get("price"))
        stock = request.form.get("stock", "0").strip()

        if not name:
            return _new_product_error("Nombre es requerido")
        if Product.query.filter(
            Product.user_id == user_id,
            db.func.lower(Product.name) == name.lower()
        ).first():
            return _new_product_error(f"El producto '{name}' ya existe. Usa un nombre diferente.")
        if sku and Product.query.filter_by(user_id=user_id, sku=sku).first():
            return _new_product_error(f"SKU '{sku}' ya existe. Usa uno diferente.")
        if package_cost_cents is None:
            return _new_product_error("Costo de paquete inválido")
        
        try:
            package_qty_val = int(package_qty)
            if package_qty_val <= 0:
                raise ValueError("Debe ser mayor a 0")
        except ValueError:
            return _new_product_error("Cantidad en paquete inválida")
        
        cost_cents = package_cost_cents // package_qty_val if package_qty_val > 0 else 0
        
        if price_cents is None:
            return _new_product_error("Precio inválido")
        try:
            stock_val = int(stock)
            if stock_val < 0:
                raise ValueError("Stock no puede ser negativo")
        except ValueError:
            return _new_product_error("Stock inválido")

        product = Product(user_id=user_id, name=name, sku=sku, package_cost_cents=package_cost_cents, package_quantity=package_qty_val, cost_cents=cost_cents, price_cents=price_cents, stock=stock_val)
        db.session.add(product)
        db.session.commit()
        flash("Producto creado", "success")
        
        if is_ajax:
            return jsonify({"success": True, "product_id": product.id}), 200
        return redirect(url_for("products"))

    return render_template("product_form.html", product=None, is_ajax=is_ajax)


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("products")
def product_edit(product_id):
    user_id = session.get("user_id")
    product = Product.query.filter_by(id=product_id, user_id=user_id).first_or_404()
    if request.method == "POST":
        name = " ".join(request.form.get("name", "").split())
        sku = request.form.get("sku", "").strip() or None
        package_cost_cents = parse_price(request.form.get("package_cost"))
        package_qty = request.form.get("package_qty", "1").strip()
        price_cents = parse_price(request.form.get("price"))
        stock = request.form.get("stock", "0").strip()

        if not name:
            flash("Nombre es requerido", "error")
            return render_template("product_form.html", product=product)
        if Product.query.filter(
            Product.user_id == user_id,
            Product.id != product_id,
            db.func.lower(Product.name) == name.lower()
        ).first():
            flash(f"El producto '{name}' ya existe. Usa un nombre diferente.", "error")
            return redirect(url_for("products"))
        if sku and Product.query.filter(Product.sku == sku, Product.id != product_id, Product.user_id == user_id).first():
            flash(f"SKU '{sku}' ya existe en otro producto. Usa uno diferente.", "error")
            return render_template("product_form.html", product=product)
        if package_cost_cents is None:
            flash("Costo de paquete inválido", "error")
            return render_template("product_form.html", product=product)
        
        try:
            package_qty_val = int(package_qty)
            if package_qty_val <= 0:
                raise ValueError("Debe ser mayor a 0")
        except ValueError:
            flash("Cantidad en paquete inválida", "error")
            return render_template("product_form.html", product=product)
        
        cost_cents = package_cost_cents // package_qty_val if package_qty_val > 0 else 0
        
        if price_cents is None:
            flash("Precio inválido", "error")
            return render_template("product_form.html", product=product)
        try:
            stock_val = int(stock)
            if stock_val < 0:
                raise ValueError("Stock no puede ser negativo")
        except ValueError:
            flash("Stock inválido", "error")
            return render_template("product_form.html", product=product)

        product.name = name
        product.sku = sku
        product.package_cost_cents = package_cost_cents
        product.package_quantity = package_qty_val
        product.cost_cents = cost_cents
        product.price_cents = price_cents
        product.stock = stock_val
        db.session.commit()
        flash("Producto actualizado", "success")
        return redirect(url_for("products"))

    return render_template("product_form.html", product=product)


@app.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
@require_permission("products")
def product_delete(product_id):
    user_id = session.get("user_id")
    product = Product.query.filter_by(id=product_id, user_id=user_id).first_or_404()
    has_sales = SaleItem.query.filter_by(product_id=product.id).first()
    if has_sales:
        flash("No se puede eliminar: el producto tiene ventas registradas", "error")
        return redirect(url_for("products"))

    try:
        db.session.delete(product)
        db.session.commit()
        flash("Producto eliminado", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Error al eliminar producto: {exc}", "error")

    return redirect(url_for("products"))


@app.route("/sales")
@login_required
@require_permission("sales")
def sales():
    user_id = session.get("user_id")
    search_q = request.args.get("q", "").strip()

    query = Sale.query.filter_by(user_id=user_id).options(
        db.joinedload(Sale.items).joinedload(SaleItem.product)
    )
    if search_q:
        search_lower = search_q.lower()
        anon_terms = {"anonimo", "sin nombre"}
        if search_lower in anon_terms:
            query = query.filter((Sale.customer_name.is_(None)) | (Sale.customer_name == ""))
        else:
            query = query.filter(Sale.customer_name.ilike(f"%{search_q}%"))

    items = (
        query.order_by(Sale.created_at.desc())
        .limit(100)
        .all()
    )
    sales_serializable = []
    for sale in items:
        sale_items = []
        for item in sale.items:
            product_name = item.product.name if item.product else "Producto eliminado"
            product_id = item.product.id if item.product else None
            sale_items.append({
                "product": {
                    "id": product_id,
                    "name": product_name,
                },
                "qty": item.qty,
                "unit_price_cents": item.unit_price_cents,
                "line_total_cents": item.line_total_cents,
            })
        sales_serializable.append({
            "id": sale.id,
            "created_at": sale.created_at.strftime("%d/%m/%Y %H:%M"),
            "created_at_date": sale.created_at.strftime("%d/%m/%Y"),
            "created_at_time": sale.created_at.strftime("%H:%M"),
            "customer_name": sale.customer_name or "Anónimo",
            "customer_key": sale.customer_name or "__SIN_NOMBRE__",
            "payment_method": sale.payment_method or "efectivo",
            "payment_status": sale.payment_status or "pagado",
            "total_cents": sale.total_cents,
            "paid_cents": sale.paid_cents,
            "pending_cents": sale.pending_cents,
            "items": sale_items,
        })

    sales_json = json.dumps(sales_serializable)
    products = Product.query.filter_by(user_id=user_id).order_by(Product.name.asc()).all()
    products_data = serialize_products(products)
    return render_template("sales.html", sales=sales_serializable, search_q=search_q, sales_json=sales_json, products=products_data)


@app.route("/sales/new", methods=["GET", "POST"])
@login_required
@require_permission("sales")
def sale_new():
    user_id = session.get("user_id")
    products = Product.query.filter_by(user_id=user_id).order_by(Product.name.asc()).all()
    products_data = serialize_products(products)
    line_items = []
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        payment_method = request.form.get("payment_method", "efectivo").strip()
        product_ids = request.form.getlist("product_id")
        qty_values = request.form.getlist("qty")

        # Obtener todos los productos en una sola query
        valid_ids = [int(pid) for pid in product_ids if pid]
        products_map = {p.id: p for p in Product.query.filter(Product.id.in_(valid_ids), Product.user_id == user_id).all()} if valid_ids else {}

        for product_id, qty_str in zip(product_ids, qty_values):
            if not product_id or not qty_str:
                continue
            try:
                qty = int(qty_str)
                pid = int(product_id)
            except (ValueError, TypeError):
                continue
            if qty <= 0 or pid not in products_map:
                continue
            product = products_map[pid]
            line_items.append({"product": product, "qty": qty})

        if not line_items:
            flash("Agrega al menos un producto", "error")
            if is_ajax:
                return render_template(
                    "sale_form.html", products=products_data, line_items=line_items, customer_name=customer_name, payment_method=payment_method, is_ajax=True
                ), 400
            return render_template(
                "sale_form.html", products=products_data, line_items=line_items, customer_name=customer_name, payment_method=payment_method
            )

        for item in line_items:
            if item["product"].stock < item["qty"]:
                flash(f"Stock insuficiente para {item['product'].name}", "error")
                if is_ajax:
                    return render_template(
                        "sale_form.html", products=products_data, line_items=line_items, customer_name=customer_name, payment_method=payment_method, is_ajax=True
                    ), 400
                return render_template(
                    "sale_form.html", products=products_data, line_items=line_items, customer_name=customer_name, payment_method=payment_method
                )

        # Determinar estado de pago según el método
        if payment_method == "fiado":
            payment_status = "pendiente"
            paid_cents = 0
        else:
            payment_status = "pagado"
            paid_cents = 0  # Se calculará después
        
        sale = Sale(
            user_id=user_id,
            customer_name=customer_name, 
            payment_method=payment_method,
            payment_status=payment_status,
            paid_cents=paid_cents
        )
        db.session.add(sale)

        total_cents = 0
        for item in line_items:
            product = item["product"]
            qty = item["qty"]
            line_total = product.price_cents * qty
            sale_item = SaleItem(
                sale=sale,
                product=product,
                qty=qty,
                unit_price_cents=product.price_cents,
                line_total_cents=line_total,
            )
            product.stock -= qty
            total_cents += line_total
            db.session.add(sale_item)

        sale.total_cents = total_cents
        # Si no es fiado, se considera pagado completamente
        if payment_method != "fiado":
            sale.paid_cents = total_cents
        db.session.commit()
        flash("Venta registrada", "success")
        
        if is_ajax:
            return jsonify({"success": True, "sale_id": sale.id}), 200
        return redirect(url_for("sales"))

    return render_template("sale_form.html", products=products_data, line_items=line_items, customer_name="", payment_method="efectivo", is_ajax=is_ajax)


@app.route("/sales/<int:sale_id>/delete", methods=["POST"])
@login_required
@require_permission("sales")
def sale_delete(sale_id):
    user_id = session.get("user_id")
    sale = Sale.query.filter_by(id=sale_id, user_id=user_id).first_or_404()
    
    try:
        # Devolver stock a los productos y eliminar items explícitamente
        for item in sale.items:
            product = None
            if item.product_id:
                product = Product.query.filter_by(id=item.product_id, user_id=user_id).first()
            if product:
                product.stock += item.qty
            db.session.delete(item)
        
        # Eliminar todos los pagos asociados
        for payment in sale.payments:
            db.session.delete(payment)
        
        # Ahora eliminar la venta
        db.session.delete(sale)
        db.session.commit()
        flash("Venta eliminada y stock devuelto", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al eliminar venta: {str(e)}", "error")
    
    return redirect(url_for("sales"))


@app.route("/sales/<int:sale_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("sales")
def sale_edit(sale_id):
    user_id = session.get("user_id")
    sale = Sale.query.filter_by(id=sale_id, user_id=user_id).first_or_404()
    products = Product.query.filter_by(user_id=user_id).order_by(Product.name.asc()).all()
    products_data = serialize_products(products)
    
    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        payment_method = request.form.get("payment_method", "efectivo").strip()
        product_ids = request.form.getlist("product_id")
        qty_values = request.form.getlist("qty")

        # Validar productos y cantidades
        valid_ids = [int(pid) for pid in product_ids if pid]
        products_map = {p.id: p for p in Product.query.filter(Product.id.in_(valid_ids), Product.user_id == user_id).all()} if valid_ids else {}

        line_items = []
        for product_id, qty_str in zip(product_ids, qty_values):
            if not product_id or not qty_str:
                continue
            try:
                qty = int(qty_str)
                pid = int(product_id)
            except (ValueError, TypeError):
                continue
            if qty <= 0 or pid not in products_map:
                continue
            product = products_map[pid]
            line_items.append({"product": product, "qty": qty})

        if not line_items:
            flash("Agrega al menos un producto", "error")
            return render_template(
                "sale_form.html", 
                sale=sale,
                products=products_data, 
                line_items=line_items, 
                customer_name=customer_name, 
                payment_method=payment_method
            )

        new_total_cents = sum(item["product"].price_cents * item["qty"] for item in line_items)
        payments_total = (
            db.session.query(db.func.coalesce(db.func.sum(Payment.amount_cents), 0))
            .filter(Payment.sale_id == sale.id)
            .scalar()
        )
        if payment_method == "fiado" and payments_total > new_total_cents:
            flash("No puedes reducir el total por debajo de lo ya pagado", "error")
            return render_template(
                "sale_form.html",
                sale=sale,
                products=products_data,
                line_items=line_items,
                customer_name=customer_name,
                payment_method=payment_method
            )

        # Devolver stock de los productos originales
        for item in sale.items:
            item.product.stock += item.qty

        # Validar stock disponible para los nuevos productos
        for item in line_items:
            if item["product"].stock < item["qty"]:
                # Si falla, restaurar el stock original antes de mostrar el error
                for original_item in sale.items:
                    original_item.product.stock -= original_item.qty
                flash(f"Stock insuficiente para {item['product'].name}", "error")
                return render_template(
                    "sale_form.html",
                    sale=sale,
                    products=products_data,
                    line_items=line_items,
                    customer_name=customer_name,
                    payment_method=payment_method
                )

        # Eliminar los items antiguos
        for item in sale.items:
            db.session.delete(item)
        
        # Actualizar información de la venta
        sale.customer_name = customer_name
        sale.payment_method = payment_method
        
        # Ajustar estado de pago según el método
        # Si cambia de fiado a otro método, marcar como pagado
        if payment_method != "fiado" and sale.payment_status in ["pendiente", "parcial"]:
            sale.payment_status = "pagado"
            # El total pagado será actualizado después de calcular el nuevo total
        elif payment_method == "fiado" and sale.paid_cents == 0:
            sale.payment_status = "pendiente"
        
        # Crear nuevos items y calcular total
        total_cents = 0
        for item in line_items:
            product = item["product"]
            qty = item["qty"]
            line_total = product.price_cents * qty
            sale_item = SaleItem(
                sale=sale,
                product=product,
                qty=qty,
                unit_price_cents=product.price_cents,
                line_total_cents=line_total,
            )
            product.stock -= qty
            total_cents += line_total
            db.session.add(sale_item)

        sale.total_cents = total_cents
        
        # Ajustar paid_cents según el nuevo total y método de pago
        if payment_method != "fiado":
            sale.paid_cents = total_cents
            sale.payment_status = "pagado"
        else:
            sale.paid_cents = payments_total
            if sale.paid_cents == 0:
                sale.payment_status = "pendiente"
            elif sale.paid_cents >= total_cents:
                sale.payment_status = "pagado"
            else:
                sale.payment_status = "parcial"
        
        db.session.commit()
        flash("Venta actualizada correctamente", "success")
        return redirect(url_for("sales"))

    # GET: Mostrar formulario con datos existentes
    line_items = [{"product": item.product, "qty": item.qty} for item in sale.items]
    return render_template(
        "sale_form.html",
        sale=sale,
        products=products_data,
        line_items=line_items,
        customer_name=sale.customer_name or "",
        payment_method=sale.payment_method
    )


@app.route("/debts")
@login_required
@require_permission("debts")
def debts():
    user_id = session.get("user_id")
    # Obtener todas las ventas con deuda pendiente del usuario actual
    pending_sales = (
        Sale.query.filter(
            Sale.user_id == user_id,
            Sale.payment_method == "fiado",
            Sale.payment_status.in_(["pendiente", "parcial"])
        )
        .options(
            db.joinedload(Sale.items).joinedload(SaleItem.product),
            db.joinedload(Sale.payments)
        )
        .order_by(Sale.created_at.desc())
        .all()
    )
    
    # Agrupar las ventas por cliente (deuda pendiente)
    debts_by_customer = {}
    for sale in pending_sales:
        customer = sale.customer_name or "Sin nombre"
        if customer not in debts_by_customer:
            customer_key = customer if customer != "Sin nombre" else "__SIN_NOMBRE__"
            debts_by_customer[customer] = {
                'customer_name': customer,
                'customer_key': customer_key,
                'total_original_cents': 0,
                'total_paid_cents': 0,
                'total_debt_cents': 0,
                'sales': [],
                'items_map': {}
            }
        debts_by_customer[customer]['total_debt_cents'] += sale.pending_cents
        debts_by_customer[customer]['sales'].append(sale)

    for sale in pending_sales:
        customer = sale.customer_name or "Sin nombre"
        customer_data = debts_by_customer.get(customer)
        if not customer_data:
            continue
        customer_data['total_original_cents'] += sale.total_cents
        customer_data['total_paid_cents'] += sale.paid_cents

        items_map = customer_data['items_map']
        for item in sale.items:
            product_name = item.product.name if item.product else "Producto eliminado"
            key = item.product_id
            if key not in items_map:
                items_map[key] = {
                    'product_name': product_name,
                    'qty': 0,
                    'line_total_cents': 0
                }
            items_map[key]['qty'] += item.qty
            items_map[key]['line_total_cents'] += item.line_total_cents
    
    # Convertir a lista y ordenar por nombre (A-Z)
    for customer_data in debts_by_customer.values():
        items_list = sorted(
            customer_data['items_map'].values(),
            key=lambda x: x['product_name'].lower()
        )
        customer_data['items_list'] = items_list
        customer_data.pop('items_map', None)

    grouped_debts = sorted(debts_by_customer.values(), key=lambda x: x['customer_name'].lower())
    
    total_debt_cents = sum(sale.pending_cents for sale in pending_sales)
    
    # Crear JSON serializable para el resumen
    debts_summary_data = {
        "total_debt_cents": total_debt_cents,
        "customers": [
            {
                "customer_name": c["customer_name"],
                "total_original_cents": c["total_original_cents"],
                "total_paid_cents": c["total_paid_cents"],
                "total_debt_cents": c["total_debt_cents"],
                "items_list": c["items_list"]
            }
            for c in grouped_debts
        ]
    }
    debts_summary_json = json.dumps(debts_summary_data)
    
    # Crear versión serializable de grouped_debts
    grouped_debts_serializable = [
        {
            "customer_name": c["customer_name"],
            "customer_key": c["customer_key"],
            "total_original_cents": c["total_original_cents"],
            "total_paid_cents": c["total_paid_cents"],
            "total_debt_cents": c["total_debt_cents"],
            "items_list": c["items_list"],
            "latest_sale_id": c["sales"][0].id if c.get("sales") else None,
            "sales_summary": [
                {
                    "id": sale.id,
                    "created_at": sale.created_at.strftime("%d/%m/%Y %H:%M"),
                    "total_cents": sale.total_cents,
                    "paid_cents": sale.paid_cents,
                    "pending_cents": sale.pending_cents,
                    "payment_status": sale.payment_status,
                }
                for sale in sorted(c.get("sales", []), key=lambda s: s.created_at, reverse=True)
            ]
        }
        for c in grouped_debts
    ]
    grouped_debts_json = json.dumps(grouped_debts_serializable)
    
    return render_template("debts.html", 
                         grouped_debts=grouped_debts, 
                         total_debt_cents=total_debt_cents, 
                         debts_summary_json=debts_summary_json, 
                         grouped_debts_json=grouped_debts_json)


@app.route("/debts/customer/payment", methods=["GET", "POST"])
@login_required
@require_permission("debts")
def customer_payment_register():
    user_id = session.get("user_id")
    customer_key = request.args.get("customer", "").strip()
    if not customer_key:
        flash("Cliente inválido", "error")
        return redirect(url_for("debts"))

    customer_name, customer_filter = get_customer_filter_from_key(customer_key)

    pending_sales = (
        Sale.query.filter(
            Sale.user_id == user_id,
            customer_filter,
            Sale.payment_method == "fiado",
            Sale.payment_status.in_(["pendiente", "parcial"])
        )
        .options(
            db.joinedload(Sale.items).joinedload(SaleItem.product)
        )
        .order_by(Sale.created_at.asc())
        .all()
    )

    if not pending_sales:
        flash("No hay deudas pendientes para este cliente", "error")
        return redirect(url_for("debts"))

    items_map = {}
    total_pending_cents = 0
    for sale in pending_sales:
        total_pending_cents += sale.pending_cents
    for sale in pending_sales:
        for item in sale.items:
            product_name = item.product.name if item.product else "Producto eliminado"
            key = item.product_id
            if key not in items_map:
                items_map[key] = {
                    'product_name': product_name,
                    'qty': 0,
                    'line_total_cents': 0
                }
            items_map[key]['qty'] += item.qty
            items_map[key]['line_total_cents'] += item.line_total_cents

    items_list = sorted(items_map.values(), key=lambda x: x['product_name'].lower())

    if request.method == "POST":
        amount_str = request.form.get("amount", "").strip()
        payment_method = request.form.get("payment_method", "efectivo").strip()
        notes = request.form.get("notes", "").strip()

        amount_cents = parse_price(amount_str)
        if amount_cents is None or amount_cents <= 0:
            flash("Ingresa un monto válido", "error")
            return render_template(
                "customer_payment_form.html",
                customer_name=customer_name,
                customer_key=customer_key,
                items=items_list,
                total_pending_cents=total_pending_cents,
                pending_sales=pending_sales,
            )

        if amount_cents > total_pending_cents:
            flash(f"El monto excede la deuda pendiente de {total_pending_cents/100:.2f}", "error")
            return render_template(
                "customer_payment_form.html",
                customer_name=customer_name,
                customer_key=customer_key,
                items=items_list,
                total_pending_cents=total_pending_cents,
                pending_sales=pending_sales,
            )

        remaining = amount_cents
        for sale in pending_sales:
            if remaining <= 0:
                break
            pending_cents = sale.pending_cents
            if pending_cents <= 0:
                continue
            apply_cents = pending_cents if remaining >= pending_cents else remaining

            payment = Payment(
                sale=sale,
                amount_cents=apply_cents,
                payment_method=payment_method,
                notes=notes
            )
            db.session.add(payment)

            sale.paid_cents += apply_cents
            if sale.paid_cents >= sale.total_cents:
                sale.payment_status = "pagado"
            else:
                sale.payment_status = "parcial"

            remaining -= apply_cents

        db.session.commit()
        flash(f"Pago de {amount_cents/100:.2f} registrado exitosamente", "success")
        return redirect(url_for("debts"))

    return render_template(
        "customer_payment_form.html",
        customer_name=customer_name,
        customer_key=customer_key,
        items=items_list,
        total_pending_cents=total_pending_cents,
        pending_sales=pending_sales,
    )


@app.route("/debts/customer/receipt")
@login_required
@require_permission("debts")
def debt_customer_receipt():
    user_id = session.get("user_id")
    customer_key = request.args.get("customer", "").strip()
    if not customer_key:
        flash("Cliente inválido", "error")
        return redirect(url_for("debts"))

    customer_name, customer_filter = get_customer_filter_from_key(customer_key)

    pending_sales = (
        Sale.query.filter(
            Sale.user_id == user_id,
            customer_filter,
            Sale.payment_method == "fiado",
            Sale.payment_status.in_(["pendiente", "parcial"])
        )
        .options(
            db.joinedload(Sale.items).joinedload(SaleItem.product),
            db.joinedload(Sale.payments)
        )
        .order_by(Sale.created_at.asc())
        .all()
    )

    if not pending_sales:
        flash("No hay deudas pendientes para este cliente", "error")
        return redirect(url_for("debts"))

    items_map = {}
    payments_history = []
    total_original_cents = 0
    total_paid_cents = 0
    total_pending_cents = 0

    for sale in pending_sales:
        total_original_cents += sale.total_cents
        total_paid_cents += sale.paid_cents
        total_pending_cents += sale.pending_cents

        for item in sale.items:
            product_name = item.product.name if item.product else "Producto eliminado"
            key = item.product_id
            if key not in items_map:
                items_map[key] = {
                    "product_name": product_name,
                    "qty": 0,
                    "line_total_cents": 0
                }
            items_map[key]["qty"] += item.qty
            items_map[key]["line_total_cents"] += item.line_total_cents

        for payment in sale.payments:
            payments_history.append({
                "sale_id": sale.id,
                "amount_cents": payment.amount_cents,
                "payment_method": payment.payment_method,
                "notes": payment.notes or "",
                "created_at": payment.created_at,
            })

    items_list = sorted(items_map.values(), key=lambda x: x["product_name"].lower())
    payments_history.sort(key=lambda x: x["created_at"], reverse=True)

    generated_at = datetime.now()
    receipt_number = f"BOL-{generated_at.strftime('%Y%m%d%H%M')}-{pending_sales[-1].id:05d}"

    return render_template(
        "debt_receipt.html",
        customer_name=customer_name,
        customer_key=customer_key,
        generated_at=generated_at,
        receipt_number=receipt_number,
        total_original_cents=total_original_cents,
        total_paid_cents=total_paid_cents,
        total_pending_cents=total_pending_cents,
        items_list=items_list,
        pending_sales=sorted(pending_sales, key=lambda s: s.created_at, reverse=True),
        payments_history=payments_history,
    )


@app.route("/debts/<int:sale_id>/payment", methods=["GET", "POST"])
@login_required
@require_permission("debts")
def payment_register(sale_id):
    user_id = session.get("user_id")
    sale = Sale.query.filter_by(id=sale_id, user_id=user_id).first_or_404()
    
    if sale.payment_status == "pagado":
        flash("Esta venta ya está completamente pagada", "error")
        return redirect(url_for("debts"))
    
    if request.method == "POST":
        amount_str = request.form.get("amount", "").strip()
        payment_method = request.form.get("payment_method", "efectivo").strip()
        notes = request.form.get("notes", "").strip()
        
        amount_cents = parse_price(amount_str)
        if amount_cents is None or amount_cents <= 0:
            flash("Ingresa un monto válido", "error")
            return render_template("payment_form.html", sale=sale)
        
        pending_cents = sale.pending_cents
        
        if amount_cents > pending_cents:
            flash(f"El monto excede la deuda pendiente de {pending_cents/100:.2f}", "error")
            return render_template("payment_form.html", sale=sale)
        
        # Registrar el pago
        payment = Payment(
            sale=sale,
            amount_cents=amount_cents,
            payment_method=payment_method,
            notes=notes
        )
        db.session.add(payment)
        
        # Actualizar el total pagado
        sale.paid_cents += amount_cents
        
        # Actualizar el estado
        if sale.paid_cents >= sale.total_cents:
            sale.payment_status = "pagado"
        else:
            sale.payment_status = "parcial"
        
        db.session.commit()
        flash(f"Pago de {amount_cents/100:.2f} registrado exitosamente", "success")
        return redirect(url_for("debts"))
    
    return render_template("payment_form.html", sale=sale)


@app.route("/reports")
@login_required
@require_permission("reports")
def reports():
    user_id = session.get("user_id")
    today = datetime.now()
    today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    # Ventas hoy
    total_sales_today = (
        db.session.query(db.func.coalesce(db.func.sum(Sale.total_cents), 0))
        .filter(Sale.user_id == user_id, Sale.created_at >= today_start, Sale.created_at < today_end)
        .scalar()
    )
    total_transactions_today = (
        db.session.query(db.func.count(Sale.id))
        .filter(Sale.user_id == user_id, Sale.created_at >= today_start, Sale.created_at < today_end)
        .scalar()
    )

    # Ventas esta semana (últimos 7 días)
    week_start = today_start - timedelta(days=7)
    total_sales_week = (
        db.session.query(db.func.coalesce(db.func.sum(Sale.total_cents), 0))
        .filter(Sale.user_id == user_id, Sale.created_at >= week_start, Sale.created_at < today_end)
        .scalar()
    )
    
    # Ventas este mes
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total_sales_month = (
        db.session.query(db.func.coalesce(db.func.sum(Sale.total_cents), 0))
        .filter(Sale.user_id == user_id, Sale.created_at >= month_start, Sale.created_at < today_end)
        .scalar()
    )

    # Dinero invertido en bruto
    total_invested = (
        db.session.query(db.func.coalesce(db.func.sum(Product.cost_cents * Product.stock), 0))
        .filter(Product.user_id == user_id)
        .scalar()
    )

    # Top 10 productos más vendidos (todos los tiempos)
    top_products = (
        db.session.query(Product.name, db.func.sum(SaleItem.qty).label("qty"))
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Product.user_id == user_id)
        .group_by(Product.id, Product.name)
        .order_by(db.desc("qty"))
        .limit(10)
        .all()
    )

    # Productos con bajo stock (menos de 10 unidades)
    low_stock_products = (
        db.session.query(Product.name, Product.stock, Product.cost_cents)
        .filter(Product.user_id == user_id, Product.stock < 10)
        .order_by(Product.stock.asc())
        .limit(10)
        .all()
    )

    # Ventas por método de pago (últimos 30 días)
    thirty_days_ago = today_start - timedelta(days=30)
    payment_methods = (
        db.session.query(Sale.payment_method, db.func.count(Sale.id).label("count"), db.func.sum(Sale.total_cents).label("total"))
        .filter(Sale.user_id == user_id, Sale.created_at >= thirty_days_ago)
        .group_by(Sale.payment_method)
        .all()
    )

    # Últimas 20 ventas
    recent_sales = (
        db.session.query(Sale)
        .filter(Sale.user_id == user_id)
        .order_by(Sale.created_at.desc())
        .limit(20)
        .all()
    )

    # Calcular ingresos, costo de ventas y ganancia bruta del dia.
    today_sales_summary = (
        db.session.query(
            db.func.coalesce(db.func.sum(Sale.total_cents), 0),
            db.func.coalesce(db.func.sum(SaleItem.qty * Product.cost_cents), 0)
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(Sale.user_id == user_id, Sale.created_at >= today_start, Sale.created_at < today_end)
        .first()
    )
    today_cost = today_sales_summary[1] if today_sales_summary[1] else 0
    today_gross_profit = total_sales_today - today_cost

    return render_template(
        "reports.html",
        total_sales_today=total_sales_today,
        total_transactions_today=total_transactions_today,
        total_sales_week=total_sales_week,
        total_sales_month=total_sales_month,
        top_products=top_products,
        low_stock_products=low_stock_products,
        total_invested=total_invested,
        payment_methods=payment_methods,
        recent_sales=recent_sales,
        today_cost=today_cost,
        today_gross_profit=today_gross_profit,
    )


@app.route("/reports/debts-matrix")
@login_required
@require_permission("reports")
def reports_debts_matrix():
    debts = (
        db.session.query(
            db.func.coalesce(Sale.customer_name, "").label("customer_name"),
            User.username.label("username"),
            db.func.sum(Sale.total_cents - Sale.paid_cents).label("debt_cents"),
        )
        .join(User, User.id == Sale.user_id)
        .filter((Sale.total_cents - Sale.paid_cents) > 0)
        .group_by(db.func.coalesce(Sale.customer_name, ""), User.username)
        .order_by(User.username.asc(), db.func.coalesce(Sale.customer_name, "").asc())
        .all()
    )

    customer_debts = defaultdict(lambda: defaultdict(int))
    users_with_debt = set()

    for debt in debts:
        customer_name = (debt.customer_name or "").strip() or "Sin nombre"
        debt_cents = int(debt.debt_cents or 0)
        customer_debts[customer_name][debt.username] += debt_cents
        users_with_debt.add(debt.username)

    users = sorted(users_with_debt)
    rows = []
    total_debt_cents = 0
    debt_by_user = {username: 0 for username in users}

    for customer_name in sorted(customer_debts.keys()):
        per_user = dict(customer_debts[customer_name])
        customer_total = sum(per_user.values())
        rows.append(
            {
                "customer_name": customer_name,
                "debts_by_user": per_user,
                "total_debt_cents": customer_total,
            }
        )
        total_debt_cents += customer_total
        for username, debt_cents in per_user.items():
            debt_by_user[username] = debt_by_user.get(username, 0) + debt_cents

    top_customers = sorted(rows, key=lambda r: r["total_debt_cents"], reverse=True)[:10]
    top_users = sorted(debt_by_user.items(), key=lambda item: item[1], reverse=True)

    return render_template(
        "debts_matrix_report.html",
        users=users,
        rows=rows,
        total_debt_cents=total_debt_cents,
        total_customers=len(rows),
        total_users=len(users),
        debt_by_user=debt_by_user,
        top_customers=top_customers,
        top_users=top_users,
    )



@app.route("/users")
@login_required
@require_permission("users")
def users():
    users_list = User.query.order_by(User.username.asc()).all()
    return render_template("users.html", users=users_list)


@app.route("/users/new", methods=["GET", "POST"])
@login_required
@require_permission("users")
def user_new():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "admin").strip()

        if not username or len(username) < 3:
            flash("Usuario debe tener al menos 3 caracteres", "error")
            return render_template("user_form.html", user=None)
        if not password or len(password) < 6:
            flash("Contraseña debe tener al menos 6 caracteres", "error")
            return render_template("user_form.html", user=None)
        
        if User.query.filter_by(username=username).first():
            flash(f"👤 Usuario '{username}' ya existe. Elige otro.", "error")
            return render_template("user_form.html", user=None)

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            is_active=True
        )
        db.session.add(user)
        db.session.commit()
        flash(f"Usuario '{username}' creado exitosamente", "success")
        return redirect(url_for("users"))

    return render_template("user_form.html", user=None)


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("users")
def user_edit(user_id):
    user = User.query.get_or_404(user_id)
    is_protected_user = user.username == PROTECTED_USERNAME
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        role = request.form.get("role", "admin").strip()
        is_active = request.form.get("is_active") == "on"

        # Validar clave secreta si es usuario protegido y hay cambios críticos
        if is_protected_user:
            secret_key = request.form.get("secret_key", "").strip()
            if secret_key != PROTECTED_USER_SECRET:
                flash("⚠️ Necesitas la clave de acceso para modificar este usuario", "error")
                if is_ajax:
                    return render_template("user_form.html", user=user, is_protected=True, is_ajax=True), 400
                return render_template("user_form.html", user=user, is_protected=True)

        if not username or len(username) < 3:
            flash("Usuario debe tener al menos 3 caracteres", "error")
            if is_ajax:
                return render_template("user_form.html", user=user, is_protected=is_protected_user, is_ajax=True), 400
            return render_template("user_form.html", user=user, is_protected=is_protected_user)

        # Verificar si el nuevo username ya existe en otro usuario
        existing = User.query.filter_by(username=username).first()
        if existing and existing.id != user.id:
            flash(f"👤 Usuario '{username}' ya existe en otro perfil. Elige otro.", "error")
            if is_ajax:
                return render_template("user_form.html", user=user, is_protected=is_protected_user, is_ajax=True), 400
            return render_template("user_form.html", user=user, is_protected=is_protected_user)

        # No permitir cambiar username del usuario protegido
        if is_protected_user and username != PROTECTED_USERNAME:
            flash("⚠️ No se puede cambiar el nombre de este usuario protegido", "error")
            if is_ajax:
                return render_template("user_form.html", user=user, is_protected=True, is_ajax=True), 400
            return render_template("user_form.html", user=user, is_protected=True)

        user.username = username
        user.role = role
        user.is_active = is_active
        db.session.commit()
        flash("Usuario actualizado", "success")
        
        if is_ajax:
            return jsonify({"success": True}), 200
        return redirect(url_for("users"))

    return render_template("user_form.html", user=user, is_protected=is_protected_user, is_ajax=is_ajax)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@require_permission("users")
def user_delete(user_id):
    user = User.query.get_or_404(user_id)
    
    # Verificar si es el usuario protegido
    if user.username == PROTECTED_USERNAME:
        secret_key = request.form.get("secret_key", "").strip()
        if secret_key != PROTECTED_USER_SECRET:
            flash("⚠️ No puedes eliminar este usuario sin la clave de acceso correcta", "error")
            return redirect(url_for("users"))
    
    if user.id == session.get("user_id"):
        flash("No puedes eliminar tu propia cuenta", "error")
        return redirect(url_for("users"))

    username = user.username
    
    try:
        # Eliminar primero todos los datos relacionados con el usuario
        # 1. Eliminar SaleItems asociados a las ventas del usuario
        sale_ids = [sale.id for sale in Sale.query.filter_by(user_id=user_id).all()]
        if sale_ids:
            SaleItem.query.filter(SaleItem.sale_id.in_(sale_ids)).delete(synchronize_session=False)
        
        # 2. Eliminar todas las ventas del usuario
        Sale.query.filter_by(user_id=user_id).delete()
        
        # 3. Eliminar todos los productos del usuario
        Product.query.filter_by(user_id=user_id).delete()
        
        # 4. Eliminar settings del usuario
        Settings.query.filter_by(user_id=user_id).delete()
        
        # 5. Finalmente eliminar el usuario
        db.session.delete(user)
        db.session.commit()
        
        flash(f"Usuario '{username}' y todos sus datos eliminados correctamente", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al eliminar usuario: {str(e)}", "error")
    
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/password", methods=["GET", "POST"])
@login_required
@require_permission("users")
def user_change_password(user_id):
    user = User.query.get_or_404(user_id)
    is_protected_user = user.username == PROTECTED_USERNAME
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    # Determinar si es el mismo usuario
    current_user_id = session.get("user_id")
    is_self = (user.id == current_user_id)
    
    # Solo admin o el mismo usuario pueden cambiar contraseña
    if not is_self and session.get("role") != "admin":
        flash("No tienes permiso para cambiar esta contraseña", "error")
        if is_ajax:
            return jsonify({"error": "No tienes permiso"}), 403
        return redirect(url_for("users"))
    
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        # Si es usuario protegido, SIEMPRE requerir clave secreta (incluso si es él mismo)
        if is_protected_user:
            secret_key = request.form.get("secret_key", "").strip()
            if secret_key != PROTECTED_USER_SECRET:
                flash("⚠️ Necesitas la clave de acceso para cambiar la contraseña de este usuario protegido", "error")
                if is_ajax:
                    return render_template("user_password.html", user=user, is_protected=True, is_self=is_self, is_ajax=True), 400
                return render_template("user_password.html", user=user, is_protected=True, is_self=is_self)

        # Verificar contraseña antigua solo si el usuario intenta cambiar su propia contraseña
        if is_self:
            if not old_password:
                flash("Debes ingresar tu contraseña actual", "error")
                if is_ajax:
                    return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=True, is_ajax=True), 400
                return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=True)
            if not user.check_password(old_password):
                flash("Contraseña actual incorrecta", "error")
                if is_ajax:
                    return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=True, is_ajax=True), 400
                return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=True)

        if not new_password or len(new_password) < 6:
            flash("Nueva contraseña debe tener al menos 6 caracteres", "error")
            if is_ajax:
                return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=is_self, is_ajax=True), 400
            return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=is_self)

        if new_password != confirm_password:
            flash("Las contraseñas no coinciden", "error")
            if is_ajax:
                return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=is_self, is_ajax=True), 400
            return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=is_self)

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash("Contraseña actualizada", "success")
        
        if is_ajax:
            return jsonify({"success": True}), 200
        return redirect(url_for("users"))
    
    # Método GET: mostrar el formulario
    return render_template("user_password.html", user=user, is_protected=is_protected_user, is_self=is_self, is_ajax=is_ajax)


@app.route("/settings", methods=["GET", "POST"])
@login_required
@require_permission("settings")
def settings():
    user_id = session.get("user_id")
    user_role = session.get("role", "vendedor")
    if not user_id:
        return redirect(url_for("login"))
    
    # Obtener el usuario actual para verificar si es admin
    current_user = User.query.get(user_id)
    
    # Determinar qué usuario se va a editar
    edit_user_id = user_id
    if current_user and current_user.role == "admin":
        # Si es admin, puede seleccionar otro usuario
        selected_user_id = request.args.get("user_id", type=int)
        if selected_user_id:
            selected_user = User.query.get(selected_user_id)
            if selected_user:
                edit_user_id = selected_user_id
    
    edit_user = User.query.get(edit_user_id)
    if not edit_user:
        flash("Usuario no encontrado", "error")
        return redirect(url_for("settings"))
    
    settings_obj = get_user_settings(edit_user_id)
    all_users = []
    if current_user and current_user.role == "admin":
        all_users = User.query.all()
    
    if request.method == "POST":
        try:
            threshold = int(request.form.get("stock_yellow_threshold", "10"))
            if threshold < 1:
                flash("El threshold debe ser mayor a 0", "error")
            else:
                settings_obj.stock_yellow_threshold = threshold
            
            # Procesar permisos por rol
            modules = ["dashboard", "products", "sales", "debts", "reports", "users", "settings"]
            
            # Determinar qué roles puede modificar el usuario actual
            if current_user.role == "admin":
                # Admin puede modificar todos los roles
                roles_to_update = ["admin", "gerente", "vendedor"]
            else:
                # Otros roles solo pueden modificar su propio rol
                roles_to_update = [current_user.role]
            
            for role in roles_to_update:
                perms = {}
                for module in modules:
                    checkbox_name = f"{role}_{module}"
                    perms[module] = checkbox_name in request.form
                
                if role == "admin":
                    settings_obj.admin_permissions = json.dumps(perms)
                elif role == "gerente":
                    settings_obj.gerente_permissions = json.dumps(perms)
                else:  # vendedor
                    settings_obj.vendedor_permissions = json.dumps(perms)
            
            db.session.commit()
            flash("Ajustes actualizado correctamente", "success")
            # Recargar los datos actualizados
            settings_obj = get_user_settings(edit_user_id)
        except (ValueError, Exception) as e:
            flash(f"Error al guardar: {str(e)}", "error")
    
    # Preparar datos de permisos para el template
    permissions_data = {
        "admin": settings_obj.get_role_permissions("admin"),
        "gerente": settings_obj.get_role_permissions("gerente"),
        "vendedor": settings_obj.get_role_permissions("vendedor")
    }
    
    return render_template("settings.html", 
                         settings=settings_obj, 
                         edit_user=edit_user,
                         current_user=current_user,
                         all_users=all_users,
                         permissions=permissions_data)


if __name__ == "__main__":
    ensure_recent_backup()
    start_backup_scheduler()
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True, use_reloader=False)
