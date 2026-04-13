from __future__ import annotations


def register_routes(app, root):
    @root.login_required
    def costs_list():
        return costs_list_view(root)

    @root.editor_required
    def cost_new():
        return cost_new_view(root)

    @root.editor_required
    def cost_edit(entry_id):
        return cost_edit_view(root, entry_id)

    @root.editor_required
    def cost_delete(entry_id):
        return cost_delete_view(root, entry_id)

    app.add_url_rule("/costs", endpoint="costs_list", view_func=costs_list)
    app.add_url_rule("/costs/new", endpoint="cost_new", view_func=cost_new, methods=["GET", "POST"])
    app.add_url_rule("/costs/<entry_id>/edit", endpoint="cost_edit", view_func=cost_edit, methods=["GET", "POST"])
    app.add_url_rule("/costs/<entry_id>/delete", endpoint="cost_delete", view_func=cost_delete, methods=["POST"])


def costs_list_view(root):
    redir = root._list_filters_clear_redirect("costs_list")
    if redir:
        return redir
    m = root._list_filters_merge("costs_list", ("type", "start_date", "end_date"))
    cost_type = (m.get("type") or "").strip()
    start_raw = (m.get("start_date") or "").strip()
    end_raw = (m.get("end_date") or "").strip()
    try:
        start_date = root.datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = root.datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_date = None
        end_date = None
    query = root.CostEntry.query
    if cost_type:
        query = query.filter_by(cost_type=cost_type)
    if start_date:
        query = query.filter(root.CostEntry.end_date >= start_date)
    if end_date:
        query = query.filter(root.CostEntry.start_date <= end_date)
    entries = query.order_by(root.CostEntry.start_date.desc()).all()
    return root.render_template(
        "costs.html",
        entries=entries,
        cost_type=cost_type,
        solvent_total=sum(e.total_cost for e in root.CostEntry.query.filter_by(cost_type="solvent").all()),
        personnel_total=sum(e.total_cost for e in root.CostEntry.query.filter_by(cost_type="personnel").all()),
        overhead_total=sum(e.total_cost for e in root.CostEntry.query.filter_by(cost_type="overhead").all()),
        start_date=start_raw,
        end_date=end_raw,
        list_filters_active=bool(cost_type or start_raw or end_raw),
        clear_filters_url=root.url_for("costs_list", clear_filters=1),
    )


def cost_new_view(root):
    if root.request.method == "POST":
        try:
            entry = root.CostEntry(
                cost_type=root.request.form["cost_type"],
                name=root.request.form["name"].strip(),
                unit_cost=float(root.request.form.get("unit_cost") or 0) or None,
                unit=root.request.form.get("unit", "").strip() or None,
                quantity=float(root.request.form.get("quantity") or 0) or None,
                total_cost=float(root.request.form["total_cost"]),
                start_date=root.datetime.strptime(root.request.form["start_date"], "%Y-%m-%d").date(),
                end_date=root.datetime.strptime(root.request.form["end_date"], "%Y-%m-%d").date(),
                notes=root.request.form.get("notes", "").strip() or None,
                created_by=root.current_user.id,
            )
            root.db.session.add(entry)
            root.log_audit("create", "cost_entry", entry.id)
            root.db.session.commit()
            root.flash("Cost entry added.", "success")
            return root.redirect(root.url_for("costs_list"))
        except Exception as exc:
            root.db.session.rollback()
            root.flash(f"Error: {str(exc)}", "error")
    return root.render_template("cost_form.html", entry=None, today=root.date.today())


def cost_edit_view(root, entry_id):
    entry = root.db.session.get(root.CostEntry, entry_id)
    if not entry:
        root.flash("Cost entry not found.", "error")
        return root.redirect(root.url_for("costs_list"))
    if root.request.method == "POST":
        try:
            entry.cost_type = root.request.form["cost_type"]
            entry.name = root.request.form["name"].strip()
            entry.unit_cost = float(root.request.form.get("unit_cost") or 0) or None
            entry.unit = root.request.form.get("unit", "").strip() or None
            entry.quantity = float(root.request.form.get("quantity") or 0) or None
            entry.total_cost = float(root.request.form["total_cost"])
            entry.start_date = root.datetime.strptime(root.request.form["start_date"], "%Y-%m-%d").date()
            entry.end_date = root.datetime.strptime(root.request.form["end_date"], "%Y-%m-%d").date()
            entry.notes = root.request.form.get("notes", "").strip() or None
            root.log_audit("update", "cost_entry", entry.id)
            root.db.session.commit()
            root.flash("Cost entry updated.", "success")
            return root.redirect(root.url_for("costs_list"))
        except Exception as exc:
            root.db.session.rollback()
            root.flash(f"Error: {str(exc)}", "error")
    return root.render_template("cost_form.html", entry=entry, today=root.date.today())


def cost_delete_view(root, entry_id):
    entry = root.db.session.get(root.CostEntry, entry_id)
    if entry:
        root.log_audit("delete", "cost_entry", entry.id)
        root.db.session.delete(entry)
        root.db.session.commit()
        root.flash("Cost entry deleted.", "success")
    return root.redirect(root.url_for("costs_list"))
