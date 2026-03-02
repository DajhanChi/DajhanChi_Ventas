"""Add user_id to Product and Sale models for multi-user support

Revision ID: add_user_id_multi_user
Revises: a156297d37c5
Create Date: 2026-02-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_user_id_multi_user'
down_revision = 'a156297d37c5'
branch_labels = None
depends_on = None


def upgrade():
    # Add user_id to product table
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_product_user_id', 'user', ['user_id'], ['id'])
        batch_op.create_index('ix_product_user_id', ['user_id'])
    
    # Set all existing products to admin user (id=1)
    op.execute("UPDATE product SET user_id = 1 WHERE user_id IS NULL")
    
    # Make user_id NOT NULL
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.alter_column('user_id', existing_type=sa.Integer(), nullable=False)
    
    # Add user_id to sale table
    with op.batch_alter_table('sale', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_sale_user_id', 'user', ['user_id'], ['id'])
        batch_op.create_index('ix_sale_user_id', ['user_id'])
    
    # Set all existing sales to admin user (id=1)
    op.execute("UPDATE sale SET user_id = 1 WHERE user_id IS NULL")
    
    # Make user_id NOT NULL
    with op.batch_alter_table('sale', schema=None) as batch_op:
        batch_op.alter_column('user_id', existing_type=sa.Integer(), nullable=False)


def downgrade():
    # Remove user_id from sale table
    with op.batch_alter_table('sale', schema=None) as batch_op:
        batch_op.drop_index('ix_sale_user_id')
        batch_op.drop_constraint('fk_sale_user_id', type_='foreignkey')
        batch_op.drop_column('user_id')
    
    # Remove user_id from product table
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_index('ix_product_user_id')
        batch_op.drop_constraint('fk_product_user_id', type_='foreignkey')
        batch_op.drop_column('user_id')
