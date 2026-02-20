import os
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
Compress(app)
app.config["SECRET_KEY"] = "change-me-in-production"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["COMPRESS_LEVEL"] = 6
app.config["COMPRESS_MIN_SIZE"] = 500

instance_db_path = os.path.join(app.instance_path, "app.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{instance_db_path}"


db = SQLAlchemy(app)
migrate = Migrate(app, db)
_db_initialized = False


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
    name = db.Column(db.String(160), nullable=False, index=True)
    sku = db.Column(db.String(64), nullable=True, index=True)
    package_cost_cents = db.Column(db.Integer, nullable=False, default=0)
    package_quantity = db.Column(db.Integer, nullable=False, default=1)
    cost_cents = db.Column(db.Integer, nullable=False, default=0)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0, index=True)


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    customer_name = db.Column(db.String(160))
    payment_method = db.Column(db.String(20), nullable=False, default="efectivo")  # efectivo, yape, fiado
    total_cents = db.Column(db.Integer, nullable=False, default=0)
    paid_cents = db.Column(db.Integer, nullable=False, default=0)
    payment_status = db.Column(db.String(20), nullable=False, default="pagado")  # pagado, pendiente, parcial
    
    @property
    def pending_cents(self):
        return self.total_cents - self.paid_cents


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
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.String(255))
    
    sale = db.relationship("Sale", backref=db.backref("payments", lazy=True, cascade="all, delete-orphan"))


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


@app.template_filter("money")
def format_money(cents):
    if cents is None:
        return "0.00"
    return f"{cents / 100:.2f}"


def parse_price(value):
    if not value:
        return None
    clean = value.strip().replace(",", ".")
    try:
        amount = Decimal(clean)
    except InvalidOperation:
        return None
    cents = int((amount * 100).quantize(Decimal("1")))
    return cents


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


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
            return redirect(url_for("dashboard"))
        flash("Credenciales invalidas", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    recent_sales = Sale.query.options(db.joinedload(Sale.items)).order_by(Sale.created_at.desc()).limit(5).all()
    low_stock = Product.query.filter(Product.stock <= 5).order_by(Product.stock.asc()).limit(10).all()
    return render_template("dashboard.html", recent_sales=recent_sales, low_stock=low_stock)


@app.route("/products")
@login_required
def products():
    items = Product.query.order_by(Product.name.asc()).limit(200).all()
    return render_template("products.html", products=items)


@app.route("/products/new", methods=["GET", "POST"])
@login_required
def product_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        sku = request.form.get("sku", "").strip() or None
        package_cost_cents = parse_price(request.form.get("package_cost"))
        package_qty = request.form.get("package_qty", "1").strip()
        price_cents = parse_price(request.form.get("price"))
        stock = request.form.get("stock", "0").strip()

        if not name:
            flash("Nombre es requerido", "error")
            return render_template("product_form.html", product=None)
        if sku and Product.query.filter_by(sku=sku).first():
            flash(f"SKU '{sku}' ya existe. Usa uno diferente.", "error")
            return render_template("product_form.html", product=None)
        if package_cost_cents is None:
            flash("Costo de paquete inválido", "error")
            return render_template("product_form.html", product=None)
        
        try:
            package_qty_val = int(package_qty)
            if package_qty_val <= 0:
                raise ValueError("Debe ser mayor a 0")
        except ValueError:
            flash("Cantidad en paquete inválida", "error")
            return render_template("product_form.html", product=None)
        
        cost_cents = package_cost_cents // package_qty_val if package_qty_val > 0 else 0
        
        if price_cents is None:
            flash("Precio inválido", "error")
            return render_template("product_form.html", product=None)
        try:
            stock_val = int(stock)
            if stock_val < 0:
                raise ValueError("Stock no puede ser negativo")
        except ValueError:
            flash("Stock inválido", "error")
            return render_template("product_form.html", product=None)

        product = Product(name=name, sku=sku, package_cost_cents=package_cost_cents, package_quantity=package_qty_val, cost_cents=cost_cents, price_cents=price_cents, stock=stock_val)
        db.session.add(product)
        db.session.commit()
        flash("Producto creado", "success")
        return redirect(url_for("products"))

    return render_template("product_form.html", product=None)


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        sku = request.form.get("sku", "").strip() or None
        package_cost_cents = parse_price(request.form.get("package_cost"))
        package_qty = request.form.get("package_qty", "1").strip()
        price_cents = parse_price(request.form.get("price"))
        stock = request.form.get("stock", "0").strip()

        if not name:
            flash("Nombre es requerido", "error")
            return render_template("product_form.html", product=product)
        if sku and Product.query.filter(Product.sku == sku, Product.id != product_id).first():
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
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)
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
def sales():
    items = Sale.query.options(db.joinedload(Sale.items)).order_by(Sale.created_at.desc()).limit(100).all()
    return render_template("sales.html", sales=items)


@app.route("/sales/new", methods=["GET", "POST"])
@login_required
def sale_new():
    products = Product.query.order_by(Product.name.asc()).all()
    line_items = []

    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        payment_method = request.form.get("payment_method", "efectivo").strip()
        product_ids = request.form.getlist("product_id")
        qty_values = request.form.getlist("qty")

        # Obtener todos los productos en una sola query
        valid_ids = [int(pid) for pid in product_ids if pid]
        products_map = {p.id: p for p in Product.query.filter(Product.id.in_(valid_ids)).all()} if valid_ids else {}

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
                "sale_form.html", products=products, line_items=line_items, customer_name=customer_name, payment_method=payment_method
            )

        for item in line_items:
            if item["product"].stock < item["qty"]:
                flash(f"Stock insuficiente para {item['product'].name}", "error")
                return render_template(
                    "sale_form.html", products=products, line_items=line_items, customer_name=customer_name, payment_method=payment_method
                )

        # Determinar estado de pago según el método
        if payment_method == "fiado":
            payment_status = "pendiente"
            paid_cents = 0
        else:
            payment_status = "pagado"
            paid_cents = 0  # Se calculará después
        
        sale = Sale(
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
        return redirect(url_for("sales"))

    return render_template("sale_form.html", products=products, line_items=line_items, customer_name="", payment_method="efectivo")


@app.route("/sales/<int:sale_id>/delete", methods=["POST"])
@login_required
def sale_delete(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    
    try:
        # Devolver stock a los productos y eliminar items explícitamente
        for item in sale.items:
            item.product.stock += item.qty
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


@app.route("/debts")
@login_required
def debts():
    # Obtener todas las ventas con deuda pendiente
    pending_sales = Sale.query.filter(
        Sale.payment_status.in_(["pendiente", "parcial"])
    ).order_by(Sale.created_at.desc()).all()
    
    total_debt_cents = sum(sale.pending_cents for sale in pending_sales)
    
    return render_template("debts.html", pending_sales=pending_sales, total_debt_cents=total_debt_cents)


@app.route("/debts/<int:sale_id>/payment", methods=["GET", "POST"])
@login_required
def payment_register(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    
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
def reports():
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    # Usar índices para hacer queries más rápidas
    total_sales_today = (
        db.session.query(db.func.coalesce(db.func.sum(Sale.total_cents), 0))
        .filter(Sale.created_at >= today_start, Sale.created_at < today_end)
        .scalar()
    )
    total_transactions_today = (
        db.session.query(db.func.count(Sale.id))
        .filter(Sale.created_at >= today_start, Sale.created_at < today_end)
        .scalar()
    )

    # Optimizar query de top productos con LIMIT
    top_products = (
        db.session.query(Product.name, db.func.sum(SaleItem.qty).label("qty"))
        .join(SaleItem, SaleItem.product_id == Product.id)
        .group_by(Product.id, Product.name)
        .order_by(db.desc("qty"))
        .limit(5)
        .all()
    )

    return render_template(
        "reports.html",
        total_sales_today=total_sales_today,
        total_transactions_today=total_transactions_today,
        top_products=top_products,
    )


@app.route("/users")
@login_required
def users():
    users_list = User.query.order_by(User.username.asc()).all()
    return render_template("users.html", users=users_list)


@app.route("/users/new", methods=["GET", "POST"])
@login_required
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
def user_edit(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        role = request.form.get("role", "admin").strip()
        is_active = request.form.get("is_active") == "on"

        if not username or len(username) < 3:
            flash("Usuario debe tener al menos 3 caracteres", "error")
            return render_template("user_form.html", user=user)

        # Verificar si el nuevo username ya existe en otro usuario
        existing = User.query.filter_by(username=username).first()
        if existing and existing.id != user.id:
            flash(f"👤 Usuario '{username}' ya existe en otro perfil. Elige otro.", "error")
            return render_template("user_form.html", user=user)

        user.username = username
        user.role = role
        user.is_active = is_active
        db.session.commit()
        flash("Usuario actualizado", "success")
        return redirect(url_for("users"))

    return render_template("user_form.html", user=user)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def user_delete(user_id):
    user = User.query.get_or_404(user_id)
    
    if user.id == session.get("user_id"):
        flash("No puedes eliminar tu propia cuenta", "error")
        return redirect(url_for("users"))

    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f"Usuario '{username}' eliminado", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/password", methods=["GET", "POST"])
@login_required
def user_change_password(user_id):
    user = User.query.get_or_404(user_id)
    
    # Solo admin o el mismo usuario pueden cambiar contraseña
    if session.get("user_id") != user_id and session.get("role") != "admin":
        flash("No tienes permiso para cambiar esta contraseña", "error")
        return redirect(url_for("users"))
    
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        # Verificar contraseña antigua solo si el usuario intenta cambiar su propia contraseña
        if user.id == session.get("user_id"):
            if not user.check_password(old_password):
                flash("Contraseña actual incorrecta", "error")
                return render_template("user_password.html", user=user)

        if not new_password or len(new_password) < 6:
            flash("Nueva contraseña debe tener al menos 6 caracteres", "error")
            return render_template("user_password.html", user=user)

        if new_password != confirm_password:
            flash("Las contraseñas no coinciden", "error")
            return render_template("user_password.html", user=user)

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash("Contraseña actualizada", "success")
        return redirect(url_for("users"))

    return render_template("user_password.html", user=user)


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True, use_reloader=False)
