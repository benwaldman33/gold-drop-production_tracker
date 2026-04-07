/**
 * Field intake photos: one native <input type="file"> per row (required for iOS
 * and many in-app WebViews — assigning input.files via DataTransfer often does
 * not submit). Each row: label opens the picker; Remove drops the row; form
 * submit strips empty rows.
 */
(function () {
  function filledCount(bucket) {
    var n = 0;
    bucket.querySelectorAll(".field-photo-row input[type=file]").forEach(function (inp) {
      if (inp.files && inp.files.length > 0) n += 1;
    });
    return n;
  }

  function bindSubmitCleanup(form) {
    if (!form || form.dataset.fieldPhotoCleanupBound === "1") return;
    form.dataset.fieldPhotoCleanupBound = "1";
    form.addEventListener("submit", function () {
      document.querySelectorAll("[data-field-photo-bucket] .field-photo-row").forEach(function (row) {
        var inp = row.querySelector("input[type=file]");
        if (!inp || !inp.files || !inp.files.length) row.remove();
      });
    });
  }

  function addRow(bucket, inputName, max) {
    if (filledCount(bucket) >= max) {
      window.alert(
        "You can add at most " + max + " photos in this section. Remove one to add another."
      );
      return;
    }
    var rowsEl = bucket.querySelector(".field-photo-rows");
    if (!rowsEl) return;

    var row = document.createElement("div");
    row.className = "field-photo-row";
    row.style.cssText =
      "display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 0;padding:10px;border:1px solid var(--dark-border, #2E3148);border-radius:8px;background:var(--dark-card, #1B1D2E);";

    var preview = document.createElement("div");
    preview.className = "field-photo-row-preview";
    preview.style.cssText =
      "min-width:52px;min-height:52px;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:6px;background:var(--dark-hover, #252840);font-size:0.72rem;color:var(--text-muted, #6B6975);padding:8px;text-align:center;flex:1 1 140px;";
    preview.textContent = "No photo yet";

    var input = document.createElement("input");
    input.type = "file";
    input.name = inputName;
    input.accept = "image/*";
    input.className = "field-photo-native-input";
    input.id =
      "fieldph_" +
      Date.now().toString(36) +
      "_" +
      Math.floor(Math.random() * 1e9).toString(36);

    var lab = document.createElement("label");
    lab.htmlFor = input.id;
    lab.className = "btn btn-secondary btn-sm";
    lab.textContent = "Take or choose photo";
    lab.style.cursor = "pointer";
    lab.style.display = "inline-flex";
    lab.style.alignItems = "center";
    lab.style.margin = "0";

    var rm = document.createElement("button");
    rm.type = "button";
    rm.className = "btn btn-secondary btn-sm";
    rm.textContent = "Remove";
    rm.addEventListener("click", function () {
      if (preview._objectUrl) {
        try {
          URL.revokeObjectURL(preview._objectUrl);
        } catch (e) {}
      }
      row.remove();
    });

    input.addEventListener("change", function () {
      if (preview._objectUrl) {
        try {
          URL.revokeObjectURL(preview._objectUrl);
        } catch (e) {}
        preview._objectUrl = null;
      }
      preview.innerHTML = "";
      if (!input.files || !input.files[0]) {
        preview.textContent = "No photo yet";
        return;
      }
      var f = input.files[0];
      var url = URL.createObjectURL(f);
      preview._objectUrl = url;
      var thumb = document.createElement("img");
      thumb.src = url;
      thumb.alt = "";
      thumb.style.cssText =
        "width:52px;height:52px;object-fit:cover;border-radius:6px;display:block;";
      preview.style.padding = "4px";
      preview.appendChild(thumb);
      var cap = document.createElement("div");
      cap.textContent = f.name;
      cap.style.cssText =
        "font-size:0.75rem;margin-top:4px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary, #9B99A1);";
      preview.appendChild(cap);
      var sz = document.createElement("div");
      sz.textContent =
        f.size >= 1048576
          ? (f.size / 1048576).toFixed(1) + " MB"
          : Math.round(f.size / 1024) + " KB";
      sz.style.cssText = "font-size:0.7rem;color:var(--text-muted, #6B6975);";
      preview.appendChild(sz);
    });

    row.appendChild(preview);
    row.appendChild(lab);
    row.appendChild(input);
    row.appendChild(rm);
    rowsEl.appendChild(row);
  }

  function initBucket(bucket) {
    var max = parseInt(bucket.getAttribute("data-max") || "30", 10);
    var inputName = bucket.getAttribute("data-input-name");
    if (!inputName) return;

    var fallback = bucket.querySelector(".field-photo-fallback");
    var addBtn = bucket.querySelector(".field-photo-add-btn");
    if (!addBtn) return;

    if (fallback && fallback.parentNode) {
      fallback.parentNode.removeChild(fallback);
    }

    addBtn.hidden = false;
    addBtn.textContent = "Add photo";
    addBtn.addEventListener("click", function () {
      addRow(bucket, inputName, max);
    });

    bindSubmitCleanup(bucket.closest("form"));
  }

  function run() {
    document.querySelectorAll("[data-field-photo-bucket]").forEach(initBucket);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
