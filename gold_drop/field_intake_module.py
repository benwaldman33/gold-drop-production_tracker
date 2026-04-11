from __future__ import annotations


def register_routes(app, root):
    @root.field_token_required
    def field_home(token):
        return field_home_view(root, token)

    @root.field_token_required
    def field_biomass_new(token):
        return field_biomass_new_view(root, token)

    @root.field_token_required
    def field_purchase_new(token):
        return field_purchase_new_view(root, token)

    @root.login_required
    def desk_field_purchase_submission():
        return desk_field_purchase_submission_view(root)

    @root.field_token_required
    def field_thanks(token):
        return field_thanks_view(root, token)

    app.add_url_rule("/field", endpoint="field_home", view_func=field_home)
    app.add_url_rule("/field/biomass/new", endpoint="field_biomass_new", view_func=field_biomass_new, methods=["GET", "POST"])
    app.add_url_rule("/field/purchase/new", endpoint="field_purchase_new", view_func=field_purchase_new, methods=["GET", "POST"])
    app.add_url_rule("/biomass-purchasing/new-submission", endpoint="desk_field_purchase_submission", view_func=desk_field_purchase_submission, methods=["GET", "POST"])
    app.add_url_rule("/field/thanks", endpoint="field_thanks", view_func=field_thanks)


def get_or_create_supplier_from_field_form(root, token):
    supplier_id = (root.request.form.get("supplier_id") or "").strip()
    new_name = (root.request.form.get("new_supplier_name") or "").strip()
    if supplier_id:
        supplier = root.db.session.get(root.Supplier, supplier_id)
        if not supplier:
            raise ValueError("Selected supplier was not found.")
        return supplier, False
    if not new_name:
        raise ValueError("Supplier is required (pick one or enter a new supplier name).")

    new_location = (root.request.form.get("new_supplier_location") or "").strip() or None
    new_phone = (root.request.form.get("new_supplier_phone") or "").strip() or None
    new_email = (root.request.form.get("new_supplier_email") or "").strip() or None
    existing = root.Supplier.query.filter(root.func.lower(root.Supplier.name) == new_name.lower()).first()
    if existing:
        return existing, False

    supplier = root.Supplier(
        name=new_name,
        location=new_location,
        contact_phone=new_phone,
        contact_email=new_email,
        is_active=True,
        notes="Created via field intake",
    )
    root.db.session.add(supplier)
    root.db.session.flush()
    root.log_audit(
        "create",
        "supplier",
        supplier.id,
        details=root.json.dumps({
            "source": "field_intake",
            "token_label": token.label,
            "name": new_name,
            "location": new_location,
            "contact_phone": new_phone,
            "contact_email": new_email,
        }),
        user_id=None,
    )
    return supplier, True


def get_or_create_supplier_from_desk_purchase_form(root):
    supplier_id = (root.request.form.get("supplier_id") or "").strip()
    new_name = (root.request.form.get("new_supplier_name") or "").strip()
    if supplier_id:
        supplier = root.db.session.get(root.Supplier, supplier_id)
        if not supplier:
            raise ValueError("Selected supplier was not found.")
        return supplier, False
    if not new_name:
        raise ValueError("Supplier is required (pick one or enter a new supplier name).")

    new_location = (root.request.form.get("new_supplier_location") or "").strip() or None
    new_phone = (root.request.form.get("new_supplier_phone") or "").strip() or None
    new_email = (root.request.form.get("new_supplier_email") or "").strip() or None
    existing = root.Supplier.query.filter(root.func.lower(root.Supplier.name) == new_name.lower()).first()
    if existing:
        return existing, False

    supplier = root.Supplier(
        name=new_name,
        location=new_location,
        contact_phone=new_phone,
        contact_email=new_email,
        is_active=True,
        notes="Created via office purchase intake",
    )
    root.db.session.add(supplier)
    root.db.session.flush()
    root.log_audit(
        "create",
        "supplier",
        supplier.id,
        details=root.json.dumps({
            "source": "desk_purchase_intake",
            "name": new_name,
            "location": new_location,
            "contact_phone": new_phone,
            "contact_email": new_email,
        }),
        user_id=root.current_user.id,
    )
    return supplier, True


def parse_field_purchase_intake_form_to_submission(root, supplier, *, source_token_id: str | None):
    purchase_date_raw = (root.request.form.get("purchase_date") or "").strip()
    if not purchase_date_raw:
        raise ValueError("Purchase Date is required.")
    purchase_date = root.datetime.strptime(purchase_date_raw, "%Y-%m-%d").date()

    delivery_date_raw = (root.request.form.get("delivery_date") or "").strip()
    harvest_date_raw = (root.request.form.get("harvest_date") or "").strip()
    delivery_date = root.datetime.strptime(delivery_date_raw, "%Y-%m-%d").date() if delivery_date_raw else None
    harvest_date = root.datetime.strptime(harvest_date_raw, "%Y-%m-%d").date() if harvest_date_raw else None

    estimated_potency_raw = (root.request.form.get("estimated_potency_pct") or "").strip()
    estimated_potency = float(estimated_potency_raw) if estimated_potency_raw else None
    if estimated_potency is not None and not (0 <= estimated_potency <= 100):
        raise ValueError("Estimated Potency must be between 0 and 100.")

    price_per_lb_raw = (root.request.form.get("price_per_lb") or "").strip()
    price_per_lb = float(price_per_lb_raw) if price_per_lb_raw else None
    if price_per_lb is not None and price_per_lb < 0:
        raise ValueError("Price/lb cannot be negative.")

    queue_placement = ((root.request.form.get("queue_placement") or "").strip() or None)
    if queue_placement and queue_placement not in ("aggregate", "indoor", "outdoor"):
        raise ValueError("Queue Placement must be Aggregate, Indoor, or Outdoor.")

    lots = []
    for strain, weight_raw in zip(root.request.form.getlist("lot_strains[]"), root.request.form.getlist("lot_weights[]")):
        strain = (strain or "").strip()
        weight_raw = (weight_raw or "").strip()
        if not strain and not weight_raw:
            continue
        if weight_raw:
            try:
                weight = float(weight_raw)
            except ValueError:
                raise ValueError("Lot weight must be a number.")
            if weight <= 0:
                raise ValueError("Lot weight must be greater than 0.")
        else:
            weight = None
        lots.append({"strain": strain or None, "weight_lbs": weight})

    supplier_photos = root.request.files.getlist("supplier_photos")
    biomass_photos = root.request.files.getlist("biomass_photos")
    coa_photos = root.request.files.getlist("coa_photos")
    root._validate_field_intake_photo_bucket(supplier_photos, "Supplier / License photos")
    root._validate_field_intake_photo_bucket(biomass_photos, "Biomass photos")
    root._validate_field_intake_photo_bucket(coa_photos, "Testing / COA photos")
    saved_supplier_paths = root._save_field_photos(supplier_photos, prefix="purchase-supplier")
    saved_biomass_paths = root._save_field_photos(biomass_photos, prefix="purchase-biomass")
    saved_coa_paths = root._save_field_photos(coa_photos, prefix="purchase-coa")
    all_paths = saved_supplier_paths + saved_biomass_paths + saved_coa_paths

    return root.FieldPurchaseSubmission(
        source_token_id=source_token_id,
        supplier_id=supplier.id,
        purchase_date=purchase_date,
        delivery_date=delivery_date,
        harvest_date=harvest_date,
        estimated_potency_pct=estimated_potency,
        price_per_lb=price_per_lb,
        storage_note=((root.request.form.get("storage_note") or "").strip() or None),
        license_info=((root.request.form.get("license_info") or "").strip() or None),
        queue_placement=queue_placement,
        coa_status_text=((root.request.form.get("coa_status_text") or "").strip() or None),
        notes=((root.request.form.get("notes") or "").strip() or None),
        lots_json=root.json.dumps(lots),
        photos_json=(root.json.dumps(all_paths) if all_paths else None),
        supplier_photos_json=(root.json.dumps(saved_supplier_paths) if saved_supplier_paths else None),
        biomass_photos_json=(root.json.dumps(saved_biomass_paths) if saved_biomass_paths else None),
        coa_photos_json=(root.json.dumps(saved_coa_paths) if saved_coa_paths else None),
        status="pending",
    ), lots, all_paths


def field_home_view(root, token):
    return root.render_template("field_home.html", token_value=root._get_field_token_value(), token=token)


def field_biomass_new_view(root, token):
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    if root.request.method == "POST":
        try:
            supplier, _created = get_or_create_supplier_from_field_form(root, token)
            availability_raw = (root.request.form.get("availability_date") or "").strip()
            if not availability_raw:
                raise ValueError("Availability Date is required.")
            availability_date = root.datetime.strptime(availability_raw, "%Y-%m-%d").date()

            stage = (root.request.form.get("stage") or "declared").strip()
            stage_to_status = {"declared": "declared", "testing": "in_testing"}
            status = stage_to_status.get(stage)
            if not status:
                raise ValueError("Stage must be Declared or Testing for field intake.")

            declared_weight_raw = (root.request.form.get("declared_weight_lbs") or "").strip()
            declared_weight = float(declared_weight_raw) if declared_weight_raw else 0.0
            if declared_weight < 0:
                raise ValueError("Declared Weight cannot be negative.")

            declared_price_raw = (root.request.form.get("declared_price_per_lb") or "").strip()
            declared_price = float(declared_price_raw) if declared_price_raw else None
            if declared_price is not None and declared_price < 0:
                raise ValueError("Declared $/lb cannot be negative.")

            potency_raw = (root.request.form.get("estimated_potency_pct") or "").strip()
            estimated_potency = float(potency_raw) if potency_raw else None
            if estimated_potency is not None and not (0 <= estimated_potency <= 100):
                raise ValueError("Estimated Potency must be between 0 and 100.")

            photos = root.request.files.getlist("photos")
            root._validate_field_intake_photo_bucket(photos, "Photos")
            saved_photo_paths = root._save_field_photos(photos, prefix="biomass")
            strain_name = (root.request.form.get("strain_name") or "").strip() or None

            purchase = root.Purchase(
                supplier_id=supplier.id,
                availability_date=availability_date,
                purchase_date=availability_date,
                declared_weight_lbs=declared_weight,
                stated_weight_lbs=declared_weight,
                declared_price_per_lb=declared_price,
                stated_potency_pct=estimated_potency,
                testing_timing=(root.request.form.get("testing_timing") or "before_delivery").strip() or "before_delivery",
                testing_status=(root.request.form.get("testing_status") or "pending").strip() or "pending",
                status=status,
                field_photo_paths_json=(root.json.dumps(saved_photo_paths) if saved_photo_paths else None),
                notes=((root.request.form.get("notes") or "").strip() or None),
            )
            root.db.session.add(purchase)
            root.db.session.flush()
            purchase.batch_id = root._ensure_unique_batch_id(
                root._generate_batch_id(supplier.name, availability_date, declared_weight),
                exclude_purchase_id=purchase.id,
            )
            if strain_name:
                root.db.session.add(root.PurchaseLot(
                    purchase_id=purchase.id,
                    strain_name=strain_name,
                    weight_lbs=declared_weight,
                    remaining_weight_lbs=declared_weight,
                    potency_pct=estimated_potency,
                ))
            root.log_audit(
                "create",
                "purchase",
                purchase.id,
                details=root.json.dumps({
                    "source": "field_intake",
                    "pipeline_stage": status,
                    "token_label": token.label,
                    "supplier": supplier.name,
                    "photos_count": len(saved_photo_paths),
                }),
                user_id=None,
            )
            root.db.session.commit()
            return root.redirect(root.url_for("field_thanks", kind="biomass", t=root._get_field_token_value()))
        except ValueError as exc:
            root.db.session.rollback()
            root.flash(str(exc), "error")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("Field biomass intake failed")
            root.flash("Could not submit. Please check your inputs and try again.", "error")

    return root.render_template(
        "field_biomass_form.html",
        token_value=root._get_field_token_value(),
        suppliers=suppliers,
        today=root.date.today(),
        field_photo_max=int(root.app.config.get("FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET", 30)),
    )


def field_purchase_new_view(root, token):
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    if root.request.method == "POST":
        try:
            supplier, _created = get_or_create_supplier_from_field_form(root, token)
            submission, lots, all_paths = parse_field_purchase_intake_form_to_submission(root, supplier, source_token_id=token.id)
            root.db.session.add(submission)
            root.db.session.flush()
            root.log_audit(
                "create",
                "field_purchase_submission",
                submission.id,
                details=root.json.dumps({
                    "source": "field_intake",
                    "token_label": token.label,
                    "supplier": supplier.name,
                    "lots_count": len(lots),
                    "photos_count": len(all_paths),
                }),
                user_id=None,
            )
            root.db.session.commit()
            root.notify_slack(f"New field purchase submission from {supplier.name}: {len(lots)} lot row(s), pending review.")
            return root.redirect(root.url_for("field_thanks", kind="purchase", t=root._get_field_token_value()))
        except ValueError as exc:
            root.db.session.rollback()
            root.flash(str(exc), "error")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("Field purchase intake failed")
            root.flash("Could not submit. Please check your inputs and try again.", "error")

    return root.render_template(
        "field_purchase_form.html",
        token_value=root._get_field_token_value(),
        suppliers=suppliers,
        today=root.date.today(),
        field_photo_max=int(root.app.config.get("FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET", 30)),
    )


def desk_field_purchase_submission_view(root):
    if not root.current_user.can_edit_purchases:
        root.flash("You don't have permission to submit purchase proposals.", "error")
        return root.redirect(root.url_for("biomass_purchasing_dashboard"))
    suppliers = root.Supplier.query.filter_by(is_active=True).order_by(root.Supplier.name).all()
    if root.request.method == "POST":
        try:
            supplier, _created = get_or_create_supplier_from_desk_purchase_form(root)
            submission, lots, all_paths = parse_field_purchase_intake_form_to_submission(root, supplier, source_token_id=None)
            root.db.session.add(submission)
            root.db.session.flush()
            root.log_audit(
                "create",
                "field_purchase_submission",
                submission.id,
                details=root.json.dumps({
                    "source": "desk_purchase_intake",
                    "supplier": supplier.name,
                    "lots_count": len(lots),
                    "photos_count": len(all_paths),
                }),
                user_id=root.current_user.id,
            )
            root.db.session.commit()
            root.notify_slack(
                f"New office purchase submission from {supplier.name} ({root.current_user.display_name}): "
                f"{len(lots)} lot row(s), pending review."
            )
            root.flash("Purchase proposal submitted for approval.", "success")
            return root.redirect(root.url_for("biomass_purchasing_dashboard"))
        except ValueError as exc:
            root.db.session.rollback()
            root.flash(str(exc), "error")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("Desk purchase intake failed")
            root.flash("Could not submit. Please check your inputs and try again.", "error")

    return root.render_template(
        "desk_purchase_intake_form.html",
        suppliers=suppliers,
        today=root.date.today(),
        field_photo_max=int(root.app.config.get("FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET", 30)),
    )


def field_thanks_view(root, token):
    kind = (root.request.args.get("kind") or "").strip()
    return root.render_template("field_thanks.html", kind=kind, token_value=root._get_field_token_value())
