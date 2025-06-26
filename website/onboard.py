from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from .models import Plan
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
        db.session.flush() # Use flush to get the new_plan.id before commit

        # Set as active plan and mark profile as complete if it's the first time
        current_user.active_plan_id = new_plan.id
        if not current_user.profile_complete:
            current_user.profile_complete = True
        
        db.session.commit()

        flash(f"New plan '{plan_name}' created successfully!", "success")
        return redirect(url_for("views.home"))

    # GET -> show the wizard template
    return render_template("onboarding.html")

    