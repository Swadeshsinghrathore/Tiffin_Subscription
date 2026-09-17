import calendar
from datetime import date, timedelta
from decimal import Decimal
from functools import wraps
import os
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from tiffin.billing import compute_bill, delivery_days, format_rupees, month_bounds
from tiffin.db import close_db, init_db
from tiffin.models import BillLine, Status
from tiffin.repository import (
    add_holiday,
    create_customer,
    create_owner,
    create_pause,
    create_plan,
    delete_holiday,
    end_subscription,
    freeze_bills,
    get_all_plans,
    get_customer_by_phone,
    get_customers,
    get_frozen_bills_for_month,
    get_holiday_dates,
    get_holidays,
    get_open_pause_for_customer,
    get_owner_by_id,
    get_owner_by_username_or_email,
    get_pauses_for_customer,
    get_recent_notification_logs,
    get_transfer_in,
    get_transfer_out,
    get_transfers_map,
    has_frozen_bills,
    reactivate_subscription,
    resume_pause,
    toggle_plan_active,
    transfer_subscription,
    unfreeze_bills,
    update_customer_plan,
    verify_owner_password,
)
from tiffin.notifications import (
    dispatch_daily_delivery_notifications,
    get_customers_due_delivery_today,
)
from tiffin.scheduler import get_scheduler_info, start_scheduler
from tiffin.validators import (
    ValidationError,
    normalize_phone,
    parse_date,
    validate_pause,
    validate_resume,
    validate_transfer,
)


def login_required(f):
    """Decorator to require owner authentication for protected routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("owner_id"):
            flash("Please sign in to access the owner portal.", "warning")
            return redirect(url_for("owner_login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def customer_login_required(f):
    """Decorator to require customer authentication for customer portal routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("customer_phone"):
            flash("Please enter your registered 10-digit phone number to access your customer portal.", "info")
            return redirect(url_for("customer_login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY="tiffin-secret-key-change-in-prod",
        DATABASE=os.path.join(app.instance_path, "tiffin.db")
        if not test_config or "DATABASE" not in test_config
        else test_config["DATABASE"],
    )

    if test_config:
        app.config.update(test_config)

    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize DB on start
    with app.app_context():
        init_db()

    app.teardown_appcontext(close_db)

    # Start background scheduler for daily 9:00 AM notifications (unless testing)
    if not app.config.get("TESTING"):
        start_scheduler(app)

    # ------------------------------------------------------------------------
    # Context Processor: Inject current owner & customer into all templates
    # ------------------------------------------------------------------------
    @app.context_processor
    def inject_context():
        owner_id = session.get("owner_id")
        current_owner = get_owner_by_id(owner_id) if owner_id else None
        cust_phone = session.get("customer_phone")
        current_customer = get_customer_by_phone(cust_phone) if cust_phone else None
        return {
            "current_owner": current_owner,
            "current_customer": current_customer,
        }

    # ------------------------------------------------------------------------
    # Public Landing Page
    # ------------------------------------------------------------------------
    @app.route("/")
    def landing_page():
        return render_template("landing.html")

    # ------------------------------------------------------------------------
    # Owner Authentication: Login, Signup, Logout
    # ------------------------------------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def owner_login():
        if session.get("owner_id"):
            return redirect(url_for("customers_roster"))

        next_url = request.args.get("next") or url_for("customers_roster")

        if request.method == "POST":
            username_input = request.form.get("username", "").strip()
            password_input = request.form.get("password", "")

            owner = get_owner_by_username_or_email(username_input)
            if owner and verify_owner_password(owner, password_input):
                session.clear()
                session["owner_id"] = owner.id
                flash(f"Welcome back, {owner.business_name}!", "success")
                return redirect(next_url)
            else:
                flash("Invalid username or password. (Hint: Demo login is admin / tiffin123)", "danger")

        return render_template("login.html", next_url=next_url)

    @app.route("/signup", methods=["GET", "POST"])
    def owner_signup():
        if session.get("owner_id"):
            return redirect(url_for("customers_roster"))

        if request.method == "POST":
            business_name = request.form.get("business_name", "").strip()
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            try:
                if not business_name or not username or not email or not password:
                    raise ValidationError("All fields are required.")
                if len(password) < 6:
                    raise ValidationError("Password must be at least 6 characters.")
                if password != confirm_password:
                    raise ValidationError("Passwords do not match.")

                owner = create_owner(
                    username=username,
                    email=email,
                    password=password,
                    business_name=business_name,
                )
                session.clear()
                session["owner_id"] = owner.id
                flash(f"Account registered! Welcome to TiffinBox, {owner.business_name}.", "success")
                return redirect(url_for("customers_roster"))

            except (ValidationError, ValueError) as e:
                flash(str(e), "danger")
                return render_template("signup.html", form_data=request.form)

        return render_template("signup.html")

    @app.route("/logout")
    def owner_logout():
        session.clear()
        flash("You have been signed out successfully.", "info")
        return redirect(url_for("landing_page"))

    # ------------------------------------------------------------------------
    # Customers Roster & Search
    # ------------------------------------------------------------------------
    @app.route("/customers")
    def customers_roster():
        status_filter = request.args.get("status", "all").strip().lower()
        search_query = request.args.get("q", "").strip()

        # Fetch all customers to compute roster stats
        all_customers = get_customers()
        stats = {
            "total": len(all_customers),
            "active": sum(1 for c in all_customers if c.status == Status.ACTIVE),
            "paused": sum(1 for c in all_customers if c.status == Status.PAUSED),
            "ended": sum(1 for c in all_customers if c.status in (Status.ENDED, Status.NOT_STARTED)),
        }

        # Filtered customer list
        filtered = get_customers(status_filter=status_filter, query=search_query)

        return render_template(
            "customers.html",
            customers=filtered,
            stats=stats,
            current_status=status_filter,
            current_query=search_query,
        )

    # ------------------------------------------------------------------------
    # Subscription Management
    # ------------------------------------------------------------------------
    @app.route("/customers/new", methods=["GET", "POST"])
    @login_required
    def subscribe_customer():
        today_iso = date.today().isoformat()
        plans = get_all_plans(include_inactive=False)

        if request.method == "POST":
            raw_phone = request.form.get("phone", "")
            raw_name = request.form.get("name", "")
            raw_email = request.form.get("email", "")
            raw_address = request.form.get("address", "")
            raw_plan_id = request.form.get("plan_id", "")
            raw_start_date = request.form.get("start_date", "")

            try:
                if not raw_name.strip():
                    raise ValidationError("Customer name is required.")
                if not raw_plan_id:
                    raise ValidationError("Please select a meal plan.")

                norm_phone = normalize_phone(raw_phone)
                start_d = parse_date(raw_start_date)
                plan_id = int(raw_plan_id)

                customer = create_customer(
                    phone=norm_phone,
                    name=raw_name,
                    email=raw_email,
                    address=raw_address,
                    plan_id=plan_id,
                    start_date=start_d,
                )
                flash(f"Successfully subscribed {customer.name} ({customer.phone})!", "success")
                return redirect(url_for("customer_detail", phone=customer.phone))

            except (ValidationError, ValueError) as e:
                flash(str(e), "danger")
                return render_template(
                    "subscribe.html",
                    plans=plans,
                    today_iso=today_iso,
                    form_data=request.form,
                )

        return render_template("subscribe.html", plans=plans, today_iso=today_iso)

    # ------------------------------------------------------------------------
    # Single Customer Detail & Actions
    # ------------------------------------------------------------------------
    @app.route("/customers/<phone>")
    def customer_detail(phone: str):
        customer = get_customer_by_phone(phone)
        if not customer:
            flash(f"Customer with phone '{phone}' not found.", "danger")
            return redirect(url_for("customers_roster"))

        pauses = get_pauses_for_customer(customer.id)  # type: ignore
        today = date.today()
        holidays = get_holiday_dates()

        current_bill = compute_bill(
            plan=customer.plan,  # type: ignore
            customer=customer,
            pauses=pauses,
            year=today.year,
            month=today.month,
            holidays=holidays,
        )

        return render_template(
            "customer_detail.html",
            customer=customer,
            pauses=pauses,
            current_bill=current_bill,
            current_month_name=calendar.month_name[today.month],
            today_iso=today.isoformat(),
        )

    @app.route("/customers/<phone>/pause", methods=["POST"])
    @login_required
    def customer_pause(phone: str):
        customer = get_customer_by_phone(phone)
        if not customer:
            flash("Customer not found.", "danger")
            return redirect(url_for("customers_roster"))

        try:
            start_d = parse_date(request.form.get("start_date", ""))
            end_raw = request.form.get("end_date", "").strip()
            end_d = parse_date(end_raw) if end_raw else None
            reason = request.form.get("reason", "").strip()

            open_pause = get_open_pause_for_customer(customer.id)  # type: ignore
            validate_pause(open_pause, start_d, end_d)

            create_pause(customer.id, start_d, end_d, reason)  # type: ignore

            today = date.today()
            if start_d < today:
                flash(f"Recorded backdated pause starting from {start_d.strftime('%b %d, %Y')}.", "warning")
            else:
                flash(f"Successfully recorded pause starting from {start_d.strftime('%b %d, %Y')}.", "success")

        except (ValidationError, ValueError) as e:
            flash(str(e), "danger")

        return redirect(url_for("customer_detail", phone=customer.phone))

    @app.route("/customers/<phone>/resume", methods=["POST"])
    @login_required
    def customer_resume(phone: str):
        customer = get_customer_by_phone(phone)
        if not customer:
            flash("Customer not found.", "danger")
            return redirect(url_for("customers_roster"))

        try:
            resume_d = parse_date(request.form.get("resume_date", ""))
            open_pause = get_open_pause_for_customer(customer.id)  # type: ignore
            validate_resume(open_pause, resume_d)

            resume_pause(open_pause.id, resume_d)  # type: ignore
            flash(f"Resumed delivery for {customer.name}. Pause closed through {resume_d.strftime('%b %d, %Y')}.", "success")

        except (ValidationError, ValueError) as e:
            flash(str(e), "danger")

        return redirect(url_for("customer_detail", phone=customer.phone))

    @app.route("/customers/<phone>/end", methods=["POST"])
    @login_required
    def customer_end(phone: str):
        customer = get_customer_by_phone(phone)
        if not customer:
            flash("Customer not found.", "danger")
            return redirect(url_for("customers_roster"))

        try:
            end_d = parse_date(request.form.get("end_date", ""))
            end_subscription(customer.phone, end_d)
            flash(f"Subscription for {customer.name} marked to end on {end_d.strftime('%b %d, %Y')}.", "info")
        except (ValidationError, ValueError) as e:
            flash(str(e), "danger")

        return redirect(url_for("customer_detail", phone=customer.phone))

    @app.route("/customers/<phone>/transfer", methods=["GET", "POST"])
    @login_required
    def customer_transfer(phone: str):
        customer = get_customer_by_phone(phone)
        if not customer:
            flash("Customer not found.", "danger")
            return redirect(url_for("customers_roster"))

        today = date.today()
        # Default transfer date: tomorrow or today, must be strictly after customer start date
        default_transfer_date = max(today, customer.start_date + timedelta(days=1))

        if request.method == "POST":
            raw_phone = request.form.get("new_phone", "")
            raw_name = request.form.get("new_name", "")
            raw_address = request.form.get("new_address", "")
            raw_email = request.form.get("new_email", "")
            raw_date = request.form.get("transfer_date", "")
            raw_reason = request.form.get("reason", "")

            try:
                transfer_d = parse_date(raw_date)
                norm_new_phone = validate_transfer(customer, raw_phone, raw_name, transfer_d)

                new_customer, transfer_record = transfer_subscription(
                    from_customer=customer,
                    new_phone=norm_new_phone,
                    new_name=raw_name,
                    transfer_date=transfer_d,
                    new_address=raw_address,
                    new_email=raw_email,
                    reason=raw_reason,
                )

                flash(
                    f"Subscription successfully transferred to {new_customer.name} ({new_customer.phone}) "
                    f"effective {transfer_d.strftime('%b %d, %Y')}. The {customer.plan.name if customer.plan else 'meal'} plan and cycle "
                    f"have carried over, and month-end billing will automatically split by who was served.",
                    "success",
                )
                return redirect(url_for("customer_detail", phone=new_customer.phone))

            except (ValidationError, ValueError) as e:
                flash(str(e), "danger")
                return render_template(
                    "transfer.html",
                    customer=customer,
                    default_date=raw_date or default_transfer_date.isoformat(),
                    form_data=request.form,
                )

        return render_template(
            "transfer.html",
            customer=customer,
            default_date=default_transfer_date.isoformat(),
            form_data={},
        )

    # ------------------------------------------------------------------------
    # Monthly Billing Sheet & Generation
    # ------------------------------------------------------------------------
    @app.route("/billing")
    def billing_sheet():
        today = date.today()
        try:
            year = int(request.args.get("year", today.year))
            month = int(request.args.get("month", today.month))
            if not (1 <= month <= 12 and 2000 <= year <= 2100):
                year, month = today.year, today.month
        except (ValueError, TypeError):
            year, month = today.year, today.month

        # Calculate prev / next month for pagination
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1

        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        # Month bounds and holidays
        first_d, last_d = month_bounds(year, month)
        holidays_set = get_holiday_dates()
        month_holidays = {h for h in holidays_set if first_d <= h <= last_d}
        billable_days_month = len(delivery_days(first_d, last_d, holidays_set))

        is_frozen = has_frozen_bills(year, month)
        frozen_at = None

        if is_frozen:
            bills = get_frozen_bills_for_month(year, month)
            if bills and bills[0].generated_at:
                frozen_at = bills[0].generated_at
        else:
            all_customers = get_customers()
            bills = []
            for c in all_customers:
                if c.start_date <= last_d and (c.end_date is None or c.end_date >= first_d):
                    pauses = get_pauses_for_customer(c.id)  # type: ignore
                    line = compute_bill(
                        plan=c.plan,  # type: ignore
                        customer=c,
                        pauses=pauses,
                        year=year,
                        month=month,
                        holidays=holidays_set,
                    )
                    bills.append(line)

        transfers_map = get_transfers_map()
        for b in bills:
            b.transfer_info = transfers_map.get(b.customer.id)

        total_revenue_paise = sum(b.amount_paise for b in bills)
        total_delivered_meals = sum(b.delivered_days for b in bills)
        is_future_month = (year, month) > (today.year, today.month)
        is_current_month = (year, month) == (today.year, today.month)

        return render_template(
            "billing.html",
            year=year,
            month=month,
            month_name=calendar.month_name[month],
            prev_year=prev_year,
            prev_month=prev_month,
            next_year=next_year,
            next_month=next_month,
            bills=bills,
            billable_days_month=billable_days_month,
            holidays_count=len(month_holidays),
            total_revenue_formatted=format_rupees(total_revenue_paise),
            total_delivered_meals=total_delivered_meals,
            is_frozen=is_frozen,
            frozen_at=frozen_at,
            is_future_month=is_future_month,
            is_current_month=is_current_month,
        )

    @app.route("/billing/generate", methods=["POST"])
    @login_required
    def billing_generate():
        try:
            year = int(request.form.get("year", 0))
            month = int(request.form.get("month", 0))
            if not (1 <= month <= 12 and 2000 <= year <= 2100):
                raise ValueError("Invalid year/month.")

            first_d, last_d = month_bounds(year, month)
            holidays_set = get_holiday_dates()
            all_customers = get_customers()

            bills_to_freeze: list[BillLine] = []
            for c in all_customers:
                if c.start_date <= last_d and (c.end_date is None or c.end_date >= first_d):
                    pauses = get_pauses_for_customer(c.id)  # type: ignore
                    line = compute_bill(
                        plan=c.plan,  # type: ignore
                        customer=c,
                        pauses=pauses,
                        year=year,
                        month=month,
                        holidays=holidays_set,
                    )
                    bills_to_freeze.append(line)

            freeze_bills(bills_to_freeze)
            flash(f"Successfully froze and finalized {len(bills_to_freeze)} invoices for {calendar.month_name[month]} {year}!", "success")
        except Exception as e:
            flash(f"Error finalizing bills: {e}", "danger")

        return redirect(url_for("billing_sheet", year=year, month=month))

    @app.route("/billing/unfreeze", methods=["POST"])
    @login_required
    def billing_unfreeze():
        try:
            year = int(request.form.get("year", 0))
            month = int(request.form.get("month", 0))
            unfreeze_bills(year, month)
            flash(f"Invoices for {calendar.month_name[month]} {year} have been unfrozen. Live recalculation enabled.", "info")
        except Exception as e:
            flash(f"Error unfreezing bills: {e}", "danger")

        return redirect(url_for("billing_sheet", year=year, month=month))

    # ------------------------------------------------------------------------
    # Meal Plans Management
    # ------------------------------------------------------------------------
    @app.route("/plans", methods=["GET", "POST"])
    def plans_view():
        if request.method == "POST":
            if not session.get("owner_id"):
                flash("Please log in to modify plans.", "warning")
                return redirect(url_for("owner_login"))

            code = request.form.get("code", "")
            name = request.form.get("name", "")
            price_rupees_raw = request.form.get("price_rupees", "")

            try:
                if not code.strip() or not name.strip() or not price_rupees_raw.strip():
                    raise ValidationError("All fields are required.")
                price_dec = Decimal(price_rupees_raw.strip())
                if price_dec <= 0:
                    raise ValidationError("Price must be greater than zero.")
                price_paise = int(price_dec * 100)
                create_plan(code, name, price_paise)
                flash(f"Plan '{name}' created successfully!", "success")
            except (ValidationError, ValueError) as e:
                flash(str(e), "danger")

            return redirect(url_for("plans_view"))

        plans = get_all_plans(include_inactive=True)
        return render_template("plans.html", plans=plans)

    @app.route("/plans/<int:plan_id>/toggle", methods=["POST"])
    @login_required
    def toggle_plan(plan_id: int):
        toggle_plan_active(plan_id)
        flash("Plan status updated.", "info")
        return redirect(url_for("plans_view"))

    # ------------------------------------------------------------------------
    # Service Holidays
    # ------------------------------------------------------------------------
    @app.route("/holidays", methods=["GET", "POST"])
    def holidays_view():
        today_iso = date.today().isoformat()
        if request.method == "POST":
            if not session.get("owner_id"):
                flash("Please log in to add holidays.", "warning")
                return redirect(url_for("owner_login"))

            day_raw = request.form.get("day", "")
            label = request.form.get("label", "")
            try:
                if not label.strip():
                    raise ValidationError("Holiday reason / label is required.")
                day_d = parse_date(day_raw)
                add_holiday(day_d, label)
                flash(f"Added service closure for {day_d.strftime('%b %d, %Y')} ({label}).", "success")
            except (ValidationError, ValueError) as e:
                flash(str(e), "danger")

            return redirect(url_for("holidays_view"))

        holidays = get_holidays()
        return render_template("holidays.html", holidays=holidays, today_iso=today_iso)

    @app.route("/holidays/<day_iso>/delete", methods=["POST"])
    @login_required
    def delete_holiday_route(day_iso: str):
        try:
            day_d = parse_date(day_iso)
            delete_holiday(day_d)
            flash(f"Removed service holiday for {day_d.strftime('%b %d, %Y')}.", "info")
        except Exception as e:
            flash(f"Error removing holiday: {e}", "danger")

        return redirect(url_for("holidays_view"))

    # ------------------------------------------------------------------------
    # Customer Portal & Self-Service
    # ------------------------------------------------------------------------
    @app.route("/customer/login", methods=["GET", "POST"])
    def customer_login():
        if session.get("customer_phone"):
            return redirect(url_for("customer_portal"))

        phone_val = ""
        if request.method == "POST":
            phone_raw = request.form.get("phone", "")
            try:
                norm_phone = normalize_phone(phone_raw)
                customer = get_customer_by_phone(norm_phone)
                if not customer:
                    flash(f"No subscription found for phone '{norm_phone}'. Please check your 10-digit number.", "danger")
                    phone_val = phone_raw
                else:
                    session["customer_phone"] = customer.phone
                    session["customer_id"] = customer.id
                    flash(f"Welcome to your portal, {customer.name}!", "success")
                    next_url = request.args.get("next")
                    return redirect(next_url or url_for("customer_portal"))
            except ValidationError as e:
                flash(str(e), "danger")
                phone_val = phone_raw

        # Provide sample active customers for quick 1-click login demonstration
        sample_customers = get_customers()[:4]
        return render_template("customer_login.html", phone_val=phone_val, sample_customers=sample_customers)

    @app.route("/customer/logout")
    def customer_logout():
        session.pop("customer_phone", None)
        session.pop("customer_id", None)
        flash("You have been signed out of your customer portal.", "info")
        return redirect(url_for("landing_page"))

    @app.route("/portal")
    @customer_login_required
    def customer_portal():
        phone = session.get("customer_phone")
        customer = get_customer_by_phone(phone)
        if not customer:
            session.pop("customer_phone", None)
            session.pop("customer_id", None)
            flash("Customer session expired. Please enter your phone number.", "warning")
            return redirect(url_for("customer_login"))

        today = date.today()
        pauses = get_pauses_for_customer(customer.id)
        holidays = get_holiday_dates()
        current_bill = compute_bill(
            plan=customer.plan,
            customer=customer,
            pauses=pauses,
            year=today.year,
            month=today.month,
            holidays=holidays,
        )
        open_pause = get_open_pause_for_customer(customer.id)
        active_plans = get_all_plans(include_inactive=False)
        current_month_name = calendar.month_name[today.month]

        return render_template(
            "customer_portal.html",
            customer=customer,
            current_bill=current_bill,
            current_month_name=current_month_name,
            pauses=pauses,
            open_pause=open_pause,
            active_plans=active_plans,
            today_iso=today.isoformat(),
        )

    @app.route("/portal/pause", methods=["POST"])
    @customer_login_required
    def customer_portal_pause():
        phone = session.get("customer_phone")
        customer = get_customer_by_phone(phone)
        if not customer:
            return redirect(url_for("customer_login"))

        start_date_raw = request.form.get("start_date", "")
        end_date_raw = request.form.get("end_date", "")
        is_open = request.form.get("is_open_ended") == "1"
        reason = request.form.get("reason", "")

        try:
            start_d = parse_date(start_date_raw)
            end_d = None if is_open or not end_date_raw else parse_date(end_date_raw)

            open_pause = get_open_pause_for_customer(customer.id)
            validate_pause(open_pause, start_d, end_d)

            create_pause(customer.id, start_d, end_d, reason)
            flash(f"Tiffin delivery paused starting {start_d.strftime('%b %d, %Y')}.", "success")
        except (ValidationError, ValueError) as e:
            flash(str(e), "danger")

        return redirect(url_for("customer_portal"))

    @app.route("/portal/resume", methods=["POST"])
    @customer_login_required
    def customer_portal_resume():
        phone = session.get("customer_phone")
        customer = get_customer_by_phone(phone)
        if not customer:
            return redirect(url_for("customer_login"))

        pause_id = int(request.form.get("pause_id", 0))
        resume_date_raw = request.form.get("resume_date", "")

        try:
            today = date.today()
            resume_d = parse_date(resume_date_raw) if resume_date_raw else today

            pauses = get_pauses_for_customer(customer.id)
            pause_obj = next((p for p in pauses if p.id == pause_id), None)
            if not pause_obj:
                raise ValidationError("Pause record not found.")

            validate_resume(pause_obj, resume_d)
            resume_pause(pause_id, resume_d)
            flash(f"Delivery resumed! Tiffin service is active again from {resume_d.strftime('%b %d, %Y')}.", "success")
        except (ValidationError, ValueError) as e:
            flash(str(e), "danger")

        return redirect(url_for("customer_portal"))

    @app.route("/portal/change-plan", methods=["POST"])
    @customer_login_required
    def customer_portal_change_plan():
        phone = session.get("customer_phone")
        customer = get_customer_by_phone(phone)
        if not customer:
            return redirect(url_for("customer_login"))

        plan_id = int(request.form.get("plan_id", 0))
        try:
            update_customer_plan(customer.id, plan_id)
            updated_customer = get_customer_by_phone(phone)
            flash(f"Meal plan updated to '{updated_customer.plan.name}'! New monthly rate: {updated_customer.plan.monthly_price_formatted}.", "success")
        except (ValidationError, ValueError) as e:
            flash(str(e), "danger")

        return redirect(url_for("customer_portal"))

    @app.route("/portal/cancel", methods=["POST"])
    @customer_login_required
    def customer_portal_cancel():
        phone = session.get("customer_phone")
        customer = get_customer_by_phone(phone)
        if not customer:
            return redirect(url_for("customer_login"))

        end_date_raw = request.form.get("end_date", "")
        try:
            end_d = parse_date(end_date_raw) if end_date_raw else date.today()
            if end_d < customer.start_date:
                raise ValidationError("End date cannot be prior to subscription start date.")
            end_subscription(customer.phone, end_d)
            flash(f"Subscription scheduled to end on {end_d.strftime('%b %d, %Y')}. Food will be delivered up through this date.", "warning")
        except (ValidationError, ValueError) as e:
            flash(str(e), "danger")

        return redirect(url_for("customer_portal"))

    @app.route("/portal/reactivate", methods=["POST"])
    @customer_login_required
    def customer_portal_reactivate():
        phone = session.get("customer_phone")
        customer = get_customer_by_phone(phone)
        if not customer:
            return redirect(url_for("customer_login"))

        try:
            reactivate_subscription(customer.phone)
            flash("Subscription reactivated! Your weekday lunch deliveries will continue.", "success")
        except (ValidationError, ValueError) as e:
            flash(str(e), "danger")

        return redirect(url_for("customer_portal"))

    # ------------------------------------------------------------------------
    # Delivery Notification Service & Scheduler
    # ------------------------------------------------------------------------
    @app.route("/notifications")
    @login_required
    def notifications_view():
        today = date.today()
        is_delivery, reason, eligible_customers = get_customers_due_delivery_today(today)
        logs = get_recent_notification_logs(limit=50)
        scheduler_info = get_scheduler_info()

        return render_template(
            "notifications.html",
            is_delivery_day=is_delivery,
            status_reason=reason,
            eligible_customers=eligible_customers,
            logs=logs,
            today_formatted=today.strftime("%A, %B %d, %Y"),
            scheduler_info=scheduler_info,
        )

    @app.route("/notifications/send-today", methods=["POST"])
    @login_required
    def send_notifications_today():
        today = date.today()
        result = dispatch_daily_delivery_notifications(on_date=today)
        if result["delivery_day"]:
            flash(
                f"9:00 AM notification batch dispatched! Notified {result['sent_count']} active subscribers due for delivery today.",
                "success",
            )
        else:
            flash(f"No notifications sent: {result['reason']}", "warning")

        return redirect(url_for("notifications_view"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
