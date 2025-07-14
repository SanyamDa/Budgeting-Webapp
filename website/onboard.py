from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from .models import Plan, BudgetCategory
from . import db

onboard = Blueprint("onboard", __name__)

@onboard.route("/onboarding", methods=["GET", "POST"])
@login_required
def show_form():
    # This route is now for creating new plans, so we don't redirect if profile is complete.
    if request.method == "POST":
        # -------- main numbers --------
        income  = float(request.form.get("income", 0) or 0)
        needs_p = float(request.form.get("needs", 0) or 0)
        wants_p = float(request.form.get("wants", 0) or 0)
        save_p  = float(request.form.get("savings", 0) or 0)

        # -------- sub-category arrays --------
        needs_sub   = request.form.getlist("needsSub[]")
        wants_sub   = request.form.getlist("wantsSub[]")
        saving_sub  = request.form.getlist("savingsSub[]")
        plan_name   = request.form.get("plan_name", "").strip() or "My First Plan"

        # -------- Create new Plan object -------- 
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

    