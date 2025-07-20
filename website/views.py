from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from werkzeug.security import generate_password_hash 
from flask_login import login_required, current_user
from .models import BudgetCategory, Transaction, Plan, MonthlyBudget, MonthlyRollover, Payee
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import func
from . import db
import datetime

views = Blueprint('views', __name__)

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
        today = datetime.datetime.now()
        year, month = today.year, today.month
    
    try:
        display_date = datetime.datetime(year, month, 1)
    except ValueError:
        # Handle invalid month/year in URL
        today = datetime.datetime.now()
        year, month = today.year, today.month
        display_date = today

    display_month_str = display_date.strftime('%B')

    # Determine if the current view is the user's first month
    user_join_date = current_user.date_created
    if user_join_date is None:
        # If the user has no join date, set it to now to prevent crash and fix the data.
        user_join_date = datetime.datetime.now()
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

        # If no record, calculate it
        if not rollover_from_last_month:
            prev_month_budgets = MonthlyBudget.query.filter_by(
                plan_id=plan.id, month=prev_month_int, year=prev_month_year
            ).all()
            
            if prev_month_budgets:
                total_assigned_prev = sum(mb.assigned_amount for mb in prev_month_budgets)
                total_spent_prev = sum(mb.spent_amount for mb in prev_month_budgets)
                leftover = total_assigned_prev - total_spent_prev
                
                new_rollover = MonthlyRollover(
                    plan_id=plan.id, month=prev_month_int, year=prev_month_year, amount=leftover
                )
                db.session.add(new_rollover)
                db.session.commit()
                rollover_amount = leftover
        else:
            rollover_amount = rollover_from_last_month.amount

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
    
    money_to_be_assigned = plan.monthly_income + rollover_amount
    available_amount = money_to_be_assigned - total_assigned

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
                         current_year=year,
                         # For navigation
                         prev_month=prev_month_date.month,
                         prev_year=prev_month_date.year,
                         next_month=next_month_date.month,
                         next_year=next_month_date.year,
                         is_first_month=is_first_month,
                         can_go_prev=can_go_prev,
                         can_go_next=can_go_next,
                         # Summary data
                         total_assigned=total_assigned,
                         total_spent=total_spent,
                         available_amount=available_amount,
                         rollover_amount=rollover_amount,
                         money_to_be_assigned=money_to_be_assigned,
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
    now = datetime.datetime.now()
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
        print(f"Extracted category_id: {category_id}, type: {type(category_id)}")  # Debug
        
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
        
        # Get the budget ratios from plan settings
        print(f"Plan budget_pref: {plan.budget_pref}")  # Debug
        print(f"Plan monthly_income: {plan.monthly_income}")  # Debug
        budget_ratios = plan.budget_pref.get('ratios', {}) if plan.budget_pref else {}
        print(f"Budget ratios: {budget_ratios}")  # Debug
        
        # Handle naming inconsistency: "investments" in categories vs "savings" in budget_pref
        ratio_key = main_cat_name
        if main_cat_name == 'investments':
            ratio_key = 'savings'
        
        try:
            category_ratio = budget_ratios.get(ratio_key, 0) / 100.0
            print(f"Category ratio for {main_cat_name} (using key '{ratio_key}'): {category_ratio}")  # Debug  # Debug
        except Exception as e:
            print(f"Error calculating category ratio: {e}")  # Debug
            raise        
        # Calculate the maximum allowed amount based on the ratio
        max_allowed = plan.monthly_income * category_ratio if plan.monthly_income else 0
        
        # Get current total assigned to this main category
        current_date = datetime.datetime.now()
        current_month = current_date.month
        current_year = current_date.year
        
        # Get current total assigned to this main category from MonthlyBudget records
        current_total = 0
        for c in plan.categories:
            if c.main_category.lower() == main_cat_name and c.id != category_id:
                mb = MonthlyBudget.query.filter_by(
                    plan_id=plan.id, 
                    category_id=c.id, 
                    month=current_month, 
                    year=current_year
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
        # Get current month and year
        current_date = datetime.datetime.now()
        current_month = current_date.month
        current_year = current_date.year
        
        # Find or create MonthlyBudget record for this category and month
        monthly_budget = MonthlyBudget.query.filter_by(
            plan_id=plan.id, 
            category_id=category_id, 
            month=current_month, 
            year=current_year
        ).first()
        
        if not monthly_budget:
            monthly_budget = MonthlyBudget(
                plan_id=plan.id,
                category_id=category_id,
                month=current_month,
                year=current_year,
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
    """API endpoint to add a new transaction"""
    try:
        data = request.get_json()
        category_id = data.get('category_id')
        amount = float(data.get('amount', 0))
        description = data.get('description', 'Transaction')
        payee_id = data.get('payee_id')
        
        category = BudgetCategory.query.filter_by(
            id=category_id,
            plan_id=current_user.active_plan.id
        ).first()
        
        if not category:
            return jsonify({'success': False, 'error': 'Category not found'}), 404
        
        # Create new transaction (amount should be negative for expenses)
        transaction = Transaction(
            description=description,
            amount=-abs(amount),  # Make negative for expenses
            category_id=category_id,
            payee_id=payee_id,
            plan_id=current_user.active_plan.id
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        # Update category spent amount
        spent = db.session.query(func.sum(Transaction.amount)).filter_by(
            category_id=category.id
        ).scalar() or 0
        category.spent_amount = abs(spent)
        db.session.commit()
    

        return jsonify({
            'success': True,
            'transaction_id': transaction.id,
            'category_spent': category.spent_amount,
            'category_available': category.available_amount
        })
        
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
@views.route('/transactions')
@login_required
def transactions():
    """Display the transactions summary page (placeholder until table implemented)."""
    # Ensure the user has an active plan
    plan = current_user.active_plan
    if not plan:
        flash("No active plan found.", 'error')
        return redirect(url_for('views.home'))

    # Calculate Monthly Allowance (income)
    monthly_allowance = plan.monthly_income or 0.0

    # Determine current month/year
    today = datetime.datetime.now()
    start_of_month = datetime.datetime(today.year, today.month, 1)
    end_of_month = start_of_month + datetime.timedelta(days=32)
    end_of_month = datetime.datetime(end_of_month.year, end_of_month.month, 1)

    # Sum all transaction amounts for this plan in the current month (expenses are stored as negative)
    activity_sum = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.plan_id == plan.id,
        Transaction.transaction_date >= start_of_month,
        Transaction.transaction_date < end_of_month
    ).scalar() or 0.0

    activity_total = abs(activity_sum)  # Convert to positive value for display

    available = monthly_allowance - activity_total

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
        payees=[{'id': p.id, 'name': p.name} for p in plan.payees]
    )


# --------------------------- Reflect Page ---------------------------
@views.route('/reflect')
@login_required
def reflect():
    plan = current_user.active_plan
    if not plan:
        flash("No active plan found.", 'error')
        return redirect(url_for('views.home'))
    
    transactions = db.session.query(Transaction).filter(
        Transaction.plan_id == plan.id
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
        month_name = datetime.datetime(int(year), int(month), 1).strftime('%b %Y')
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
        start_of_month = datetime.datetime(int(year), int(month), 1)
        if int(month) == 12:
            end_of_month = datetime.datetime(int(year) + 1, 1, 1)
        else:
            end_of_month = datetime.datetime(int(year), int(month) + 1, 1)
        
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
    if sorted_months:
        month_totals = {}
        for month_key in sorted_months:
            year, month = month_key.split('-')
            start_of_month = datetime.datetime(int(year), int(month), 1)
            if int(month) == 12:
                end_of_month = datetime.datetime(int(year) + 1, 1, 1)
            else:
                end_of_month = datetime.datetime(int(year), int(month) + 1, 1)
            
            month_transactions = db.session.query(Transaction).filter(
                Transaction.plan_id == plan.id,
                Transaction.transaction_date >= start_of_month,
                Transaction.transaction_date < end_of_month
            ).all()
            
            month_total = sum(abs(tx.amount) for tx in month_transactions)
            month_name = datetime.datetime(int(year), int(month), 1).strftime('%b %Y')
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
    
    return render_template('reflect.html', 
                         month_options=month_options,
                         current_month=current_month,
                         spending_data=spending_data,
                         grouped_spending=grouped_spending,
                         total_spending=total_spending,
                         summary_stats=summary_stats,
                         monthly_breakdown=monthly_breakdown)


@views.route('/add_category', methods=['POST'])
@login_required
def add_category():
    """Add a new category to the current plan."""
    plan = current_user.active_plan
    if not plan:
        flash("No active plan found.", 'error')
        return redirect(url_for('views.home'))
    
    main_category = request.form.get('main_category')
    category_name = request.form.get('category_name')
    
    if not main_category or not category_name:
        flash("Please fill in all fields.", 'error')
        return redirect(url_for('views.home'))
    
    # Check if category already exists
    existing_category = BudgetCategory.query.filter_by(
        name=category_name,
        plan_id=plan.id
    ).first()
    
    if existing_category:
        flash(f"Category '{category_name}' already exists.", 'error')
        return redirect(url_for('views.home'))
    
    # Create new category
    new_category = BudgetCategory(
        name=category_name,
        main_category=main_category,
        plan_id=plan.id
    )
    
    try:
        db.session.add(new_category)
        db.session.commit()
        flash(f"Category '{category_name}' added successfully!", 'success')
    except Exception as e:
        db.session.rollback()
        flash("Error adding category. Please try again.", 'error')
    
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
    
    try:
        category_id = int(category_id)
        new_amount = float(new_amount)
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
    current_date = datetime.datetime.now()
    current_month = current_date.month
    current_year = current_date.year
    
    current_total_others = 0
    current_category_amount = 0
    
    for c in plan.categories:
        if c.main_category.lower() == main_cat_name:
            mb = MonthlyBudget.query.filter_by(
                plan_id=plan.id, 
                category_id=c.id, 
                month=current_month, 
                year=current_year
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
        month=current_month, 
        year=current_year
    ).first()
    
    if mb:
        mb.assigned_amount = new_amount
    else:
        mb = MonthlyBudget(
            plan_id=plan.id, 
            category_id=category_id, 
            month=current_month, 
            year=current_year, 
            assigned_amount=new_amount, 
            spent_amount=0
        )
        db.session.add(mb)
    
    db.session.commit()
    
    flash(f'Successfully assigned ${new_amount:.2f} to {category_to_update.name}.', 'success')
    return redirect(url_for('views.home'))