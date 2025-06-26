from flask import Blueprint, render_template, redirect, url_for, flash, request
from werkzeug.security import generate_password_hash 
from flask_login import login_required, current_user
from .models import Plan
from sqlalchemy.orm.attributes import flag_modified
from . import db

views = Blueprint('views', __name__)

@views.route('/')
@login_required
def home():
    # Redirect to onboarding if the user hasn't created their first plan yet
    if not current_user.profile_complete or not current_user.active_plan:
        return redirect(url_for('onboard.show_form'))

    plan = current_user.active_plan
    budget_ratios = plan.budget_pref.get('ratios', {})

    # Prepare data for the budget allocation chart
    chart_data = {
        'labels': ['Needs', 'Wants', 'Savings'],
        'datasets': [{
            'label': 'Budget Allocation',
            'data': [
                budget_ratios.get('needs', 0),
                budget_ratios.get('wants', 0),
                budget_ratios.get('savings', 0)
            ],
            'backgroundColor': [
                '#4e73df',
                '#1cc88a',
                '#36b9cc'
            ],
            'hoverBackgroundColor': [
                '#2e59d9',
                '#17a673',
                '#2c9faf'
            ],
            'hoverBorderColor': "rgba(234, 236, 244, 1)",
        }]
    }

    return render_template("home.html", plan=plan, chart_data=chart_data)

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

