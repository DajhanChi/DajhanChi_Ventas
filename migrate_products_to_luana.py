#!/usr/bin/env python
"""
Script para migrar productos de SKU >= 100 a usuario Luana
"""
import os
import sys
from app import app, db, User, Product
from werkzeug.security import generate_password_hash

with app.app_context():
    # Obtener el usuario actual (dajhanchi)
    current_user = User.query.filter_by(username="dajhanchi").first()
    if not current_user:
        print("✗ Usuario 'dajhanchi' no encontrado")
        sys.exit(1)
    
    print(f"✓ Usuario actual: {current_user.username} (ID: {current_user.id})")
    
    # Crear o obtener usuario Luana
    luana = User.query.filter_by(username="luana").first()
    if not luana:
        luana = User(
            username="luana",
            password_hash=generate_password_hash("luana123"),
            role="user",
            is_active=True
        )
        db.session.add(luana)
        db.session.commit()
        print(f"✓ Usuario 'luana' creado (ID: {luana.id})")
    else:
        print(f"✓ Usuario 'luana' ya existe (ID: {luana.id})")
    
    # Buscar productos con SKU >= "sku_100"
    # Primero como string, luego extraer los numéricos
    products_to_migrate = []
    
    # Obtener todos los productos del usuario actual
    all_products = Product.query.filter_by(user_id=current_user.id).all()
    
    for product in all_products:
        if product.sku:
            # Extraer número del SKU si comienza con "sku_"
            if product.sku.startswith("sku_"):
                try:
                    sku_number = int(product.sku.replace("sku_", ""))
                    if sku_number >= 100:
                        products_to_migrate.append(product)
                except ValueError:
                    pass
    
    print(f"\n📦 Productos encontrados para migrar: {len(products_to_migrate)}")
    
    if products_to_migrate:
        print("\nProductos a migrar:")
        for p in products_to_migrate:
            print(f"  - {p.name} (SKU: {p.sku}, Stock: {p.stock})")
        
        # Migrar productos a Luana
        print(f"\n🔄 Migrando {len(products_to_migrate)} productos a Luana...")
        for product in products_to_migrate:
            product.user_id = luana.id
        
        db.session.commit()
        print(f"✓ {len(products_to_migrate)} productos migrados exitosamente")
        
        # Mostrar resumen
        print("\n📊 Resumen después de migración:")
        dajhanchi_products = Product.query.filter_by(user_id=current_user.id).count()
        luana_products = Product.query.filter_by(user_id=luana.id).count()
        print(f"  - {current_user.username}: {dajhanchi_products} productos")
        print(f"  - luana: {luana_products} productos")
    else:
        print("\n✗ No se encontraron productos con SKU >= 100")
        print("\n📊 Productos actuales de dajhanchi:")
        for p in all_products[:10]:
            print(f"  - {p.name} (SKU: {p.sku})")
        if len(all_products) > 10:
            print(f"  ... y {len(all_products) - 10} más")
