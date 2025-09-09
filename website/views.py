from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, request, flash, jsonify, redirect, url_for
from flask_login import login_required, current_user
from .models import Note, Plan, BudgetCategory, MonthlyBudget, Transaction, Payee, MonthlyRollover, AdditionalIncome
from . import db
import json
from datetime import datetime, date
import calendar
from sqlalchemy import func, and_
from collections import defaultdict
import traceback
from openai import OpenAI
import base64
from io import BytesIO
import random
from PIL import Image
import pillow_heif

# Register HEIF opener with PIL
pillow_heif.register_heif_opener()

views = Blueprint('views', __name__)

# Helper function for budget validation
def validate_budget_limit(category, transaction_amount, transaction_date=None):
    """
    Validate if a transaction amount would exceed the category's budget limit.
    Returns (is_valid, error_message, validation_data)
    """
    try:
        # Use transaction date to determine which month's budget to check
        if transaction_date is None:
            transaction_date = datetime.now()
        
        target_month = transaction_date.month
        target_year = transaction_date.year
        
        # Get the monthly budget for this category and month
        monthly_budget = MonthlyBudget.query.filter_by(
            plan_id=category.plan_id,
            category_id=category.id,
            month=target_month,
            year=target_year
        ).first()
        
        # If no monthly budget exists, use 0 as assigned amount (no budget set for this month)
        assigned_amount = monthly_budget.assigned_amount if monthly_budget else 0
        
        # Calculate current spent amount for this specific month
        current_spent = db.session.query(func.sum(func.abs(Transaction.amount))).filter(
            Transaction.category_id == category.id,
            func.extract('month', Transaction.transaction_date) == target_month,
            func.extract('year', Transaction.transaction_date) == target_year
        ).scalar() or 0
        
        # Check if this transaction would exceed the category limit
        new_total_spent = current_spent + transaction_amount
        available_amount = assigned_amount - current_spent
        
        if new_total_spent > assigned_amount:
            excess_amount = new_total_spent - assigned_amount
            error_message = f'Transaction exceeds budget limit for "{category.name}" category. Available: ฿{available_amount:.2f}, Requested: ฿{transaction_amount:.2f}, Excess: ฿{excess_amount:.2f}'
            
            validation_data = {
                'error_type': 'budget_exceeded',
                'available_amount': available_amount,
                'requested_amount': transaction_amount,
                'excess_amount': excess_amount,
                'category_name': category.name,
                'current_spent': current_spent,
                'category_limit': assigned_amount
            }
            
            return False, error_message, validation_data
        
        # Validation passed
        validation_data = {
            'available_amount': available_amount,
            'requested_amount': transaction_amount,
            'category_name': category.name,
            'current_spent': current_spent,
            'category_limit': assigned_amount,
            'new_total_spent': new_total_spent
        }
        
        return True, None, validation_data
        
    except Exception as e:
        return False, f'Error validating budget: {str(e)}', {}

# Additional validation functions
def validate_transaction_data(amount, description, category_id, plan_id):
    """
    Comprehensive validation for transaction data.
    Returns (is_valid, error_message)
    """
    # Amount validation
    if not amount or amount <= 0:
        return False, "Transaction amount must be greater than zero"
    
    if amount > 1000000:  # 1 million baht limit
        return False, "Transaction amount exceeds maximum limit of ฿1,000,000"
    
    # Description validation
    if not description or not description.strip():
        return False, "Transaction description is required"
    
    if len(description.strip()) < 2:
        return False, "Transaction description must be at least 2 characters"
    
    if len(description) > 200:
        return False, "Transaction description must be less than 200 characters"
    
    # Category validation
    if not category_id:
        return False, "Category is required"
    
    category = BudgetCategory.query.filter_by(id=category_id, plan_id=plan_id).first()
    if not category:
        return False, "Invalid category selected"
    
    return True, None

def validate_monthly_spending_limit(plan, transaction_amount):
    """
    Check if transaction would exceed monthly spending limits.
    Returns (is_valid, warning_message)
    """
    try:
        # Get current month's spending
        current_date = datetime.now()
        month_start = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        monthly_spent = db.session.query(func.sum(func.abs(Transaction.amount))).filter(
            Transaction.plan_id == plan.id,
            Transaction.transaction_date >= month_start
        ).scalar() or 0
        
        # Calculate total monthly budget
        total_budget = db.session.query(func.sum(BudgetCategory.assigned_amount)).filter_by(
            plan_id=plan.id
        ).scalar() or 0
        
        new_monthly_total = monthly_spent + transaction_amount
        
        # Warning if exceeding 90% of monthly budget
        if new_monthly_total > (total_budget * 0.9):
            remaining_budget = total_budget - monthly_spent
            return False, f"Warning: This transaction will use ฿{transaction_amount:.2f} of your remaining ฿{remaining_budget:.2f} monthly budget. Consider reviewing your spending."
        
        return True, None
        
    except Exception as e:
        return True, None  # Don't block transaction for validation errors

def check_duplicate_transaction(plan_id, amount, description, payee_id=None, hours_threshold=1):
    """
    Check for potential duplicate transactions within the last few hours.
    Returns (is_duplicate, warning_message)
    """
    try:
        # Check for similar transactions in the last hour
        time_threshold = datetime.now() - timedelta(hours=hours_threshold)
        
        query = Transaction.query.filter(
            Transaction.plan_id == plan_id,
            func.abs(Transaction.amount) == amount,
            Transaction.transaction_date >= time_threshold
        )
        
        # Add payee filter if provided
        if payee_id:
            query = query.filter(Transaction.payee_id == payee_id)
        
        # Check description similarity (exact match or very similar)
        similar_transactions = query.filter(
            func.lower(Transaction.description).like(f"%{description.lower()}%")
        ).all()
        
        if similar_transactions:
            return True, f"Warning: Similar transaction detected within the last {hours_threshold} hour(s). Please verify this is not a duplicate."
        
        return False, None
        
    except Exception as e:
        return False, None  # Don't block transaction for validation errors

@views.route('/<int:year>/<int:month>')
@views.route('/')
@login_required
def home(year=None, month=None):
    # Redirect to onboarding if the user hasn't created their first plan yet
    if not current_user.profile_complete or not current_user.active_plan:
        return redirect(url_for('onboard.show_form'))

    plan = current_user.active_plan

    # Determine the date to display
    if year is None or month is None:
        today = datetime.now()
        year, month = today.year, today.month
    
    try:
        display_date = datetime(year, month, 1)
    except ValueError:
        # Handle invalid month/year in URL
        today = datetime.now()
        year, month = today.year, today.month
        display_date = today

    display_month_str = display_date.strftime('%B')

    # Determine if the current view is the user's first month
    user_join_date = current_user.date_created
    if user_join_date is None:
        # If the user has no join date, set it to now to prevent crash and fix the data.
        user_join_date = datetime.now()
        current_user.date_created = user_join_date
        db.session.commit()

    is_first_month = (display_date.year == user_join_date.year and display_date.month == user_join_date.month)
    
    # --- Rollover Calculation ---
    previous_month_date = display_date - relativedelta(months=1)
    prev_month_int = previous_month_date.month
    prev_month_year = previous_month_date.year

    # Initialize rollover amount
    rollover_amount = 0.0
    
    # Check if the display month is after the user's join month before calculating rollover
    if not is_first_month:
        # Try to find an existing rollover record
        rollover_from_last_month = MonthlyRollover.query.filter_by(
            plan_id=plan.id, month=prev_month_int, year=prev_month_year
        ).first()

        if rollover_from_last_month:
            rollover_amount = rollover_from_last_month.amount
        else:
            # If no rollover record exists, start with 0 for this month
            # The rollover will be created when this month's leftover is calculated
            rollover_amount = 0.0

    # --- Budget Processing for Display Month ---
    categories = BudgetCategory.query.filter_by(plan_id=plan.id).all()
    monthly_budgets_map = {}
    for cat in categories:
        mb = MonthlyBudget.query.filter_by(plan_id=plan.id, category_id=cat.id, month=month, year=year).first()
        if not mb:
            # For new months, start with assigned_amount = 0 (fresh start)
            mb = MonthlyBudget(plan_id=plan.id, category_id=cat.id, month=month, year=year, assigned_amount=0, spent_amount=0)
            db.session.add(mb)
        monthly_budgets_map[cat.id] = mb
    db.session.commit()

    organized_categories = {'needs': [], 'wants': [], 'investments': []}
    total_assigned = 0
    total_spent = 0
    
    for category in categories:
        mb = monthly_budgets_map.get(category.id)
        if mb:
            category.assigned_amount = mb.assigned_amount
            spent = db.session.query(func.sum(Transaction.amount)).filter(
                Transaction.category_id == category.id,
                func.extract('month', Transaction.transaction_date) == month,
                func.extract('year', Transaction.transaction_date) == year
            ).scalar() or 0
            mb.spent_amount = abs(spent)
            category.spent_amount = abs(spent)
        
        total_assigned += category.assigned_amount
        total_spent += category.spent_amount
        
        if category.main_category in organized_categories:
            organized_categories[category.main_category].append(category)
    db.session.commit()
    
    category_totals = {}
    for main_cat, cats in organized_categories.items():
        category_totals[main_cat] = {
            'assigned': sum(c.assigned_amount for c in cats),
            'spent': sum(c.spent_amount for c in cats),
            'available': sum(c.available_amount for c in cats)
        }
    
    # Follow user's calculation rules:
    # Assigned in Month = amount assigned to all subcategories
    assigned_in_month = total_assigned
    
    # Activity = total activity in all categories and subcategories
    activity = total_spent
    
    # Available = assigned_in_month - activity
    available = assigned_in_month - activity
    
    # Get additional income for this month
    additional_income_total = db.session.query(func.sum(AdditionalIncome.amount)).filter_by(
        plan_id=plan.id, month=month, year=year
    ).scalar() or 0.0
    
    # Money Remaining to Assign = monthly_income + additional_income + rollover - assigned_total
    # Additional income increases the total available money pool
    money_remaining_to_assign = (plan.monthly_income + additional_income_total + rollover_amount) - total_assigned
    
    # Leftover for the month = money_remaining_to_assign + available
    leftover_for_month = money_remaining_to_assign + available
    
    # Save current month's leftover as rollover for future months
    existing_rollover = MonthlyRollover.query.filter_by(
        plan_id=plan.id, month=month, year=year
    ).first()
    
    if existing_rollover:
        # Update existing rollover record
        existing_rollover.amount = leftover_for_month
    else:
        # Create new rollover record
        new_rollover = MonthlyRollover(
            plan_id=plan.id, month=month, year=year, amount=leftover_for_month
        )
        db.session.add(new_rollover)
    
    db.session.commit()

    all_categories = sorted([cat for cat in categories if cat.spent_amount > 0], key=lambda x: x.spent_amount, reverse=True)
    top_spending_categories = all_categories[:5]

    # --- Date navigation and disabling logic ---
    
    prev_month_date = display_date - relativedelta(months=1)
    next_month_date = display_date + relativedelta(months=1)

    # Check if user can navigate to previous month (based on when they joined)
    user_start_date = current_user.date_created
    user_start_month = user_start_date.month
    user_start_year = user_start_date.year

    # Disable previous month navigation if trying to go before user's start month
    can_go_prev = not (prev_month_date.year < user_start_year or 
                   (prev_month_date.year == user_start_year and prev_month_date.month < user_start_month))
    can_go_next = True

    return render_template("home.html", 
                         plan=plan,
                         categories=organized_categories,
                         category_totals=category_totals,
                         current_month=display_month_str,
                         current_month_num=month,
                         current_year=year,
                         # For navigation
                         prev_month=prev_month_date.month,
                         prev_year=prev_month_date.year,
                         next_month=next_month_date.month,
                         next_year=next_month_date.year,
                         is_first_month=is_first_month,
                         can_go_prev=can_go_prev,
                         can_go_next=can_go_next,
                         # Summary data (following user's calculation rules)
                         total_assigned=assigned_in_month,  # Assigned in Month
                         total_spent=activity,  # Activity
                         available_amount=available,  # Available = assigned_in_month - activity
                         money_remaining_to_assign=money_remaining_to_assign,  # Money Remaining to Assign
                         leftover_for_month=leftover_for_month,  # Leftover for the month
                         rollover_amount=rollover_amount,
                         top_spending_categories=top_spending_categories)


@views.route('/api/update-assigned', methods=['POST'])
@login_required
def update_assigned():
    data = request.get_json()
    category_id = data.get('category_id')
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid amount value'}), 400
    if category_id is None or amount is None:
        return jsonify({'success': False, 'message': 'Invalid data'}), 400

    category = BudgetCategory.query.get(category_id)
    if not category:
        return jsonify({'success': False, 'message': 'Category not found'}), 404

    # Determine month/year
    now = datetime.now()
    mb = MonthlyBudget.query.filter_by(plan_id=category.plan_id, category_id=category_id, month=now.month, year=now.year).first()
    if not mb:
        mb = MonthlyBudget(plan_id=category.plan_id, category_id=category_id, month=now.month, year=now.year)
        db.session.add(mb)

    mb.assigned_amount = amount
    category.assigned_amount = amount  # keep legacy field in sync

    db.session.commit()

    return jsonify({'success': True, 'assigned_amount': amount})

@views.route('/api/update-category-amount', methods=['POST'])
@login_required
def update_category_amount():
    """API endpoint to update category assigned amount with validation"""
    try:
        data = request.get_json()
        print(f"Raw request data: {data}")  # Debug: see what we actually receive
        print(f"Request headers: {dict(request.headers)}")  # Debug: check content type
        category_id = data.get('category_id')
        new_amount = float(data.get('amount', 0))
        
        # Get month and year from request, default to current month if not provided
        target_month = data.get('month')
        target_year = data.get('year')
        
        if target_month is None or target_year is None:
            current_date = datetime.now()
            target_month = target_month or current_date.month
            target_year = target_year or current_date.year
        
        print(f"Extracted category_id: {category_id}, type: {type(category_id)}")  # Debug
        print(f"Target month: {target_month}, Target year: {target_year}")  # Debug
        
        # Convert category_id to integer if it's a string
        if category_id is not None:
            try:
                category_id = int(category_id)
                print(f"Converted category_id to int: {category_id}")  # Debug
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid category ID'}), 400
        else:
            return jsonify({'success': False, 'error': 'Category ID is required'}), 400

        if new_amount < 0:
            return jsonify({'success': False, 'error': 'Assigned amount cannot be negative.'}), 400

        plan = current_user.active_plan
        if not plan:
            return jsonify({'success': False, 'error': 'No active plan found'}), 400

        # Debug: Print what we're looking for
        print(f"Looking for category_id: {category_id}, plan_id: {plan.id}")
        
        # Get the category to update
        category_to_update = BudgetCategory.query.filter_by(
            id=category_id,
            plan_id=plan.id
        ).first()
        
        # Debug: Print all categories for this plan
        all_categories = BudgetCategory.query.filter_by(plan_id=plan.id).all()
        print(f"All categories for plan {plan.id}:")
        for cat in all_categories:
            print(f"  ID: {cat.id}, Name: {cat.name}, Main: {cat.main_category}")

        if not category_to_update:
            return jsonify({'success': False, 'error': f'Category not found. Looking for ID {category_id} in plan {plan.id}'}), 404

        # Get the main category name (needs, wants, or investments)
        print(f"About to access category_to_update attributes...")  # Debug
        print(f"Category object: {category_to_update}")  # Debug
        print(f"Category found: {category_to_update.name}, main_category: {category_to_update.main_category}")  # Debug
        main_cat_name = category_to_update.main_category.lower()
        print(f"Main category name: {main_cat_name}")  # Debug
        
        # Get budget ratios and calculate limits
        print(f"DEBUG RATIO RETRIEVAL: plan.budget_pref = {plan.budget_pref}")
        budget_ratios = plan.budget_pref.get('ratios', {}) if plan.budget_pref else {}
        print(f"DEBUG RATIO RETRIEVAL: budget_ratios = {budget_ratios}")
        print(f"DEBUG RATIO RETRIEVAL: main_cat_name = {main_cat_name}")
        
        # Handle naming inconsistency: "investments" in categories vs "savings" in budget_pref
        ratio_key = main_cat_name
        if main_cat_name == 'investments':
            ratio_key = 'savings'
        
        print(f"DEBUG RATIO RETRIEVAL: ratio_key = {ratio_key}")
        
        try:
            raw_ratio = budget_ratios.get(ratio_key, 0)
            print(f"DEBUG RATIO RETRIEVAL: raw_ratio from budget_ratios.get('{ratio_key}', 0) = {raw_ratio}")
            category_ratio = raw_ratio / 100.0
            print(f"DEBUG RATIO RETRIEVAL: Final category_ratio for {main_cat_name} = {category_ratio}")
        except Exception as e:
            print(f"Error calculating category ratio: {e}")  # Debug
            raise        
        # Calculate the maximum allowed amount based on the ratio
        max_allowed = plan.monthly_income * category_ratio if plan.monthly_income else 0
        
        # Get current total assigned to this main category from MonthlyBudget records
        current_total = 0
        for c in plan.categories:
            if c.main_category.lower() == main_cat_name and c.id != category_id:
                mb = MonthlyBudget.query.filter_by(
                    plan_id=plan.id, 
                    category_id=c.id, 
                    month=target_month, 
                    year=target_year
                ).first()
                if mb:
                    current_total += mb.assigned_amount
                else:
                    current_total += c.assigned_amount  # fallback to base amount
        
        # Check if new amount would exceed the category's budget
        if (current_total + new_amount) > max_allowed:
            error_msg = (
                f"Cannot assign ${new_amount:.2f}. You only have "
                f"${(max_allowed - current_total):.2f} left to assign in "
                f"{main_cat_name.capitalize()}."
            )
            return jsonify({'success': False, 'error': error_msg}), 400
        # Update the category amount
        # Find or create MonthlyBudget record for this category and target month
        monthly_budget = MonthlyBudget.query.filter_by(
            plan_id=plan.id, 
            category_id=category_id, 
            month=target_month, 
            year=target_year
        ).first()
        
        if not monthly_budget:
            monthly_budget = MonthlyBudget(
                plan_id=plan.id,
                category_id=category_id,
                month=target_month,
                year=target_year,
                assigned_amount=new_amount,
                spent_amount=0
            )
            db.session.add(monthly_budget)
        else:
            monthly_budget.assigned_amount = new_amount
        
        # Also update the base category for consistency
        print(f"About to update category {category_to_update.id} from {category_to_update.assigned_amount} to {new_amount}")  # Debug
        old_amount = category_to_update.assigned_amount
        category_to_update.assigned_amount = new_amount
        
        try:
            db.session.commit()
            print("Database commit successful")  # Debug
        except Exception as e:
            print(f"Database commit failed: {e}")  # Debug
            raise

        # Calculate updated totals
        try:
            parent_total_assigned = 0
            parent_total_spent = 0
            
            for c in plan.categories:
                if c.main_category.lower() == main_cat_name:
                    mb = MonthlyBudget.query.filter_by(
                        plan_id=plan.id, 
                        category_id=c.id, 
                        month=current_month, 
                        year=current_year
                    ).first()
                    if mb:
                        parent_total_assigned += mb.assigned_amount
                        parent_total_spent += mb.spent_amount
                    else:
                        parent_total_assigned += c.assigned_amount
                        parent_total_spent += c.spent_amount
            
            parent_total_available = parent_total_assigned - parent_total_spent
            
            # Calculate grand total from all MonthlyBudget records
            grand_total_assigned = 0
            for c in plan.categories:
                mb = MonthlyBudget.query.filter_by(
                    plan_id=plan.id, 
                    category_id=c.id, 
                    month=current_month, 
                    year=current_year
                ).first()
                if mb:
                    grand_total_assigned += mb.assigned_amount
                else:
                    grand_total_assigned += c.assigned_amount
            
            print(f"Calculated totals successfully: parent_assigned={parent_total_assigned}, grand_total={grand_total_assigned}")  # Debug
        except Exception as e:
            print(f"Error calculating totals: {e}")  # Debug
            raise

        category_available = new_amount - category_to_update.spent_amount

        # Calculate money remaining (monthly income - total assigned)
        money_remaining = (plan.monthly_income or 0) - grand_total_assigned
        
        return jsonify({
            'success': True,
            'updated_subcategory': {
                'id': category_to_update.id,
                'new_amount': new_amount,
                'available_amount': category_available
            },
            'updated_parent_category': {
                'name': main_cat_name,
                'total_assigned': parent_total_assigned,
                'total_available': parent_total_available
            },
            'new_grand_total_assigned': grand_total_assigned,
            'money_remaining': money_remaining
        })

    except Exception as e:
        import traceback
        print(f"FULL ERROR TRACEBACK:")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500

@views.route('/api/add-transaction', methods=['POST'])
@login_required
def add_transaction():
    """API endpoint to add a new transaction with budget validation"""
    try:
        data = request.get_json()
        category_id = data.get('category_id')
        amount = float(data.get('amount', 0))
        description = data.get('description', 'Transaction')
        payee_id = data.get('payee_id')
        
        # Get transaction date from request, default to current date if not provided
        transaction_date_str = data.get('transaction_date')
        print(f"DEBUG: Received transaction_date_str: '{transaction_date_str}'")  # Debug
        
        if transaction_date_str:
            try:
                # Try different date formats
                if '/' in transaction_date_str:
                    # Handle DD/MM/YYYY format
                    transaction_date = datetime.strptime(transaction_date_str, '%d/%m/%Y')
                else:
                    # Handle YYYY-MM-DD format (HTML date input standard)
                    transaction_date = datetime.strptime(transaction_date_str, '%Y-%m-%d')
                print(f"DEBUG: Parsed transaction_date: {transaction_date}")  # Debug
            except ValueError as e:
                print(f"DEBUG: Date parsing error: {e}")  # Debug
                return jsonify({'success': False, 'error': f'Invalid date format: {transaction_date_str}. Expected YYYY-MM-DD or DD/MM/YYYY'}), 400
        else:
            transaction_date = datetime.now()
            print(f"DEBUG: Using current date: {transaction_date}")  # Debug
        
        # Comprehensive transaction validation
        is_valid, error_msg = validate_transaction_data(amount, description, category_id, current_user.active_plan.id)
        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400
        
        # Check for duplicate transactions
        is_duplicate, duplicate_warning = check_duplicate_transaction(
            current_user.active_plan.id, amount, description, payee_id
        )
        if is_duplicate:
            return jsonify({
                'success': False, 
                'error': duplicate_warning,
                'error_type': 'duplicate_warning'
            }), 400
        
        category = BudgetCategory.query.filter_by(
            id=category_id,
            plan_id=current_user.active_plan.id
        ).first()
        
        if not category:
            return jsonify({'success': False, 'error': 'Category not found'}), 404
        
        # Ensure the date is stored as a naive datetime to avoid timezone issues
        naive_transaction_date = transaction_date.replace(tzinfo=None) if transaction_date.tzinfo else transaction_date
        
        # Validate budget limit using helper function
        is_valid, error_message, validation_data = validate_budget_limit(category, amount, naive_transaction_date)
        
        if not is_valid:
            return jsonify({
                'success': False, 
                'error': error_message,
                **validation_data
            }), 400
        
        # Create new transaction (amount should be negative for expenses)
        print(f"DEBUG: About to store transaction with date: {naive_transaction_date}")  # Debug
        print(f"DEBUG: Date type: {type(naive_transaction_date)}")  # Debug
        
        transaction = Transaction(
            description=description,
            amount=-abs(amount),  # Make negative for expenses
            category_id=category_id,
            payee_id=payee_id,
            plan_id=current_user.active_plan.id,
            transaction_date=naive_transaction_date
        )
        
        print(f"DEBUG: Transaction object created, date before save: {transaction.transaction_date}")  # Debug
        
        db.session.add(transaction)
        print(f"DEBUG: Transaction added to session, date: {transaction.transaction_date}")  # Debug
        
        db.session.commit()
        print(f"DEBUG: Transaction committed, final date: {transaction.transaction_date}")  # Debug
        
        # Refresh from database to see what was actually stored
        db.session.refresh(transaction)
        print(f"DEBUG: After refresh from DB - ID: {transaction.id}, Date: {transaction.transaction_date}")  # Debug
        
        # Update category spent amount
        spent = db.session.query(func.sum(func.abs(Transaction.amount))).filter_by(
            category_id=category.id
        ).scalar() or 0
        category.spent_amount = spent
        db.session.commit()
        
        flash(f'Transaction added successfully! ฿{amount:.2f} spent on "{category.name}"', 'success')

        return jsonify({
            'success': True,
            'transaction_id': transaction.id,
            'category_spent': category.spent_amount,
            'category_available': category.assigned_amount - category.spent_amount,
            'message': f'Transaction added successfully! ฿{amount:.2f} spent on "{category.name}"'
        })
        
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid amount format'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@views.route('/api/create-category', methods=['POST'])
@login_required
def create_category():
    """API endpoint to create a new budget category"""
    try:
        data = request.get_json()
        name = data.get('name')
        main_category = data.get('main_category')
        icon = data.get('icon', 'bx-category')
        
        if not name or not main_category:
            return jsonify({'success': False, 'error': 'Name and main category required'}), 400
        
        category = BudgetCategory(
            name=name,
            main_category=main_category,
            icon=icon,
            plan_id=current_user.active_plan.id
        )
        
        db.session.add(category)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'category_id': category.id,
            'name': category.name,
            'main_category': category.main_category
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@views.route('/api/transactions', methods=['GET'])
@login_required
def get_transactions():
    """API endpoint to get all transactions for the current user"""
    try:
        transactions = db.session.query(
            Transaction.id,
            Transaction.description,
            Transaction.amount,
            Transaction.created_date,
            BudgetCategory.name.label('category_name'),
            Payee.name.label('payee_name')
        ).join(
            BudgetCategory, Transaction.category_id == BudgetCategory.id
        ).outerjoin(
            Payee, Transaction.payee_id == Payee.id
        ).filter(
            Transaction.plan_id == current_user.active_plan.id
        ).order_by(Transaction.created_date.desc()).all()
        
        transaction_list = []
        for t in transactions:
            transaction_list.append({
                'id': t.id,
                'description': t.description,
                'amount': t.amount,
                'created_at': t.created_date.isoformat(),
                'category_name': t.category_name,
                'payee_name': t.payee_name
            })
        
        return jsonify({
            'success': True,
            'transactions': transaction_list
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@views.route('/api/transactions/<int:transaction_id>', methods=['DELETE'])
@login_required
def delete_transaction(transaction_id):
    """API endpoint to delete a transaction"""
    try:
        transaction = Transaction.query.filter_by(
            id=transaction_id,
            plan_id=current_user.active_plan.id
        ).first()
        
        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        
        category_id = transaction.category_id
        
        # Delete the transaction
        db.session.delete(transaction)
        db.session.commit()
        
        # Update category spent amount
        category = BudgetCategory.query.get(category_id)
        if category:
            spent = db.session.query(func.sum(Transaction.amount)).filter_by(
                category_id=category.id
            ).scalar() or 0
            category.spent_amount = abs(spent)
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Transaction deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@views.route('/open-plan')
@login_required
def open_plan():
    """Display a list of all the user's plans."""
    return render_template('open_plan.html', plans=current_user.plans)


# --------------------------- Payees API ---------------------------
@views.route('/api/payees', methods=['GET', 'POST'])
@login_required
def manage_payees():
    """GET: list payees; POST: create new payee"""
    plan = current_user.active_plan
    if not plan:
        return jsonify({'success': False, 'error': 'No active plan'}), 400

    if request.method == 'GET':
        payees = [{'id': p.id, 'name': p.name} for p in plan.payees]
        return jsonify({'success': True, 'payees': payees})

    # POST
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Name required'}), 400

    if any(p.name.lower() == name.lower() for p in plan.payees):
        return jsonify({'success': False, 'error': 'Payee already exists'}), 400

    payee = Payee(name=name, plan_id=plan.id)
    db.session.add(payee)
    db.session.commit()
    return jsonify({'success': True, 'payee': {'id': payee.id, 'name': payee.name}})

@views.route('/api/payees/<int:payee_id>', methods=['DELETE'])
@login_required
def delete_payee(payee_id):
    plan = current_user.active_plan
    payee = Payee.query.filter_by(id=payee_id, plan_id=plan.id).first()
    if not payee:
        return jsonify({'success': False, 'error': 'Payee not found'}), 404
    db.session.delete(payee)
    db.session.commit()
    return jsonify({'success': True})


# -------------------------- Categories API ---------------------------
@views.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    """Get all categories for the current user's active plan"""
    plan = current_user.active_plan
    if not plan:
        return jsonify({'success': False, 'error': 'No active plan'}), 400

    categories = BudgetCategory.query.filter_by(plan_id=plan.id).all()
    category_list = [{
        'id': cat.id,
        'name': cat.name,
        'main_category': cat.main_category,
        'icon': cat.icon
    } for cat in categories]
    
    return jsonify({'success': True, 'categories': category_list})


# -------------------------- Transaction Payee Update ---------------------------
@views.route('/api/transactions/<int:tx_id>/set-payee', methods=['POST'])
@login_required
def set_transaction_payee(tx_id):
    """Set or clear payee for a transaction"""
    data = request.get_json()
    payee_id = data.get('payee_id')  # may be null to clear

    tx = Transaction.query.filter_by(id=tx_id, plan_id=current_user.active_plan.id).first()
    if not tx:
        return jsonify({'success': False, 'error': 'Transaction not found'}), 404

    if payee_id:
        payee = Payee.query.filter_by(id=payee_id, plan_id=current_user.active_plan.id).first()
        if not payee:
            return jsonify({'success': False, 'error': 'Payee not found'}), 404
        tx.payee_id = payee_id
    else:
        tx.payee_id = None

    db.session.commit()
    return jsonify({'success': True})


# --------------------------- Transactions Page ---------------------------
@views.route('/transactions/<int:year>/<int:month>')
@views.route('/transactions')
@login_required
def transactions(year=None, month=None):
    """Display the transactions summary page (placeholder until table implemented)."""
    # Ensure the user has an active plan
    plan = current_user.active_plan
    if not plan:
        flash("No active plan found.", 'error')
        return redirect(url_for('views.home'))

    # Calculate Monthly Allowance (income)
    monthly_allowance = plan.monthly_income or 0.0

    # Determine the date to display
    if year is None or month is None:
        today = datetime.now()
        year, month = today.year, today.month
    
    try:
        display_date = datetime(year, month, 1)
    except ValueError:
        # Handle invalid month/year in URL
        today = datetime.now()
        year, month = today.year, today.month
        display_date = datetime(year, month, 1)

    display_month_str = display_date.strftime('%B')
    
    # Calculate month boundaries
    start_of_month = datetime(year, month, 1)
    end_of_month = start_of_month + timedelta(days=32)
    end_of_month = datetime(end_of_month.year, end_of_month.month, 1)

    # Sum all transaction amounts for this plan in the current month (expenses are stored as negative)
    activity_sum = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.plan_id == plan.id,
        Transaction.transaction_date >= start_of_month,
        Transaction.transaction_date < end_of_month
    ).scalar() or 0.0

    activity_total = abs(activity_sum)  # Convert to positive value for display

    available = monthly_allowance - activity_total
    
    # Navigation variables
    from dateutil.relativedelta import relativedelta
    prev_month_date = display_date - relativedelta(months=1)
    next_month_date = display_date + relativedelta(months=1)
    
    # Check if navigation should be enabled
    user_join_date = current_user.date_created or datetime.now()
    is_first_month = (display_date.year == user_join_date.year and display_date.month == user_join_date.month)
    can_go_prev = not is_first_month
    can_go_next = True  # Allow future months for transaction entry

    return render_template(
        'transactions.html',
        monthly_allowance=monthly_allowance,
        activity_total=activity_total,
        available=available,
        transactions=db.session.query(Transaction).filter(
            Transaction.plan_id==plan.id,
            Transaction.transaction_date>=start_of_month,
            Transaction.transaction_date<end_of_month
        ).order_by(Transaction.transaction_date.desc()).all(),
        payees=[{'id': p.id, 'name': p.name} for p in plan.payees],
        # Month navigation data
        current_month=display_month_str,
        current_month_num=month,
        current_year=year,
        prev_month=prev_month_date.month,
        prev_year=prev_month_date.year,
        next_month=next_month_date.month,
        next_year=next_month_date.year,
        can_go_prev=can_go_prev,
        can_go_next=can_go_next
    )


# --------------------------- Reflect Page ---------------------------
@views.route('/reflect/<int:year>/<int:month>')
@views.route('/reflect')
@login_required
def reflect(year=None, month=None):
    plan = current_user.active_plan
    if not plan:
        flash("No active plan found.", 'error')
        return redirect(url_for('views.home'))
    
    # Determine the date to display
    if year is None or month is None:
        today = datetime.now()
        year, month = today.year, today.month
    
    try:
        display_date = datetime(year, month, 1)
    except ValueError:
        # Handle invalid month/year in URL
        today = datetime.now()
        year, month = today.year, today.month
        display_date = datetime(year, month, 1)

    display_month_str = display_date.strftime('%B')
    
    # Calculate month boundaries for filtering transactions
    start_of_month = datetime(year, month, 1)
    end_of_month = start_of_month + timedelta(days=32)
    end_of_month = datetime(end_of_month.year, end_of_month.month, 1)
    
    # Get transactions for the selected month
    transactions = db.session.query(Transaction).filter(
        Transaction.plan_id == plan.id,
        Transaction.transaction_date >= start_of_month,
        Transaction.transaction_date < end_of_month
    ).order_by(Transaction.transaction_date.desc()).all()
    
    # Get unique months with data
    months_with_data = set()
    for tx in transactions:
        month_key = tx.transaction_date.strftime('%Y-%m')
        months_with_data.add(month_key)
    
    sorted_months = sorted(list(months_with_data), reverse=True)
    month_options = []
    for month_key in sorted_months:
        year, month = month_key.split('-')
        month_name = datetime(int(year), int(month), 1).strftime('%b %Y')
        month_options.append({'value': month_key, 'display': month_name})
    
    current_month = sorted_months[0] if sorted_months else None
    
    # Calculate spending data and real statistics
    spending_data = []
    grouped_spending = {'needs': [], 'wants': [], 'investments': []}
    total_spending = 0
    summary_stats = {
        'avg_monthly': 0,
        'avg_daily': 0,
        'most_frequent_category': 'None',
        'largest_transaction': 0
    }
    
    if current_month:
        year, month = current_month.split('-')
        start_of_month = datetime(int(year), int(month), 1)
        if int(month) == 12:
            end_of_month = datetime(int(year) + 1, 1, 1)
        else:
            end_of_month = datetime(int(year), int(month) + 1, 1)
        
        month_transactions = db.session.query(Transaction).filter(
            Transaction.plan_id == plan.id,
            Transaction.transaction_date >= start_of_month,
            Transaction.transaction_date < end_of_month
        ).all()
        
        category_totals = {}
        main_category_totals = {'needs': 0, 'wants': 0, 'investments': 0}
        
        for tx in month_transactions:
            category_name = tx.category.name
            main_cat = tx.category.main_category
            amount = abs(tx.amount)
            
            if category_name not in category_totals:
                category_totals[category_name] = {
                    'amount': 0, 
                    'main_category': main_cat
                }
            category_totals[category_name]['amount'] += amount
            main_category_totals[main_cat] += amount
            total_spending += amount
        
        spending_data = [{
            'category': cat, 
            'amount': data['amount']
        } for cat, data in category_totals.items()]
        
        # Colors for subcategories
        colors = [
            '#6f42c1', '#20c997', '#fd7e14', '#e83e8c', '#6610f2',
            '#6f9bd1', '#28a745', '#ffc107', '#dc3545', '#17a2b8',
            '#f8f9fa', '#6c757d', '#343a40', '#007bff', '#6f42c1'
        ]
        
        # Group spending by main category
        color_index = 0
        for cat, data in category_totals.items():
            main_cat = data['main_category']
            percentage = (data['amount'] / total_spending * 100) if total_spending > 0 else 0
            
            grouped_spending[main_cat].append({
                'name': cat,
                'amount': data['amount'],
                'percentage': round(percentage, 1),
                'color': colors[color_index % len(colors)]
            })
            color_index += 1
        
        # Calculate real summary statistics
        months_used = len(sorted_months)
        summary_stats['avg_monthly'] = total_spending / months_used if months_used > 0 else 0
        summary_stats['avg_daily'] = summary_stats['avg_monthly'] / 30
        
        # Most frequent category (by spending amount)
        if main_category_totals:
            most_frequent = max(main_category_totals, key=main_category_totals.get)
            summary_stats['most_frequent_category'] = most_frequent.title()
        
        # Largest transaction
        all_transactions = db.session.query(Transaction).filter(
            Transaction.plan_id == plan.id
        ).all()
        if all_transactions:
            summary_stats['largest_transaction'] = max(abs(tx.amount) for tx in all_transactions)
        
        # Add trend direction
        summary_stats['trend_direction'] = '↗ Increasing' if total_spending > 1500 else '↘ Decreasing'
        summary_stats['peak_day_amount'] = max(summary_stats['avg_daily'] * 2.5, 50)
    
    # Calculate monthly breakdown for trends
    monthly_breakdown = []
    daily_spending_data = []
    daily_spending_by_category = {'needs': [], 'wants': [], 'investments': []}
    
    if sorted_months:
        month_totals = {}
        for month_key in sorted_months:
            year, month = month_key.split('-')
            start_of_month = datetime(int(year), int(month), 1)
            if int(month) == 12:
                end_of_month = datetime(int(year) + 1, 1, 1)
            else:
                end_of_month = datetime(int(year), int(month) + 1, 1)
            
            month_transactions = db.session.query(Transaction).filter(
                Transaction.plan_id == plan.id,
                Transaction.transaction_date >= start_of_month,
                Transaction.transaction_date < end_of_month
            ).all()
            
            month_total = sum(abs(tx.amount) for tx in month_transactions)
            month_name = datetime(int(year), int(month), 1).strftime('%b %Y')
            month_totals[month_key] = {'amount': month_total, 'name': month_name}
        
        # Calculate percentages
        total_all_months = sum(data['amount'] for data in month_totals.values())
        for month_key, data in month_totals.items():
            percentage = (data['amount'] / total_all_months * 100) if total_all_months > 0 else 0
            monthly_breakdown.append({
                'month_name': data['name'],
                'amount': data['amount'],
                'percentage': round(percentage, 1)
            })
    
    # Calculate real daily spending data for current month
    if current_month:
        year, month = current_month.split('-')
        start_of_month = datetime(int(year), int(month), 1)
        if int(month) == 12:
            end_of_month = datetime(int(year) + 1, 1, 1)
        else:
            end_of_month = datetime(int(year), int(month) + 1, 1)
        
        # Get all transactions for the current month
        current_month_transactions = db.session.query(Transaction).filter(
            Transaction.plan_id == plan.id,
            Transaction.transaction_date >= start_of_month,
            Transaction.transaction_date < end_of_month
        ).all()
        
        # Group transactions by day
        daily_totals = {}
        for tx in current_month_transactions:
            day_key = tx.transaction_date.day
            if day_key not in daily_totals:
                daily_totals[day_key] = 0
            daily_totals[day_key] += abs(tx.amount)
        
        # Create daily spending data array
        import calendar
        days_in_month = calendar.monthrange(int(year), int(month))[1]
        for day in range(1, days_in_month + 1):
            daily_spending_data.append({
                'day': day,
                'amount': daily_totals.get(day, 0)
            })
        
        # Create category-filtered daily spending data
        daily_spending_by_category = {'needs': [], 'wants': [], 'investments': []}
        
        for category in ['needs', 'wants', 'investments']:
            category_daily_totals = {}
            
            # Filter transactions by category
            category_transactions = [tx for tx in current_month_transactions 
                                   if tx.category.main_category == category]
            
            # Group by day
            for tx in category_transactions:
                day_key = tx.transaction_date.day
                if day_key not in category_daily_totals:
                    category_daily_totals[day_key] = 0
                category_daily_totals[day_key] += abs(tx.amount)
            
            # Create daily array for this category
            for day in range(1, days_in_month + 1):
                daily_spending_by_category[category].append({
                    'day': day,
                    'amount': category_daily_totals.get(day, 0)
                })
    
    # Navigation variables
    from dateutil.relativedelta import relativedelta
    prev_month_date = display_date - relativedelta(months=1)
    next_month_date = display_date + relativedelta(months=1)
    
    # Check if navigation should be enabled
    user_join_date = current_user.date_created or datetime.now()
    is_first_month = (display_date.year == user_join_date.year and display_date.month == user_join_date.month)
    can_go_prev = not is_first_month
    can_go_next = True  # Allow future months for analysis
    
    return render_template('reflect.html', 
                         month_options=month_options,
                         current_month=current_month,
                         spending_data=spending_data,
                         grouped_spending=grouped_spending,
                         total_spending=total_spending,
                         summary_stats=summary_stats,
                         monthly_breakdown=monthly_breakdown,
                         daily_spending_data=daily_spending_data,
                         daily_spending_by_category=daily_spending_by_category,
                         # Month navigation data
                         current_month_display=display_month_str,
                         current_month_num=month,
                         current_year=year,
                         prev_month=prev_month_date.month,
                         prev_year=prev_month_date.year,
                         next_month=next_month_date.month,
                         next_year=next_month_date.year,
                         can_go_prev=can_go_prev,
                         can_go_next=can_go_next)


@views.route('/receipt_ai')
@login_required
def receipt_ai():
    """Receipt AI page for uploading and processing receipt images"""
    # Get user's categories for the dropdown
    plan = current_user.active_plan
    categories = []
    ai_transactions = []
    
    if plan:
        categories = BudgetCategory.query.filter_by(plan_id=plan.id).all()
        
        # Get recent AI-created transactions (those with 'Receipt AI:' in description)
        ai_transactions = Transaction.query.filter(
            Transaction.plan_id == plan.id,
            Transaction.description.like('Receipt AI:%')
        ).order_by(Transaction.created_date.desc()).limit(10).all()
    
    return render_template('receipt_ai.html', categories=categories, ai_transactions=ai_transactions)


@views.route('/api/receipt_ai/create_transaction', methods=['POST'])
@login_required
def create_receipt_transaction():
    """Create a transaction from Receipt AI extracted data"""
    try:
        data = request.get_json()
        
        # Handle both old format (merchant_name) and new format (vendor)
        vendor_name = data.get('vendor', data.get('merchant_name', '')).strip()
        amount = float(data.get('amount', 0))
        date_str = data.get('date', '')
        category_id = int(data.get('category_id', 0))
        payee_id = data.get('payee_id')  # May be None for manual entries
        
        if not vendor_name or amount <= 0 or not date_str or not category_id:
            return jsonify({'success': False, 'message': 'All fields are required'})
        
        print(f"DEBUG: Creating transaction - Vendor: {vendor_name}, Amount: {amount}, Category ID: {category_id}, Payee ID: {payee_id}")
        
        # Parse date
        try:
            transaction_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid date format'})
        
        # Get category
        category = BudgetCategory.query.filter_by(
            id=category_id, 
            plan_id=current_user.active_plan.id
        ).first()
        
        if not category:
            return jsonify({'success': False, 'message': 'Invalid category'})
        
        # Validate budget limit using helper function
        is_valid, error_message, validation_data = validate_budget_limit(category, amount, transaction_date)
        
        if not is_valid:
            return jsonify({
                'success': False, 
                'message': f'Receipt transaction exceeds budget limit: {error_message}',
                **validation_data
            })
        
        # Handle payee - use provided payee_id or create/find payee
        if payee_id:
            # Use the payee_id from AI analysis
            payee = Payee.query.filter_by(
                id=payee_id,
                plan_id=current_user.active_plan.id
            ).first()
            
            if not payee:
                return jsonify({'success': False, 'message': 'Invalid payee ID'})
                
        else:
            # Fallback: create or find payee by name (for manual entries)
            payee = Payee.query.filter_by(
                name=vendor_name,
                plan_id=current_user.active_plan.id
            ).first()
            
            if not payee:
                payee = Payee(
                    name=vendor_name,
                    plan_id=current_user.active_plan.id
                )
                db.session.add(payee)
                db.session.flush()  # Get the payee ID
        
        # Create transaction
        new_transaction = Transaction(
            amount=-abs(amount),  # Negative for expense
            description=f'Receipt AI: {vendor_name}',
            transaction_date=transaction_date,
            category_id=category_id,
            payee_id=payee.id,
            plan_id=current_user.active_plan.id
        )
        
        db.session.add(new_transaction)
        
        # Update category spent amount accurately
        spent = db.session.query(func.sum(func.abs(Transaction.amount))).filter_by(
            category_id=category.id
        ).scalar() or 0
        category.spent_amount = spent
        
        db.session.commit()
        
        print(f"DEBUG: Receipt transaction created successfully - ID: {new_transaction.id}")
        
        flash(f'Receipt transaction added successfully! ฿{amount:.2f} spent at {vendor_name} in "{category.name}" category', 'success')
        
        return jsonify({
            'success': True, 
            'message': f'Receipt transaction created: ฿{amount:.2f} at {vendor_name}',
            'transaction_id': new_transaction.id,
            'category_name': f'{category.main_category.title()} - {category.name}',
            'category_spent': category.spent_amount,
            'category_available': category.assigned_amount - category.spent_amount
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: Error creating transaction: {e}")
        return jsonify({'success': False, 'message': f'Error creating transaction: {str(e)}'})


@views.route('/api/receipt_ai/process_image', methods=['POST'])
@login_required
def process_receipt_image():
    """Process uploaded receipt image with Smart AI extraction"""
    try:
        print("DEBUG: Starting receipt image processing...")
        data = request.get_json()
        image_data = data.get('image_data', '')
        
        if not image_data:
            return jsonify({'success': False, 'message': 'No image data provided'})
        
        print(f"DEBUG: Image data length: {len(image_data)} characters")
        
        # Analyze the receipt image for real data extraction with OpenAI Vision API
        parsed_data = analyze_receipt_image(image_data)
        
        print(f"DEBUG: AI analysis completed successfully: {parsed_data}")
        
        # Handle both old 'merchant' and new 'vendor' field names
        vendor_name = parsed_data.get('vendor', parsed_data.get('merchant', 'Unknown Vendor'))
        
        return jsonify({
            'success': True,
            'extracted_text': f'Smart AI analyzed receipt: {vendor_name}',
            'parsed_data': parsed_data
        })
            
    except Exception as e:
        print(f"DEBUG: Error in process_receipt_image: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Error processing image: {str(e)}'})


def analyze_receipt_image(image_data):
    """Analyze receipt image using OpenAI Vision API to extract real merchant, amount, and date"""
    
    try:
        # Initialize OpenAI client with API key from environment
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        # Extract base64 image data and determine image format
        if 'data:image/' in image_data and 'base64,' in image_data:
            # Extract the image format (e.g., 'jpeg', 'png')
            format_part = image_data.split('data:image/')[1].split(';base64,')[0]
            base64_image = image_data.split('base64,')[1]
            
            print(f"DEBUG: Detected image format: {format_part}")
            print(f"DEBUG: Base64 data length: {len(base64_image)}")
            print(f"DEBUG: First 50 chars of base64: {base64_image[:50]}")
            
            # Ensure format is supported by OpenAI
            supported_formats = ['png', 'jpeg', 'jpg', 'gif', 'webp']
            if format_part.lower() not in supported_formats:
                print(f"DEBUG: Unsupported format {format_part}, defaulting to jpeg")
                format_part = 'jpeg'  # Default to jpeg if unsupported
            else:
                print(f"DEBUG: Format {format_part} is supported")
                
        else:
            print(f"DEBUG: No proper data URL format detected, using defaults")
            print(f"DEBUG: Image data preview: {image_data[:100]}")
            base64_image = image_data
            format_part = 'jpeg'  # Default format
            
        print(f"DEBUG: Final format being sent to OpenAI: {format_part}")
        
        # Convert image to JPEG if it's in an unsupported format or corrupted
        try:
            # Decode base64 to check actual image format
            image_bytes = base64.b64decode(base64_image)
            print(f"DEBUG: Decoded image bytes length: {len(image_bytes)}")
            
            # Check for HEIC/HEIF format signatures
            is_heic = False
            if len(image_bytes) > 20:
                # Check for HEIC/HEIF signatures
                if (b'ftyp' in image_bytes[:20] and 
                    (b'heic' in image_bytes[:30] or b'heix' in image_bytes[:30] or 
                     b'mif1' in image_bytes[:30] or b'msf1' in image_bytes[:30])):
                    is_heic = True
                    print("DEBUG: Detected HEIC/HEIF format based on file signature")
            
            # Always try to convert to JPEG for maximum compatibility
            if is_heic or format_part.lower() != 'jpeg':
                print(f"DEBUG: Converting {'HEIC' if is_heic else format_part} to JPEG for OpenAI compatibility")
                converted_image = convert_image_to_jpeg(image_bytes)
                
                if converted_image != image_bytes:  # Conversion was successful
                    base64_image = base64.b64encode(converted_image).decode('utf-8')
                    format_part = 'jpeg'
                    print(f"DEBUG: Successfully converted to JPEG, new data length: {len(base64_image)}")
                else:
                    print("DEBUG: Conversion failed, using original data")
                
        except Exception as e:
            print(f"DEBUG: Image conversion failed: {e}, proceeding with original")
        
        # Get existing subcategories for intelligent matching
        existing_subcategories = get_existing_subcategories_for_ai(current_user.active_plan_id)
        
        # Create a sophisticated prompt for vendor and subcategory analysis
        prompt = f"""
        You are an expert receipt analyzer and financial categorization specialist. Analyze this receipt image and extract the following information:
        
        1. **Vendor Name**: Extract the ACTUAL VENDOR/BUSINESS name, not the mall, building, or organization. For example:
           - If it's "Starbucks at Central World", extract "Starbucks"
           - If it's "KFC Terminal 21", extract "KFC"
           - If it's "Krua Boon Vegetarian Restaurant", extract "Krua Boon"
           - Focus on the brand/business, not the location
        
        2. **Total Amount**: The final total amount paid (look for "Total", "Amount Due", or similar)
        
        3. **Date**: The transaction date (format as YYYY-MM-DD)
        
        4. **Main Category**: Determine if this expense is:
           - "Needs": Essential expenses (groceries, utilities, transportation, medical, rent)
           - "Wants": Non-essential expenses (dining out, entertainment, shopping, coffee)
           - "Investments": Investment-related expenses (rare, usually financial services)
        
        5. **Subcategory**: Based on the vendor and expense type, suggest a specific subcategory. 
           EXISTING SUBCATEGORIES in the user's budget:
           {existing_subcategories}
           
           - If a matching subcategory exists, use it EXACTLY as shown
           - If no match exists, suggest a new specific subcategory name (e.g., "Thai Food", "Coffee Shops", "Groceries")
           - Make subcategories specific but not too narrow ("Restaurants" not "Thai Vegetarian Restaurants")
        
        CRITICAL INSTRUCTIONS:
        - Extract the VENDOR/BRAND name, not the mall or location
        - Look for the TOTAL amount, not subtotals
        - Match existing subcategories when possible
        - Suggest new subcategories that are specific but reusable
        - Thai baht currency should be included
        
        Respond ONLY with a JSON object in this exact format:
        {{
            "vendor": "Actual vendor/brand name",
            "amount": 123.45,
            "date": "2024-07-20",
            "main_category": "Wants",
            "subcategory": "Thai Food",
            "subcategory_exists": true,
            "confidence": "high"
        }}
        """
        
        # Call OpenAI Vision API
        print(f"DEBUG: About to call OpenAI Vision API with image format: {format_part}")
        print(f"DEBUG: Base64 image length: {len(base64_image)} characters")
        print(f"DEBUG: Prompt length: {len(prompt)} characters")
        
        try:
            import httpx
            
            # Create client with timeout
            client = OpenAI(
                api_key=os.getenv('OPENAI_API_KEY'),
                timeout=httpx.Timeout(60.0, read=60.0, write=10.0, connect=5.0)
            )
            
            response = client.chat.completions.create(
                model="gpt-4o",  # Use GPT-4 Vision model
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{format_part};base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=500,
                temperature=0.1  # Low temperature for consistent, accurate results
            )
            print(f"DEBUG: OpenAI API call successful")
            
        except Exception as openai_error:
            print(f"DEBUG: OpenAI API call failed: {type(openai_error).__name__}: {openai_error}")
            raise Exception(f"OpenAI Vision API error: {str(openai_error)}")
        
        # Parse the AI response
        ai_response = response.choices[0].message.content.strip()
        
        # Extract JSON from the response
        try:
            print(f"DEBUG: Raw AI response text: {ai_response[:500]}...")  # Show first 500 chars
            
            # Find JSON in the response (in case there's extra text)
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                json_text = json_match.group()
                print(f"DEBUG: Extracted JSON: {json_text}")
                ai_data = json.loads(json_text)
            else:
                print(f"DEBUG: No JSON pattern found, trying to parse entire response")
                ai_data = json.loads(ai_response)
            
            # Validate and extract data from AI response (handle both merchant and vendor field names)
            vendor = ai_data.get('vendor', ai_data.get('merchant', 'Unknown Vendor'))
            amount = float(ai_data.get('amount', 0.0))
            date = ai_data.get('date', datetime.now().strftime('%Y-%m-%d'))
            main_category = ai_data.get('main_category', ai_data.get('business_type', 'Wants'))
            subcategory = ai_data.get('subcategory', 'General')
            subcategory_exists = ai_data.get('subcategory_exists', False)
            confidence = ai_data.get('confidence', 'medium')
            
            print(f"DEBUG: Raw AI response: {ai_data}")
            
            print(f"DEBUG: AI extracted - Vendor: {vendor}, Amount: {amount}, Category: {main_category}, Subcategory: {subcategory}")
            
            # Process subcategory: find existing or create new
            category_id = process_subcategory(current_user.active_plan_id, main_category, subcategory, subcategory_exists)
            
            # Process payee: find existing or create new
            payee_id = process_payee(current_user.active_plan_id, vendor)
            
            result = {
                'vendor': vendor,
                'amount': amount,
                'date': date,
                'main_category': main_category,
                'subcategory': subcategory,
                'category_id': category_id,
                'payee_id': payee_id,
                'confidence': confidence
            }
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"Error parsing AI response JSON: {e}")
            print(f"AI Response: {ai_response}")
            # Fallback to basic extraction
            return fallback_receipt_analysis()
            
    except Exception as e:
        print(f"Error with OpenAI Vision API: {e}")
        # Fallback to basic extraction
        return fallback_receipt_analysis()


def determine_smart_category_from_business_type(merchant, business_type):
    """Intelligently determine the most appropriate budget category based on business type"""
    
    # Category mapping based on business type from OpenAI analysis
    category_mappings = {
        'restaurant': 'Wants',        # Restaurants are typically Wants
        'coffee_shop': 'Wants',       # Coffee shops are Wants
        'convenience_store': 'Needs', # Basic necessities could be Needs
        'grocery': 'Needs',           # Groceries are Needs
        'retail': 'Wants',            # Shopping/retail is typically Wants
        'pharmacy': 'Needs',          # Medical/pharmacy is a Need
        'transport': 'Needs',         # Transportation is a Need
        'entertainment': 'Wants',     # Entertainment is a Want
        'other': 'Wants'              # Default to Wants
    }
    
    # Special cases based on merchant name for more accuracy
    merchant_lower = merchant.lower()
    
    # Medical/health related - always Needs
    if any(word in merchant_lower for word in ['hospital', 'clinic', 'pharmacy', 'medical', 'doctor']):
        return 'Needs'
    
    # Transportation - always Needs
    elif any(word in merchant_lower for word in ['bts', 'mrt', 'taxi', 'grab', 'transport', 'bus', 'train']):
        return 'Needs'
    
    # Supermarkets/groceries - Needs
    elif any(word in merchant_lower for word in ['tops', 'big c', 'lotus', 'makro', 'supermarket', 'market']):
        return 'Needs'
    
    # Utilities and essential services - Needs
    elif any(word in merchant_lower for word in ['electric', 'water', 'gas', 'internet', 'phone', 'utility']):
        return 'Needs'
    
    # Use business type mapping
    return category_mappings.get(business_type, 'Wants')


def convert_image_to_jpeg(image_bytes):
    """Convert image bytes to JPEG format for OpenAI compatibility"""
    try:
        print(f"DEBUG: Attempting to convert image, input size: {len(image_bytes)} bytes")
        
        # Try to open image with PIL (now supports HEIC with pillow-heif)
        image_buffer = BytesIO(image_bytes)
        image = Image.open(image_buffer)
        
        print(f"DEBUG: Successfully opened image: {image.format}, {image.mode}, {image.size}")
        
        # Convert to RGB if necessary (for PNG with transparency, HEIC, etc.)
        if image.mode in ('RGBA', 'LA', 'P'):
            print(f"DEBUG: Converting from {image.mode} to RGB with white background")
            # Create a white background
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
            image = background
        elif image.mode != 'RGB':
            print(f"DEBUG: Converting from {image.mode} to RGB")
            image = image.convert('RGB')
        
        # Save as JPEG
        output_buffer = BytesIO()
        image.save(output_buffer, format='JPEG', quality=85, optimize=True)
        jpeg_bytes = output_buffer.getvalue()
        
        print(f"DEBUG: Successfully converted to JPEG, output size: {len(jpeg_bytes)} bytes")
        return jpeg_bytes
        
    except Exception as e:
        print(f"DEBUG: Error converting image: {type(e).__name__}: {e}")
        print(f"DEBUG: Returning original bytes of size: {len(image_bytes)}")
        # Return original bytes if conversion fails
        return image_bytes


def get_existing_subcategories_for_ai(plan_id):
    """Get existing subcategories organized by main category for AI prompt"""
    try:
        from .models import BudgetCategory
        
        categories = BudgetCategory.query.filter_by(plan_id=plan_id).all()
        
        organized = {
            'Needs': [],
            'Wants': [],
            'Investments': []
        }
        
        for category in categories:
            main_cat = category.main_category.title()  # Convert to title case
            if main_cat in organized:
                organized[main_cat].append(category.name)
        
        # Format for AI prompt
        formatted = []
        for main_cat, subcats in organized.items():
            if subcats:
                formatted.append(f"{main_cat}: {', '.join(subcats)}")
        
        return '\n           '.join(formatted) if formatted else "No existing subcategories"
        
    except Exception as e:
        print(f"Error getting subcategories: {e}")
        return "No existing subcategories"


def process_subcategory(plan_id, main_category, subcategory_name, subcategory_exists):
    """Find existing subcategory or create new one, return category_id"""
    try:
        from .models import BudgetCategory
        
        # Normalize main category
        main_category = main_category.lower()
        
        print(f"DEBUG: Processing subcategory - Main: {main_category}, Sub: {subcategory_name}, Exists: {subcategory_exists}")
        
        # First, try to find existing subcategory
        existing_category = BudgetCategory.query.filter_by(
            plan_id=plan_id,
            main_category=main_category,
            name=subcategory_name
        ).first()
        
        if existing_category:
            print(f"DEBUG: Found existing subcategory: {existing_category.name} (ID: {existing_category.id})")
            return existing_category.id
        
        # If not found, create new subcategory
        print(f"DEBUG: Creating new subcategory: {subcategory_name} in {main_category}")
        
        new_category = BudgetCategory(
            name=subcategory_name,
            main_category=main_category,
            plan_id=plan_id,
            assigned_amount=0.0,
            spent_amount=0.0
        )
        
        db.session.add(new_category)
        db.session.commit()
        
        print(f"DEBUG: Created new subcategory: {new_category.name} (ID: {new_category.id})")
        return new_category.id
        
    except Exception as e:
        print(f"DEBUG: Error processing subcategory: {e}")
        # Fallback: try to find any category in the main category
        try:
            fallback_category = BudgetCategory.query.filter_by(
                plan_id=plan_id,
                main_category=main_category.lower()
            ).first()
            if fallback_category:
                return fallback_category.id
        except:
            pass
        return None


def process_payee(plan_id, vendor_name):
    """Find existing payee or create new one, return payee_id"""
    try:
        from .models import Payee
        
        print(f"DEBUG: Processing payee: {vendor_name}")
        
        # Try to find existing payee (case-insensitive)
        existing_payee = Payee.query.filter(
            Payee.plan_id == plan_id,
            func.lower(Payee.name) == func.lower(vendor_name)
        ).first()
        
        if existing_payee:
            print(f"DEBUG: Found existing payee: {existing_payee.name} (ID: {existing_payee.id})")
            return existing_payee.id
        
        # Create new payee
        print(f"DEBUG: Creating new payee: {vendor_name}")
        
        new_payee = Payee(
            name=vendor_name,
            plan_id=plan_id
        )
        
        db.session.add(new_payee)
        db.session.commit()
        
        print(f"DEBUG: Created new payee: {new_payee.name} (ID: {new_payee.id})")
        return new_payee.id
        
    except Exception as e:
        print(f"DEBUG: Error processing payee: {e}")
        return None


def fallback_receipt_analysis():
    """Fallback analysis when OpenAI Vision API fails"""
    
    # Simple fallback with reasonable defaults
    result = {
        'vendor': 'Unknown Vendor',
        'amount': 100.00,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'main_category': 'Wants',
        'subcategory': 'General',
        'subcategory_exists': False,
        'confidence': 'low'
    }
    
    return result


@views.route('/add_category', methods=['POST'])
@login_required
def add_category():
    """Add a new category to the current plan with comprehensive validation."""
    plan = current_user.active_plan
    if not plan:
        flash("No active plan found.", 'error')
        return redirect(url_for('views.home'))
    
    main_category = request.form.get('main_category')
    category_name = request.form.get('category_name', '').strip()
    
    # Enhanced validation
    if not main_category or not category_name:
        flash("Please fill in all fields.", 'error')
        return redirect(url_for('views.home'))
    
    # Validate main category
    valid_main_categories = ['needs', 'wants', 'investments']
    if main_category not in valid_main_categories:
        flash(f"Invalid main category. Must be one of: {', '.join(valid_main_categories)}", 'error')
        return redirect(url_for('views.home'))
    
    # Validate category name length and characters
    if len(category_name) < 2:
        flash("Category name must be at least 2 characters long.", 'error')
        return redirect(url_for('views.home'))
    
    if len(category_name) > 50:
        flash("Category name must be less than 50 characters.", 'error')
        return redirect(url_for('views.home'))
    
    # Check if category already exists (case-insensitive)
    existing_category = BudgetCategory.query.filter(
        func.lower(BudgetCategory.name) == func.lower(category_name),
        BudgetCategory.main_category == main_category,
        BudgetCategory.plan_id == plan.id
    ).first()
    
    if existing_category:
        flash(f"Category '{category_name}' already exists in {main_category.title()}.", 'error')
        return redirect(url_for('views.home'))
    
    # Create new category with default values
    new_category = BudgetCategory(
        name=category_name,
        main_category=main_category,
        plan_id=plan.id,
        assigned_amount=0.0,  # Default to 0, user can assign later
        spent_amount=0.0
    )
    
    try:
        db.session.add(new_category)
        
        # Update plan preferences to include the new subcategory
        if plan.budget_pref and 'subcategories' in plan.budget_pref:
            # Map investments to savings for consistency
            pref_category = 'savings' if main_category == 'investments' else main_category
            
            if pref_category not in plan.budget_pref['subcategories']:
                plan.budget_pref['subcategories'][pref_category] = []
            
            if category_name not in plan.budget_pref['subcategories'][pref_category]:
                plan.budget_pref['subcategories'][pref_category].append(category_name)
                flag_modified(plan, 'budget_pref')
        
        db.session.commit()
        flash(f"Category '{category_name}' added successfully to {main_category.title()}! You can assign a budget amount in Plan Settings.", 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error adding category: {str(e)}", 'error')
    
    return redirect(url_for('views.home'))


@views.route('/switch-plan/<int:plan_id>')
@login_required
def switch_plan(plan_id):
    """Set the selected plan as the user's active plan."""
    plan = Plan.query.get(plan_id)
    if plan and plan.user_id == current_user.id:
        current_user.active_plan_id = plan.id
        db.session.commit()
        flash(f"Switched to plan '{plan.name}'.", 'success')
    else:
        flash("Could not find the requested plan.", 'error')
    return redirect(url_for('views.home'))

@views.route('/plan-settings', methods=['GET', 'POST'])
@login_required
def plan_settings():
    """Display and handle updates for the plan settings page."""
    plan = current_user.active_plan
    if not plan:
        flash("No active plan found.", 'error')
        return redirect(url_for('views.home'))

    if request.method == 'POST':
        # Ensure subcategories structure exists
        if 'subcategories' not in plan.budget_pref:
            plan.budget_pref['subcategories'] = {'needs': [], 'wants': [], 'savings': []}

        # Check which form was submitted
        if 'update_plan_name' in request.form:
            new_name = request.form.get('plan_name')
            if new_name:
                plan.name = new_name
                db.session.commit()
                flash("Plan name updated successfully!", 'success')
            else:
                flash("Plan name cannot be empty.", 'error')

        elif 'update_ratios' in request.form:
            try:
                # Get raw values and handle potential issues
                needs_raw = request.form.get('needs_ratio', '').strip()
                wants_raw = request.form.get('wants_ratio', '').strip()
                savings_raw = request.form.get('savings_ratio', '').strip()
                
                # Debug logging
                print(f"Debug - Raw form values: needs='{needs_raw}', wants='{wants_raw}', savings='{savings_raw}'")
                
                # Validate and convert to integers
                if not needs_raw or not wants_raw or not savings_raw:
                    flash("All ratio fields must have values.", 'error')
                    return redirect(url_for('views.plan_settings'))
                
                # Handle decimal values by converting to float first, then int
                needs = int(float(needs_raw))
                wants = int(float(wants_raw))
                savings = int(float(savings_raw))
                
                # Validate ranges
                if needs < 0 or wants < 0 or savings < 0:
                    flash("Ratio values cannot be negative.", 'error')
                elif needs > 100 or wants > 100 or savings > 100:
                    flash("Individual ratio values cannot exceed 100%.", 'error')
                elif needs + wants + savings == 100:
                    plan.budget_pref['ratios'] = {'needs': needs, 'wants': wants, 'savings': savings}
                    flag_modified(plan, 'budget_pref')
                    db.session.commit()
                    flash("Category ratios updated successfully!", 'success')
                else:
                    flash(f"Ratios must add up to 100%. Current total: {needs + wants + savings}%", 'error')
            except (ValueError, TypeError) as e:
                print(f"Debug - Exception in ratio conversion: {e}")
                flash("Invalid ratio value. Please enter whole numbers only.", 'error')



        elif 'add_subcategory' in request.form:
            category = request.form.get('category')
            new_subcat = request.form.get('subcategory_name', '').strip()
            if category and new_subcat:
                if new_subcat not in plan.budget_pref['subcategories'][category]:
                    plan.budget_pref['subcategories'][category].append(new_subcat)
                    flag_modified(plan, 'budget_pref')
                    db.session.commit()
                    flash(f"Added subcategory '{new_subcat}'.", 'success')
                else:
                    flash(f"Subcategory '{new_subcat}' already exists.", 'warning')
            else:
                flash("Subcategory name cannot be empty.", 'error')

        elif 'delete_subcategory' in request.form:
            category = request.form.get('category')
            subcat_to_delete = request.form.get('subcategory_name')
            if category and subcat_to_delete:
                if subcat_to_delete in plan.budget_pref['subcategories'][category]:
                    plan.budget_pref['subcategories'][category].remove(subcat_to_delete)
                    flag_modified(plan, 'budget_pref')
                    db.session.commit()
                    flash(f"Removed subcategory '{subcat_to_delete}'.", 'success')
        
        return redirect(url_for('views.plan_settings'))

    return render_template('plan_settings.html', plan=plan)

@views.route('/display-settings', methods=['GET', 'POST'])
@login_required
def display_settings():
    """Display and handle updates for display settings."""
    if request.method == 'POST':
        theme = request.form.get('theme')
        if theme in ['light', 'dark', 'system']:
            current_user.theme = theme
            db.session.commit()
            flash("Theme updated successfully!", 'success')
        else:
            flash('Invalid theme selected.','error')
        return redirect(url_for('views.display_settings'))
    
    return render_template('display_settings.html')

@views.route('/account-settings')
@login_required
def account_settings():
    """Renders the account settings page."""
    return render_template('account_settings.html')


@views.route('/disconnect-google', methods=['GET', 'POST'])
@login_required
def disconnect_google():
    """
    Forces a user to set a password before disconnecting their Google account
    to prevent them from being locked out.
    """
    if request.method == 'POST':
        password = request.form.get('password')

        if not password or len(password) < 7:
            flash('Password must be at least 7 characters long.', category='error')
            return redirect(url_for('views.disconnect_google'))

        # Update user's password
        current_user.password = generate_password_hash(password, method='pbkdf2:sha256')

        # Disconnect Google account by clearing the google_id
        if hasattr(current_user, 'google_id'):
            current_user.google_id = None
        
        db.session.commit()

        flash('Successfully set password and disconnected Google. You can now log in with your email and new password.', category='success')
        return redirect(url_for('views.account_settings'))

    return render_template('disconnect_google.html')

@views.route('/set-password', methods=['POST'])
@login_required
def set_password():
    """Sets or updates the user's password."""
    password = request.form.get('password')

    if not password or len(password) < 7:
        flash('Password must be at least 7 characters long.', category='error')
    else:
        current_user.password = generate_password_hash(password, method='pbkdf2:sha256')
        db.session.commit()
        flash('Password updated successfully!', category='success')

    return redirect(url_for('views.account_settings'))

@views.route('/update-budget-form', methods=['POST'])
@login_required
def update_budget_form():
    """Form-based budget update that uses flash messages"""
    category_id = request.form.get('category_id')
    new_amount = request.form.get('amount')
    
    # Get month and year from form, default to current month if not provided
    target_month = request.form.get('month')
    target_year = request.form.get('year')
    
    try:
        category_id = int(category_id)
        new_amount = float(new_amount)
        
        if target_month is None or target_year is None:
            current_date = datetime.now()
            target_month = int(target_month) if target_month else current_date.month
            target_year = int(target_year) if target_year else current_date.year
        else:
            target_month = int(target_month)
            target_year = int(target_year)
            
    except (ValueError, TypeError):
        flash('Invalid input values.', 'error')
        return redirect(url_for('views.home'))
    
    if new_amount < 0:
        flash('Assigned amount cannot be negative.', 'error')
        return redirect(url_for('views.home'))

    plan = current_user.active_plan
    if not plan:
        flash('No active plan found.', 'error')
        return redirect(url_for('views.home'))

    # Get the category to update
    category_to_update = BudgetCategory.query.filter_by(
        id=category_id, plan_id=plan.id
    ).first()
    
    if not category_to_update:
        flash('Category not found.', 'error')
        return redirect(url_for('views.home'))

    # Get the main category name
    main_cat_name = category_to_update.main_category.lower()
    
    # Get budget ratios and calculate limits
    budget_ratios = plan.budget_pref.get('ratios', {}) if plan.budget_pref else {}
    ratio_key = 'savings' if main_cat_name == 'investments' else main_cat_name
    category_ratio = budget_ratios.get(ratio_key, 0) / 100.0
    max_allowed = plan.monthly_income * category_ratio if plan.monthly_income else 0
    
    # Calculate current total for this main category (excluding the category being updated)
    current_total_others = 0
    current_category_amount = 0
    
    for c in plan.categories:
        if c.main_category.lower() == main_cat_name:
            mb = MonthlyBudget.query.filter_by(
                plan_id=plan.id, 
                category_id=c.id, 
                month=target_month, 
                year=target_year
            ).first()
            if mb:
                if c.id == category_id:
                    current_category_amount = mb.assigned_amount
                else:
                    current_total_others += mb.assigned_amount
    
    # Calculate how much budget is available
    # When updating, we get "credit" for the current assignment being replaced
    remaining_budget = max_allowed - current_total_others
    
    # Check if new amount would exceed the category's budget
    if new_amount > remaining_budget:
        # Calculate the net change (how much extra money is needed)
        net_change = new_amount - current_category_amount
        actual_available = remaining_budget - current_category_amount
        
        flash(
            f"Cannot assign ${new_amount:.2f}. Total assigned to "
            f"{main_cat_name.capitalize()} would be "
            f"${(current_total_others + new_amount):.2f}, exceeding the "
            f"budget limit of ${max_allowed:.2f}.",
            'error'
        )
        return redirect(url_for('views.home'))
    
    # Update the budget
    mb = MonthlyBudget.query.filter_by(
        plan_id=plan.id, 
        category_id=category_id, 
        month=target_month, 
        year=target_year
    ).first()
    
    if mb:
        mb.assigned_amount = new_amount
    else:
        mb = MonthlyBudget(
            plan_id=plan.id, 
            category_id=category_id, 
            month=target_month, 
            year=target_year, 
            assigned_amount=new_amount, 
            spent_amount=0
        )
        db.session.add(mb)
    
    db.session.commit()
    
    flash(f"Budget updated for {category_to_update.name}!", "success")
    return redirect(url_for('views.home'))

@views.route('/add-income', methods=['POST'])
@login_required
def add_income():
    """Add unexpected income and distribute it according to budget ratios"""
    plan = current_user.active_plan
    if not plan:
        flash('No active plan found.', 'error')
        return redirect(url_for('views.home'))
    
    amount = float(request.form.get('amount', 0))
    description = request.form.get('description', '').strip()
    month = int(request.form.get('month'))
    year = int(request.form.get('year'))
    
    if amount <= 0:
        flash('Amount must be greater than 0.', 'error')
        return redirect(url_for('views.home'))
    
    if not description:
        flash('Description is required.', 'error')
        return redirect(url_for('views.home'))
    
    # Get budget ratios
    budget_ratios = plan.budget_pref.get('ratios', {}) if plan.budget_pref else {}
    needs_ratio = budget_ratios.get('needs', 50) / 100.0
    wants_ratio = budget_ratios.get('wants', 30) / 100.0
    savings_ratio = budget_ratios.get('savings', 20) / 100.0
    
    # Calculate distribution amounts
    needs_amount = amount * needs_ratio
    wants_amount = amount * wants_ratio
    savings_amount = amount * savings_ratio
    
    # Get main categories for each type
    needs_categories = [c for c in plan.categories if c.main_category.lower() == 'needs']
    wants_categories = [c for c in plan.categories if c.main_category.lower() == 'wants']
    investments_categories = [c for c in plan.categories if c.main_category.lower() == 'investments']
    
    # Distribute to categories (evenly within each main category)
    def distribute_to_categories(categories, total_amount):
        if not categories:
            return
        
        amount_per_category = total_amount / len(categories)
        
        for category in categories:
            # Get or create MonthlyBudget record
            mb = MonthlyBudget.query.filter_by(
                plan_id=plan.id,
                category_id=category.id,
                month=month,
                year=year
            ).first()
            
            if mb:
                mb.assigned_amount += amount_per_category
            else:
                mb = MonthlyBudget(
                    plan_id=plan.id,
                    category_id=category.id,
                    month=month,
                    year=year,
                    assigned_amount=amount_per_category,
                    spent_amount=0
                )
                db.session.add(mb)
    
    # Record the additional income ONLY - don't distribute to categories
    # This way it shows up in "Money Remaining to Assign" for user to allocate manually
    additional_income = AdditionalIncome(
        plan_id=plan.id,
        month=month,
        year=year,
        amount=amount,
        description=description
    )
    db.session.add(additional_income)
    
    db.session.commit()
    
    flash(f'฿{amount:.2f} from "{description}" has been added to your available money to assign!', 'success')
    return redirect(url_for('views.home', month=month, year=year))
