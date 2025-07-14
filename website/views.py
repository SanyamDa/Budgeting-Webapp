from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from werkzeug.security import generate_password_hash 
from flask_login import login_required, current_user
from .models import BudgetCategory, Transaction, Plan, MonthlyBudget
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import func
from . import db
import datetime

views = Blueprint('views', __name__)

@views.route('/')
@login_required
def home():
    # Redirect to onboarding if the user hasn't created their first plan yet
    if not current_user.profile_complete or not current_user.active_plan:
        return redirect(url_for('onboard.show_form'))

    plan = current_user.active_plan
    
    # Get current month and year
    current_date = datetime.datetime.now()
    current_month = current_date.strftime('%B')
    current_year = current_date.year
    
    # Get categories organized by main category and ensure MonthlyBudget exists for each
    # Create or fetch MonthlyBudget rows for the current month
    categories = BudgetCategory.query.filter_by(plan_id=plan.id).all()
    current_month_int = current_date.month

    monthly_budgets_map = {}
    for cat in categories:
        mb = MonthlyBudget.query.filter_by(plan_id=plan.id, category_id=cat.id, month=current_month_int, year=current_year).first()
        if not mb:
            mb = MonthlyBudget(plan_id=plan.id, category_id=cat.id, month=current_month_int, year=current_year,
                               assigned_amount=cat.assigned_amount, spent_amount=cat.spent_amount)
            db.session.add(mb)
            db.session.commit()
        monthly_budgets_map[cat.id] = mb

    # Organize categories by main category
    categories = BudgetCategory.query.filter_by(plan_id=plan.id).all()
    
    # Organize categories by main category
    organized_categories = {
        'bills': [],
        'needs': [],
        'wants': [],
        'investments': []
    }
    
    total_assigned = 0
    total_spent = 0
    
    for category in categories:
        # Use monthly budget values for assigned and spent
        mb = monthly_budgets_map.get(category.id)
        if mb:
            category.assigned_amount = mb.assigned_amount
            category.spent_amount = mb.spent_amount

        # Update spent amount from transactions (ensure latest)

        # Update spent amount from transactions
        spent = db.session.query(func.sum(Transaction.amount)).filter_by(
            category_id=category.id
        ).scalar() or 0
        category.spent_amount = abs(spent)  # Make positive for display
        total_assigned += category.assigned_amount
        total_spent += category.spent_amount
        
        if category.main_category in organized_categories:
            organized_categories[category.main_category].append(category)
    
    # Calculate totals by main category
    category_totals = {}
    for main_cat, cats in organized_categories.items():
        category_totals[main_cat] = {
            'assigned': sum(cat.assigned_amount for cat in cats),
            'spent': sum(cat.spent_amount for cat in cats),
            'available': sum(cat.available_amount for cat in cats)
        }
    
    # Calculate summary data
    available_amount = total_assigned - total_spent

    # Sort categories by spent amount for the summary panel
    all_categories = sorted([cat for cat in categories if cat.spent_amount > 0], key=lambda x: x.spent_amount, reverse=True)
    top_spending_categories = all_categories[:5]

    return render_template("home.html", 
                         plan=plan,
                         categories=organized_categories,
                         category_totals=category_totals,
                         current_month=current_month,
                         current_year=current_year,
                         total_assigned=total_assigned,
                         total_spent=total_spent,
                         available_amount=available_amount,
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
    """API endpoint to update category assigned amount"""
    try:
        data = request.get_json()
        category_id = data.get('category_id')
        new_amount = float(data.get('amount', 0))
        
        category = BudgetCategory.query.filter_by(
            id=category_id, 
            plan_id=current_user.active_plan.id
        ).first()
        
        if not category:
            return jsonify({'success': False, 'error': 'Category not found'}), 404
        
        category.assigned_amount = new_amount
        db.session.commit()
        
        return jsonify({
            'success': True,
            'category_id': category_id,
            'new_amount': new_amount,
            'available_amount': category.available_amount
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
