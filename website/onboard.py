from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from .models import Plan, BudgetCategory
from . import db
import re

onboard = Blueprint("onboard", __name__)

@onboard.route("/onboarding", methods=["GET", "POST"])
@login_required
def show_form():
    # This route is now for creating new plans, so we don't redirect if profile is complete.
    if request.method == "POST":
        # -------- Input Validation --------
        
        # 1.1) Monthly income validation - must be numeric and not blank
        income_str = request.form.get("income", "").strip()
        if not income_str:
            flash("Monthly income cannot be blank.", "error")
            return render_template("onboarding.html")
        
        try:
            income = float(income_str)
            if income < 0:
                flash("Monthly income cannot be negative.", "error")
                return render_template("onboarding.html")
            if income == 0:
                flash("Monthly income must be greater than zero.", "error")
                return render_template("onboarding.html")
            if not income.is_integer():
                flash("Monthly income must be a whole number (no decimals).", "error")
                return render_template("onboarding.html")
            income = int(income)  # Convert to integer
        except ValueError:
            flash("Monthly income must be a valid number.", "error")
            return render_template("onboarding.html")
        
        # 1.2) Ratios validation - must be numeric and add up to 100
        needs_str = request.form.get("needs", "50").strip()
        wants_str = request.form.get("wants", "30").strip()
        save_str = request.form.get("investments", "20").strip()  # Note: form uses 'investments'
        
        try:
            needs_p = float(needs_str) if needs_str else 50.0
            wants_p = float(wants_str) if wants_str else 30.0
            save_p = float(save_str) if save_str else 20.0
            
            # Check if ratios add up to 100
            total_ratio = needs_p + wants_p + save_p
            if abs(total_ratio - 100.0) > 0.01:  # Allow small floating point differences
                flash("Budget ratios must add up to 100%. Current total: {:.1f}%".format(total_ratio), "error")
                return render_template("onboarding.html")
                
        except ValueError:
            flash("Budget ratios must be valid numbers.", "error")
            return render_template("onboarding.html")
        
        # 1.3) Subcategory name validation - must be alphabetic characters only, no numbers
        needs_sub = request.form.getlist("needsSub[]")
        wants_sub = request.form.getlist("wantsSub[]")
        saving_sub = request.form.getlist("savingsSub[]")
        
        # Validate subcategory names
        all_subcategories = needs_sub + wants_sub + saving_sub
        for subcat in all_subcategories:
            subcat = subcat.strip()
            if not subcat:
                flash("Subcategory names cannot be blank.", "error")
                return render_template("onboarding.html")
            
            # Check if contains numbers or special characters (allow only letters and spaces)
            if not re.match(r'^[a-zA-Z\s]+$', subcat):
                flash(f"Subcategory '{subcat}' can only contain letters and spaces, no numbers or special characters.", "error")
                return render_template("onboarding.html")
        
        # 1.4) Plan name validation - can include any characters but not blank
        plan_name = request.form.get("plan_name", "").strip()
        if not plan_name:
            flash("Plan name cannot be blank.", "error")
            return render_template("onboarding.html")
        
        # main numbers 
        # Values already validated above

        # Create new Plan object
        new_plan = Plan(
            name=plan_name,
            monthly_income=income,
            budget_pref={
                "ratios": {"needs": needs_p, "wants": wants_p, "savings": save_p},
                "subcategories": {
                    "needs": needs_sub,
                    "wants": wants_sub,
                    "savings": saving_sub
                }
            },
            user_id=current_user.id
        )
        db.session.add(new_plan)
        db.session.flush()  # Use flush to get the new_plan.id before commit

        # Create BudgetCategory objects from subcategories
        category_mapping = {
            'needs': (needs_sub, 'needs'),
            'wants': (wants_sub, 'wants'),
            'savings': (saving_sub, 'investments')  # Map 'savings' from form to 'investments'
        }

        for form_key, (sub_list, main_cat_name) in category_mapping.items():
            for sub_name in sub_list:
                if sub_name.strip():
                    new_cat = BudgetCategory(
                        name=sub_name.strip(),
                        main_category=main_cat_name,
                        assigned_amount=0,  # Default to 0, user assigns on home page
                        plan_id=new_plan.id
                    )
                    db.session.add(new_cat)

        # Set as active plan and mark profile as complete if it's the first time
        current_user.active_plan_id = new_plan.id
        if not current_user.profile_complete:
            current_user.profile_complete = True
        
        db.session.commit()

        flash(f"New plan '{plan_name}' created successfully!", "success")
        return redirect(url_for("views.home"))

    # GET -> show the wizard template
    return render_template("onboarding.html")

    