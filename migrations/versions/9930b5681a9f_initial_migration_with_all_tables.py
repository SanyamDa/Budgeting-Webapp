"""Initial migration with all tables

Revision ID: 9930b5681a9f
Revises: 
Create Date: 2025-07-14 22:48:36.227580

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9930b5681a9f'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('plan',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('monthly_income', sa.Float(), nullable=True),
    sa.Column('budget_pref', sa.JSON(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=150), nullable=False),
    sa.Column('password', sa.String(length=150), nullable=True),
    sa.Column('first_name', sa.String(length=150), nullable=True),
    sa.Column('last_name', sa.String(length=150), nullable=True),
    sa.Column('active_plan_id', sa.Integer(), nullable=True),
    sa.Column('profile_complete', sa.Boolean(), nullable=True),
    sa.Column('theme', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['active_plan_id'], ['plan.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('budget_category',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('icon', sa.String(length=50), nullable=True),
    sa.Column('main_category', sa.String(length=50), nullable=False),
    sa.Column('assigned_amount', sa.Float(), nullable=True),
    sa.Column('spent_amount', sa.Float(), nullable=True),
    sa.Column('plan_id', sa.Integer(), nullable=False),
    sa.Column('created_date', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['plan_id'], ['plan.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('monthly_rollover',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Float(), nullable=True),
    sa.Column('plan_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plan.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('note',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('data', sa.String(length=10000), nullable=True),
    sa.Column('date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('monthly_budget',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('assigned_amount', sa.Float(), nullable=True),
    sa.Column('spent_amount', sa.Float(), nullable=True),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('plan_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['budget_category.id'], ),
    sa.ForeignKeyConstraint(['plan_id'], ['plan.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('transaction',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=200), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('transaction_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('plan_id', sa.Integer(), nullable=False),
    sa.Column('created_date', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['category_id'], ['budget_category.id'], ),
    sa.ForeignKeyConstraint(['plan_id'], ['plan.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('transaction')
    op.drop_table('monthly_budget')
    op.drop_table('note')
    op.drop_table('monthly_rollover')
    op.drop_table('budget_category')
    op.drop_table('user')
    op.drop_table('plan')
    # ### end Alembic commands ###
