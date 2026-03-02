#!/usr/bin/env python
"""
Script para probar la funcionalidad de multi-usuario
"""
import os
import sys
from app import app, db, User, Product, Sale
from werkzeug.security import generate_password_hash

# Asegurarse de que estamos en el contexto de la aplicación
with app.app_context():
    # Crear un nuevo usuario de prueba
    test_user = User.query.filter_by(username="test_user").first()
    if not test_user:
        test_user = User(
            username="test_user",
            password_hash=generate_password_hash("test123"),
            role="user",
            is_active=True
        )
        db.session.add(test_user)
        db.session.commit()
        print(f"✓ Usuario 'test_user' creado con ID: {test_user.id}")
    else:
        print(f"✓ Usuario 'test_user' ya existe con ID: {test_user.id}")
    
    # Obtener el primer usuario (admin)
    admin = User.query.first()
    if admin:
        print(f"✓ Usuario principal '{admin.username}' encontrado con ID: {admin.id}")
    else:
        print("✗ No hay usuarios en la base de datos")
        sys.exit(1)
    
    # Contar productos por usuario
    admin_products = Product.query.filter_by(user_id=admin.id).count()
    test_products = Product.query.filter_by(user_id=test_user.id).count()
    
    print(f"\n📊 Productos por usuario:")
    print(f"   - {admin.username}: {admin_products}")
    print(f"   - test_user: {test_products}")
    
    # Contar ventas por usuario
    admin_sales = Sale.query.filter_by(user_id=admin.id).count()
    test_sales = Sale.query.filter_by(user_id=test_user.id).count()
    
    print(f"\n📊 Ventas por usuario:")
    print(f"   - {admin.username}: {admin_sales}")
    print(f"   - test_user: {test_sales}")
    
    print("\n✓ Base de datos está lista para multi-usuario")
    print("\nPuedes iniciar la aplicación con:")
    print("  python app.py")
    print("\nLuego accede a http://localhost:5000 y login con:")
    print(f"  - Usuario: {admin.username}")
    print("  - Usuario: test_user / test123")
