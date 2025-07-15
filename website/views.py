from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from werkzeug.security import generate_password_hash 
from flask_login import login_required, current_user
from .models import BudgetCategory, Transaction, Plan, MonthlyBudget, MonthlyRollover
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
                    plan_id=plan.id, month=prev_month_int, year=prev_month_year, leftover_amount=leftover
                )
                db.session.add(new_rollover)
                db.session.commit()
                rollover_amount = leftover
        else:
            rollover_amount = rollover_from_last_month.leftover_amount

    # --- Budget Processing for Display Month ---
    categories = BudgetCategory.query.filter_by(plan_id=plan.id).all()
    monthly_budgets_map = {}
    for cat in categories:
        mb = MonthlyBudget.query.filter_by(plan_id=plan.id, category_id=cat.id, month=month, year=year).first()
        if not mb:
            mb = MonthlyBudget(plan_id=plan.id, category_id=cat.id, month=month, year=year,
                               assigned_amount=cat.assigned_amount, spent_amount=0)
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
        category_id = data.get('category_id')
        new_amount = float(data.get('amount', 0))

        if new_amount < 0:
            return jsonify({'success': False, 'error': 'Assigned amount cannot be negative.'}), 400

        plan = current_user.active_plan
        if not plan:
            return jsonify({'success': False, 'error': 'Active plan not found.'}), 404

        category_to_update = BudgetCategory.query.filter_by(id=category_id, plan_id=plan.id).first()
        if not category_to_update:
            return jsonify({'success': False, 'error': 'Category not found'}), 404

        # --- Income Validation ---
        total_assigned_query = db.session.query(func.sum(BudgetCategory.assigned_amount)).filter(BudgetCategory.plan_id == plan.id)
        current_total_assigned = total_assigned_query.scalar() or 0.0
        new_total_assigned = current_total_assigned - category_to_update.assigned_amount + new_amount

        if new_total_assigned > plan.monthly_income:
            overage = new_total_assigned - plan.monthly_income
            error_message = f'This change would exceed your monthly income by ${overage:.2f}. Please adjust.'
            return jsonify({'success': False, 'error': error_message}), 400

        # --- Update Database ---
        category_to_update.assigned_amount = new_amount
        db.session.commit()

        # --- Recalculate Totals for Response ---
        main_cat_name = category_to_update.main_category
        main_cat_subcategories = BudgetCategory.query.filter_by(plan_id=plan.id, main_category=main_cat_name).all()

        parent_total_assigned = sum(c.assigned_amount for c in main_cat_subcategories)
        parent_total_spent = sum(c.spent_amount for c in main_cat_subcategories)
        parent_total_available = parent_total_assigned - parent_total_spent
        
        # Grand total is the value we already calculated
        grand_total_assigned = new_total_assigned

        return jsonify({
            'success': True,
            'updated_subcategory': {
                'id': category_to_update.id,
                'new_amount': category_to_update.assigned_amount,
                'available_amount': category_to_update.available_amount
            },
            'updated_parent_category': {
                'name': main_cat_name,
                'total_assigned': parent_total_assigned,
                'total_available': parent_total_available
            },
            'new_grand_total_assigned': grand_total_assigned
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@views.route('/api/add-transaction', methods=['POST'])
@login_required
def add_transaction():
    """API endpoint to add a new transaction"""
    try:
        data = request.get_json()
        category_id = data.get('category_id')
        amount = float(data.get('amount', 0))
        description = data.get('description', 'Transaction')
        
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

@views.route('/open-plan')
@login_required
def open_plan():
    """Display a list of all the user's plans."""
    return render_template('open_plan.html', plans=current_user.plans)

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
                needs = int(request.form.get('needs_ratio'))
                wants = int(request.form.get('wants_ratio'))
                savings = int(request.form.get('savings_ratio'))

                if needs + wants + savings == 100:
                    plan.budget_pref['ratios'] = {'needs': needs, 'wants': wants, 'savings': savings}
                    flag_modified(plan, 'budget_pref')
                    db.session.commit()
                    flash("Category ratios updated successfully!", 'success')
                else:
                    flash("Ratios must add up to 100.", 'error')
            except (ValueError, TypeError):
                flash("Invalid ratio value.", 'error')



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
