/* ============================================================
   Pantry Assist — UI behavior
   Theme toggle, toasts, mobile nav, keyboard shortcuts,
   bulk selection, focus management
   ============================================================ */
(function () {
  "use strict";

  /* ---------- Theme ---------- */
  var THEME_KEY = "pantry-theme";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      btn.textContent = theme === "dark" ? "☀️" : "🌙";
      btn.title = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
      btn.setAttribute("aria-label", btn.title);
    }
  }

  function currentTheme() {
    var stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function initTheme() {
    applyTheme(currentTheme());
    var btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.addEventListener("click", function () {
        var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        localStorage.setItem(THEME_KEY, next);
        applyTheme(next);
        showToast("Theme switched to " + next + " mode", "success");
      });
    }
  }

  /* ---------- Toasts ---------- */
  function toastContainer() {
    var el = document.getElementById("toast-container");
    if (!el) {
      el = document.createElement("div");
      el.id = "toast-container";
      el.className = "toast-container";
      el.setAttribute("aria-live", "polite");
      document.body.appendChild(el);
    }
    return el;
  }

  function showToast(message, category, autohide) {
    if (!message) return;
    var container = toastContainer();
    var toast = document.createElement("div");
    toast.className = "toast " + (category || "info");
    toast.setAttribute("role", category === "error" ? "alert" : "status");

    var msg = document.createElement("div");
    msg.className = "toast-message";
    msg.textContent = message;

    var close = document.createElement("button");
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss notification");
    close.textContent = "×";
    close.addEventListener("click", function () { dismiss(toast); });

    toast.appendChild(msg);
    toast.appendChild(close);
    container.appendChild(toast);

    function dismiss(t) {
      t.style.transition = "opacity 200ms ease, transform 200ms ease";
      t.style.opacity = "0";
      t.style.transform = "translateX(16px)";
      setTimeout(function () { t.remove(); }, 200);
    }

    if (autohide !== false) {
      setTimeout(function () { dismiss(toast); }, 4200);
    }
    return toast;
  }

  /* Render server-side flash messages as toasts */
  function initFlashes() {
    var flashes = document.querySelectorAll("[data-flash]");
    flashes.forEach(function (f) {
      showToast(f.dataset.flash, f.dataset.category || "info");
      f.remove();
    });
  }

  /* ---------- Mobile nav ---------- */
  function initMobileNav() {
    var toggle = document.getElementById("nav-toggle");
    var links = document.getElementById("nav-links");
    if (!toggle || !links) return;
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.textContent = open ? "✕" : "☰";
    });
    links.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        links.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.textContent = "☰";
      });
    });
  }

  /* ---------- Keyboard shortcuts ---------- */
  function initShortcuts() {
    document.addEventListener("keydown", function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      var tag = (e.target.tagName || "").toLowerCase();
      var inField = tag === "input" || tag === "select" || tag === "textarea" || e.target.isContentEditable;
      if (inField) return;

      switch (e.key) {
        case "/":
          e.preventDefault();
          var search = document.querySelector('[name="search"], input[type="search"]');
          if (search) { search.focus(); search.select(); }
          break;
        case "n":
          var addLink = document.querySelector('[data-shortcut="new"]');
          if (addLink) { e.preventDefault(); window.location.href = addLink.getAttribute("href"); }
          break;
        case "?":
          e.preventDefault();
          showToast("Shortcuts: / search · n new item · ? help", "info");
          break;
      }
    });
  }

  /* ---------- Bulk selection ---------- */
  function initBulk() {
    var selectAlls = document.querySelectorAll(".select-all");
    var checkboxes = document.querySelectorAll(".row-checkbox");
    if (!checkboxes.length) return;

    function updateBar() {
      var checked = document.querySelectorAll(".row-checkbox:checked");
      var bar = document.getElementById("bulk-bar");
      var count = document.getElementById("bulk-count");
      var btn = document.getElementById("bulk-delete");
      if (bar) bar.classList.toggle("visible", checked.length > 0);
      if (count) count.textContent = checked.length + " selected";
      if (btn) btn.disabled = checked.length === 0;
    }

    selectAlls.forEach(function (selectAll) {
      selectAll.addEventListener("change", function () {
        var table = selectAll.closest("table");
        var scope = table ? table.querySelectorAll(".row-checkbox:not(.select-all)") : [];
        scope.forEach(function (cb) { cb.checked = selectAll.checked; });
        updateBar();
      });
    });

    checkboxes.forEach(function (cb) {
      cb.addEventListener("change", function () {
        var table = cb.closest("table");
        if (table) {
          var scope = table.querySelectorAll(".row-checkbox:not(.select-all)");
          var sa = table.querySelector(".select-all");
          if (sa) sa.checked = Array.from(scope).every(function (c) { return c.checked; });
        }
        updateBar();
      });
    });

    var bulkDelete = document.getElementById("bulk-delete");
    if (bulkDelete) {
      bulkDelete.addEventListener("click", function () {
        var ids = Array.from(document.querySelectorAll(".row-checkbox:checked")).map(function (cb) {
          return cb.value;
        });
        if (!ids.length) return;
        var names = Array.from(document.querySelectorAll(".row-checkbox:checked")).map(function (cb) {
          return cb.dataset.name || "";
        });
        var msg = "Delete " + ids.length + " item" + (ids.length > 1 ? "s" : "") + "?";
        if (ids.length === 1) msg = 'Delete "' + names[0] + '"?';
        if (!window.confirm(msg)) return;

        fetch("/api/v1/items/bulk-delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: ids.map(Number) }),
        })
          .then(function (res) {
            if (!res.ok) throw new Error("Request failed");
            return res.json();
          })
          .then(function (data) {
            showToast("Deleted " + data.deleted + " item" + (data.deleted > 1 ? "s" : ""), "success");
            ids.forEach(function (id) {
              var row = document.querySelector('tr[data-item-id="' + id + '"]');
              if (row) row.remove();
            });
            updateBar();
          })
          .catch(function () {
            showToast("Failed to delete items", "error");
          });
      });
    }

    updateBar();
  }

  /* ---------- Category collapse ---------- */
  function initCategoryToggles() {
    document.addEventListener("click", function (e) {
      var header = e.target.closest("[data-category-toggle]");
      if (!header) return;
      toggleCategory(header);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      var header = e.target.closest("[data-category-toggle]");
      if (!header) return;
      e.preventDefault();
      toggleCategory(header);
    });
  }

  function toggleCategory(header) {
    var body = header.parentElement.querySelector(".category-body");
    var chevron = header.querySelector(".category-chevron");
    if (!body) return;
    var collapsed = header.getAttribute("aria-expanded") === "false";
    header.setAttribute("aria-expanded", collapsed ? "true" : "false");
    body.style.display = collapsed ? "" : "none";
    if (chevron) chevron.textContent = collapsed ? "▾" : "▸";
  }

  /* ---------- Inline quantity edit ---------- */
  function initInlineQty() {
    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-qty-action]");
      if (!btn) return;
      var input = btn.closest(".inline-qty").querySelector(".qty-input");
      if (!input) return;
      var step = parseFloat(btn.dataset.qtyAction);
      var value = parseFloat(input.value) || 0;
      input.value = Math.max(0, Math.round((value + step) * 100) / 100);
      saveQty(input);
    });

    document.addEventListener("change", function (e) {
      if (e.target.classList && e.target.classList.contains("qty-input")) {
        saveQty(e.target);
      }
    });
  }

  function saveQty(input) {
    var row = input.closest("tr");
    if (!row) return;
    var id = row.dataset.itemId;
    var value = parseFloat(input.value) || 0;
    var original = row.dataset.qty;

    fetch("/api/v1/items/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantity: value }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("Save failed");
        row.dataset.qty = value;
        showToast("Quantity updated", "success");
      })
      .catch(function () {
        input.value = original;
        showToast("Failed to save quantity", "error");
      });
  }

  /* ---------- Focus management for modals ---------- */
  function trapFocus(overlay) {
    var focusables = overlay.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (!focusables.length) return;
    var first = focusables[0];
    var last = focusables[focusables.length - 1];

    overlay.addEventListener("keydown", function (e) {
      if (e.key !== "Tab") return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });
  }

  function initModals() {
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        document.querySelectorAll(".modal-overlay").forEach(function (m) {
          if (m.style.display !== "none") {
            var close = m.querySelector("[data-modal-close], .modal-close, .btn-text.secondary");
            if (close) close.click();
          }
        });
      }
    });
    document.addEventListener("DOMNodeInserted", function (e) {
      var overlay = e.target.querySelector && e.target.querySelector(".modal-overlay");
      if (overlay) trapFocus(overlay);
    });
  }

  /* ---------- htmx loading state ---------- */
  function initHtmxIndicator() {
    if (typeof htmx === "undefined") return;
    var defaultIndicator = '<span class="spinner htmx-indicator" aria-hidden="true"></span>';
    document.body.insertAdjacentHTML("beforeend", '<div id="htmx-global-indicator" class="htmx-indicator" style="position:fixed;top:calc(var(--nav-height) + 12px);left:50%;transform:translateX(-50%);z-index:2000;background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:8px 16px;box-shadow:var(--shadow-md);font-size:0.8125rem;display:inline-flex;align-items:center;gap:8px;">' + defaultIndicator + " Loading…</div>");

    var shown = 0;
    var el = document.getElementById("htmx-global-indicator");
    htmx.on("htmx:beforeRequest", function (e) {
      if (e.detail.elt && e.detail.elt.closest("[data-no-global-indicator]")) return;
      shown++;
      if (el) el.style.display = "inline-flex";
    });
    htmx.on("htmx:afterSwap", function () {
      shown = Math.max(0, shown - 1);
      if (el && shown === 0) el.style.display = "none";
      initBulk();
    });
    htmx.on("htmx:responseError", function () {
      shown = Math.max(0, shown - 1);
      if (el && shown === 0) el.style.display = "none";
    });
  }

  /* ---------- Boot ---------- */
  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initFlashes();
    initMobileNav();
    initShortcuts();
    initBulk();
    initInlineQty();
    initCategoryToggles();
    initModals();
    initHtmxIndicator();
  });
})();
