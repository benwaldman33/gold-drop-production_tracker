(function () {
  function initToolbar(root) {
    if (!root || root.getAttribute("data-batch-toolbar") !== "1") return;
    var entity = root.getAttribute("data-batch-entity");
    if (!entity) return;
    var scopeSel = root.getAttribute("data-batch-scope");
    var scope = scopeSel ? document.querySelector(scopeSel) : document;
    var sel = root.getAttribute("data-table-selector");
    var table = sel ? document.querySelector(sel) : null;
    var rootEl = table || scope;
    if (!rootEl) return;
    var returnTo =
      root.getAttribute("data-return-to") ||
      window.location.pathname + window.location.search;
    var minSel = parseInt(root.getAttribute("data-batch-min") || "2", 10) || 2;
    var btnAll = root.querySelector("[data-batch-select-all]");
    var btnNone = root.querySelector("[data-batch-select-none]");
    var btnEdit = root.querySelector("[data-batch-edit]");

    function cbs() {
      return rootEl.querySelectorAll(
        'input.batch-select-cb[data-batch-entity="' + entity + '"]'
      );
    }

    function refresh() {
      var list = Array.prototype.slice.call(cbs());
      var n = list.filter(function (c) {
        return c.checked;
      }).length;
      if (btnEdit) {
        btnEdit.disabled = n < minSel;
      }
    }

    if (btnAll) {
      btnAll.addEventListener("click", function () {
        cbs().forEach(function (c) {
          c.checked = true;
        });
        refresh();
      });
    }
    if (btnNone) {
      btnNone.addEventListener("click", function () {
        cbs().forEach(function (c) {
          c.checked = false;
        });
        refresh();
      });
    }
    cbs().forEach(function (c) {
      c.addEventListener("change", refresh);
    });

    if (btnEdit) {
      btnEdit.addEventListener("click", function () {
        var checked = Array.prototype.slice
          .call(cbs())
          .filter(function (c) {
            return c.checked;
          });
        if (checked.length < minSel) return;
        if (entity === "strains") {
          var u = new URL(
            window.location.origin + "/batch-edit/strains"
          );
          checked.forEach(function (c) {
            u.searchParams.append("pair", c.value);
          });
          u.searchParams.set("return_to", returnTo);
          window.location.href = u.pathname + u.search;
          return;
        }
        var ids = checked.map(function (c) {
          return c.value;
        });
        var u2 = new URL(
          window.location.origin + "/batch-edit/" + encodeURIComponent(entity)
        );
        u2.searchParams.set("ids", ids.join(","));
        u2.searchParams.set("return_to", returnTo);
        window.location.href = u2.pathname + u2.search;
      });
    }

    refresh();
  }

  document
    .querySelectorAll("[data-batch-toolbar]")
    .forEach(function (el) {
      initToolbar(el);
    });
})();
