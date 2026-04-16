from __future__ import annotations

from gold_drop.purchases import (
    biomass_budget_snapshot_for_purchase,
    enforce_weekly_biomass_purchase_limits,
)
from services.bootstrap_helpers import maintain_purchase_inventory_lots


BATCH_EDIT_META = {
    "runs": {"label": "Extraction runs", "perm": "can_edit"},
    "purchases": {"label": "Purchases", "perm": "can_edit_purchases"},
    "biomass": {"label": "Biomass pipeline", "perm": "can_edit"},
    "suppliers": {"label": "Suppliers", "perm": "can_edit"},
    "costs": {"label": "Cost entries", "perm": "can_edit"},
    "inventory_lots": {"label": "Inventory lots (on hand)", "perm": "can_edit_purchases"},
    "strains": {"label": "Strain names (lots)", "perm": "can_edit"},
}


def register_routes(app, root):
    @root.login_required
    def batch_edit(entity):
        return batch_edit_view(root, entity)

    app.add_url_rule("/batch-edit/<entity>", endpoint="batch_edit", view_func=batch_edit, methods=["GET", "POST"])


def safe_batch_return_url(root, raw: str) -> str:
    p = (raw or "").strip()
    if not p.startswith("/") or "\n" in p or "\r" in p or len(p) > 512:
        return root.url_for("dashboard")
    return p


def batch_edit_view(root, entity):
    meta = BATCH_EDIT_META.get(entity)
    if not meta:
        root.abort(404)
    perm = meta["perm"]
    if perm == "can_edit" and not root.current_user.can_edit:
        root.flash("Edit access required.", "error")
        return root.redirect(root.url_for("dashboard"))
    if perm == "can_edit_purchases" and not root.current_user.can_edit_purchases:
        root.flash("Purchase edit access required.", "error")
        return root.redirect(root.url_for("dashboard"))

    return_to = safe_batch_return_url(root, root.request.values.get("return_to") or "")

    if entity == "strains":
        pairs = root.request.values.getlist("pair") if root.request.method == "POST" else root.request.args.getlist("pair")
        pairs = [p for p in pairs if root.STRAIN_PAIR_SEP in (p or "")]
        if len(pairs) < 2:
            root.flash("Select at least two strain rows (same supplier bucket) to batch rename.", "warning")
            return root.redirect(return_to)
        if root.request.method == "GET":
            return root.render_template(
                "batch_edit.html",
                entity=entity,
                label=meta["label"],
                ids=[],
                strain_pairs=pairs,
                return_to=return_to,
                hte_pipeline_options=root._hte_pipeline_options(),
            )
        new_name = (root.request.form.get("new_strain_name") or "").strip()
        n, errs = root.apply_batch_strain_rename(pairs, new_name)
        if errs:
            for e in errs[:12]:
                root.flash(e, "error")
            root.db.session.rollback()
            return root.redirect(return_to)
        try:
            root.log_audit("update", "strain_rename", root.gen_uuid(), details=f"lots_updated={n}")
            root.db.session.commit()
            root.flash(f"Updated strain name on {n} lot(s).", "success")
        except Exception:
            root.db.session.rollback()
            root.app.logger.exception("batch strain rename")
            root.flash("Batch update failed.", "error")
        return root.redirect(return_to)

    ids = root.parse_uuid_ids(root.request.values.get("ids") or "")
    if len(ids) < 2:
        root.flash("Select at least two records to batch edit.", "warning")
        return root.redirect(return_to)

    if root.request.method == "GET":
        return root.render_template(
            "batch_edit.html",
            entity=entity,
            label=meta["label"],
            ids=ids,
            strain_pairs=[],
            return_to=return_to,
            hte_pipeline_options=root._hte_pipeline_options(),
        )

    try:
        if entity == "runs":
            n, errs = root.apply_batch_runs(ids, root.request.form)
            for e in errs[:15]:
                root.flash(e, "error")
            if n:
                root.log_audit("update", "run_batch", root.gen_uuid(), details=f"count={n}")
                root.db.session.commit()
                root.flash(f"Updated {n} run(s).", "success")
            else:
                root.db.session.rollback()
                if not errs:
                    root.flash("No changes applied (leave fields blank to skip).", "warning")
        elif entity == "purchases":
            n, errs, touched = root.apply_batch_purchases(ids, root.request.form)
            for e in errs[:15]:
                root.flash(e, "error")
            if touched:
                for p in touched:
                    maintain_purchase_inventory_lots(root, p)
                    new_snap = biomass_budget_snapshot_for_purchase(p)
                    enforce_weekly_biomass_purchase_limits(p, new_snap, enforce_cap=True)
            if n:
                root.log_audit("update", "purchase_batch", root.gen_uuid(), details=f"count={n}")
                root.db.session.commit()
                root.flash(f"Updated {n} purchase(s).", "success")
            else:
                root.db.session.rollback()
                if not errs:
                    root.flash("No changes applied.", "warning")
        elif entity == "biomass":
            n, errs = root.apply_batch_biomass(ids, root.request.form)
            for e in errs[:15]:
                root.flash(e, "error")
            if n:
                root.log_audit("update", "purchase_batch_biomass", root.gen_uuid(), details=f"count={n}")
                root.db.session.commit()
                root.flash(f"Updated {n} biomass row(s).", "success")
            else:
                root.db.session.rollback()
                if not errs:
                    root.flash("No changes applied.", "warning")
        elif entity == "suppliers":
            n, errs = root.apply_batch_suppliers(ids, root.request.form)
            for e in errs[:15]:
                root.flash(e, "error")
            if n:
                root.log_audit("update", "supplier_batch", root.gen_uuid(), details=f"count={n}")
                root.db.session.commit()
                root.flash(f"Updated {n} supplier(s).", "success")
            else:
                root.db.session.rollback()
                if not errs:
                    root.flash("No changes applied.", "warning")
        elif entity == "costs":
            n, errs = root.apply_batch_costs(ids, root.request.form)
            for e in errs[:15]:
                root.flash(e, "error")
            if n:
                root.log_audit("update", "cost_batch", root.gen_uuid(), details=f"count={n}")
                root.db.session.commit()
                root.flash(f"Updated {n} cost entr(y/ies).", "success")
            else:
                root.db.session.rollback()
                if not errs:
                    root.flash("No changes applied.", "warning")
        elif entity == "inventory_lots":
            n, errs = root.apply_batch_inventory_lots(ids, root.request.form)
            for e in errs[:15]:
                root.flash(e, "error")
            if n:
                root.log_audit("update", "inventory_lot_batch", root.gen_uuid(), details=f"count={n}")
                root.db.session.commit()
                root.flash(f"Updated {n} inventory lot(s).", "success")
            else:
                root.db.session.rollback()
                if not errs:
                    root.flash("No changes applied.", "warning")
    except ValueError as e:
        root.db.session.rollback()
        root.flash(str(e), "error")
        return root.redirect(return_to)
    except Exception:
        root.db.session.rollback()
        root.app.logger.exception("batch edit %s", entity)
        root.flash("Batch update failed.", "error")

    return root.redirect(return_to)
