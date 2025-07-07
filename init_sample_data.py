#!/usr/bin/env python3
"""
Sample data initialization script for budget categories.
Run this after creating your first plan to populate with sample categories.
"""

from website import create_app, db
from website.models import User, Plan, BudgetCategory

def init_sample_categories():
    app = create_app()
    
    with app.app_context():
        # Get the first user (for testing)
        user = User.query.first()
        if not user or not user.active_plan:
            print("No user or active plan found. Please create a user and plan first.")
            return
        
        plan = user.active_plan
        
        # Check if categories already exist
        existing_categories = BudgetCategory.query.filter_by(plan_id=plan.id).count()
        if existing_categories > 0:
            print(f"Categories already exist for plan '{plan.name}'. Skipping initialization.")
            return
        
        # Sample categories to create
        sample_categories = [
            # Bills
            {'name': 'Utilities', 'main_category': 'bills', 'icon': 'bx-bulb', 'assigned': 1000.00},
            {'name': 'TV, phone and internet', 'main_category': 'bills', 'icon': 'bx-tv', 'assigned': 100.00},
            {'name': 'Insurance', 'main_category': 'bills', 'icon': 'bx-shield', 'assigned': 8400.00},
            
            # Needs
            {'name': 'Transportation', 'main_category': 'needs', 'icon': 'bx-car', 'assigned': 500.00},
            {'name': 'Car maintenance', 'main_category': 'needs', 'icon': 'bx-wrench', 'assigned': 0.00},
            {'name': 'Bike maintenance', 'main_category': 'needs', 'icon': 'bx-cycling', 'assigned': 0.00},
            {'name': 'Home maintenance', 'main_category': 'needs', 'icon': 'bx-home', 'assigned': 0.00},
            {'name': 'Personal care', 'main_category': 'needs', 'icon': 'bx-user', 'assigned': 0.00},
            
            # Wants
            {'name': 'Dining out', 'main_category': 'wants', 'icon': 'bx-restaurant', 'assigned': 0.00},
            {'name': 'Entertainment', 'main_category': 'wants', 'icon': 'bx-movie-play', 'assigned': 0.00},
            {'name': 'Hobbies', 'main_category': 'wants', 'icon': 'bx-game', 'assigned': 0.00},
            {'name': 'Charity', 'main_category': 'wants', 'icon': 'bx-heart', 'assigned': 0.00},
            {'name': 'Holidays & gifts', 'main_category': 'wants', 'icon': 'bx-gift', 'assigned': 0.00},
            {'name': 'Decor & garden', 'main_category': 'wants', 'icon': 'bx-home-heart', 'assigned': 0.00},
            {'name': 'Shopping', 'main_category': 'wants', 'icon': 'bx-shopping-bag', 'assigned': 0.00},
            
            # Investments
            {'name': 'Emergency Fund', 'main_category': 'investments', 'icon': 'bx-shield-alt-2', 'assigned': 0.00},
            {'name': 'Retirement', 'main_category': 'investments', 'icon': 'bx-trending-up', 'assigned': 0.00},
            {'name': 'Savings', 'main_category': 'investments', 'icon': 'bx-dollar-circle', 'assigned': 0.00},
        ]
        
        # Create categories
        categories_created = 0
        for cat_data in sample_categories:
            category = BudgetCategory(
                name=cat_data['name'],
                main_category=cat_data['main_category'],
                icon=cat_data['icon'],
                assigned_amount=cat_data['assigned'],
                plan_id=plan.id
            )
            db.session.add(category)
            categories_created += 1
        
        # Add some sample transactions to Utilities to show spent amounts
        from website.models import Transaction
        utilities_cat = BudgetCategory.query.filter_by(name='Utilities', plan_id=plan.id).first()
        if utilities_cat:
            transaction = Transaction(
                description='Electric bill',
                amount=-900.00,  # Negative for expense
                category_id=utilities_cat.id,
                plan_id=plan.id
            )
            db.session.add(transaction)
        
        tv_cat = BudgetCategory.query.filter_by(name='TV, phone and internet', plan_id=plan.id).first()
        if tv_cat:
            transaction = Transaction(
                description='Internet bill',
                amount=-100.00,  # Negative for expense
                category_id=tv_cat.id,
                plan_id=plan.id
            )
            db.session.add(transaction)
        
        try:
            db.session.commit()
            print(f"Successfully created {categories_created} sample categories for plan '{plan.name}'")
            print("Sample transactions added to show spending examples.")
        except Exception as e:
            db.session.rollback()
            print(f"Error creating sample data: {e}")

if __name__ == '__main__':
    init_sample_categories()
