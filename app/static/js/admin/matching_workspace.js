/*
 * Matching Workspace — shared student drawer + unified role editor modal wiring.
 *
 * Loaded by app/templates/admin/matching_workspace/workspace.html. Any element carrying
 * data-bs-toggle="offcanvas" data-bs-target="#matchStudentDrawer" data-rec-id="..." opens the
 * student inspector for that MatchingRecord; any element carrying
 * data-bs-toggle="modal" data-bs-target="#matchRoleEditorModal" data-rec-id="..." opens the
 * unified role editor for that record. Content for both is populated by AJAX.
 */
(function () {
    "use strict";

    function scriptRoot() {
        return typeof $SCRIPT_ROOT !== "undefined" ? $SCRIPT_ROOT : "";
    }

    function returnParams() {
        var url = typeof MATCH_WORKSPACE_RETURN_URL !== "undefined" ? MATCH_WORKSPACE_RETURN_URL : window.location.href;
        var text = typeof MATCH_WORKSPACE_RETURN_TEXT !== "undefined" ? MATCH_WORKSPACE_RETURN_TEXT : document.title.trim();
        return new URLSearchParams({url: url || window.location.href, text: text || ""});
    }

    function showToast(message, category) {
        var container = document.getElementById("matchWorkspaceToastContainer");
        if (!container) {
            container = document.createElement("div");
            container.id = "matchWorkspaceToastContainer";
            container.className = "toast-container position-fixed bottom-0 end-0 p-3";
            container.style.zIndex = 1080;
            document.body.appendChild(container);
        }

        var toastEl = document.createElement("div");
        toastEl.className = "toast align-items-center text-bg-" + (category === "error" ? "danger" : "success") + " border-0";
        toastEl.setAttribute("role", "alert");
        toastEl.setAttribute("aria-live", "assertive");
        toastEl.setAttribute("aria-atomic", "true");
        toastEl.innerHTML =
            '<div class="d-flex">' +
            '<div class="toast-body"></div>' +
            '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
            "</div>";
        toastEl.querySelector(".toast-body").textContent = message;
        container.appendChild(toastEl);

        var toast = new bootstrap.Toast(toastEl, {delay: 4000});
        toastEl.addEventListener("hidden.bs.toast", function () {
            toastEl.remove();
        });
        toast.show();
    }

    function reloadStudentTable() {
        if (window.matchStudentTable) {
            window.matchStudentTable.ajax.reload(null, false);
        }
    }

    // ── Student drawer ──────────────────────────────────────────────────────

    function loadDrawer(recId, triggerEl) {
        var drawerEl = document.getElementById("matchStudentDrawer");
        var bodyEl = document.getElementById("matchStudentDrawerBody");
        var subtitleEl = document.getElementById("matchStudentDrawerSubtitle");
        if (!drawerEl || !bodyEl) {
            return;
        }

        drawerEl.setAttribute("data-rec-id", recId);
        if (subtitleEl) {
            subtitleEl.textContent = (triggerEl && triggerEl.getAttribute("data-student-name")) || "";
        }
        bodyEl.innerHTML = '<div class="text-center text-secondary py-4"><i class="fas fa-spinner fa-spin"></i> Loading&hellip;</div>';

        fetch(scriptRoot() + "/admin/match_student_drawer_ajax/" + recId + "?" + returnParams().toString(), {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load student inspector");
                }
                return response.text();
            })
            .then(function (html) {
                bodyEl.innerHTML = html;
            })
            .catch(function () {
                bodyEl.innerHTML = '<div class="text-danger small p-2">Could not load student inspector.</div>';
            });
    }

    var studentDrawerEl = document.getElementById("matchStudentDrawer");
    if (studentDrawerEl) {
        studentDrawerEl.addEventListener("show.bs.offcanvas", function (event) {
            var trigger = event.relatedTarget;
            var recId = trigger && trigger.getAttribute("data-rec-id");
            if (recId) {
                loadDrawer(recId, trigger);
            }
        });
    }

    // ── Unified role editor modal ───────────────────────────────────────────

    function initSelect2(scope) {
        if (typeof $ === "undefined" || !$.fn.select2) {
            return;
        }
        $(scope)
            .find("select.select2")
            .select2({
                selectionCssClass: "select2-small",
                dropdownCssClass: "select2-small",
                dropdownParent: $(scope).closest(".modal"),
            });
    }

    function bindRoleEditorForm(scope, recId) {
        var form = scope.querySelector("#matchRoleEditorForm");
        var alertEl = scope.querySelector("#matchRoleEditorAlert");
        if (!form) {
            return;
        }

        form.addEventListener("submit", function (e) {
            e.preventDefault();

            if (alertEl) {
                alertEl.classList.add("d-none");
                alertEl.textContent = "";
            }

            var submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
            }

            fetch(scriptRoot() + "/admin/edit_match_roles/" + recId, {
                method: "POST",
                credentials: "same-origin",
                body: new FormData(form),
            })
                .then(function (response) {
                    return response.json();
                })
                .then(function (data) {
                    if (data.success) {
                        var modalEl = document.getElementById("matchRoleEditorModal");
                        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                        modal.hide();
                        showToast("Roles updated.", "success");
                        reloadStudentTable();

                        var drawerEl = document.getElementById("matchStudentDrawer");
                        if (drawerEl && drawerEl.getAttribute("data-rec-id") === String(recId) && drawerEl.classList.contains("show")) {
                            loadDrawer(recId);
                        }
                    } else if (alertEl) {
                        var messages = [];
                        Object.keys(data.errors || {}).forEach(function (field) {
                            (data.errors[field] || []).forEach(function (message) {
                                messages.push(message);
                            });
                        });
                        alertEl.textContent = messages.length ? messages.join(" ") : data.message || "Could not save role changes.";
                        alertEl.classList.remove("d-none");
                    } else {
                        showToast(data.message || "Could not save role changes.", "error");
                    }
                })
                .catch(function () {
                    showToast("Could not save role changes due to a network error.", "error");
                })
                .finally(function () {
                    if (submitBtn) {
                        submitBtn.disabled = false;
                    }
                });
        });
    }

    function loadRoleEditor(recId) {
        var contentEl = document.getElementById("matchRoleEditorModalContent");
        if (!contentEl) {
            return;
        }

        contentEl.innerHTML = '<div class="modal-body text-center text-secondary py-4"><i class="fas fa-spinner fa-spin"></i> Loading&hellip;</div>';

        fetch(scriptRoot() + "/admin/match_role_editor_ajax/" + recId + "?" + returnParams().toString(), {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load role editor");
                }
                return response.text();
            })
            .then(function (html) {
                contentEl.innerHTML = html;
                initSelect2(contentEl);
                bindRoleEditorForm(contentEl, recId);
            })
            .catch(function () {
                contentEl.innerHTML = '<div class="modal-body text-danger small">Could not load the role editor.</div>';
            });
    }

    var roleEditorEl = document.getElementById("matchRoleEditorModal");
    if (roleEditorEl) {
        roleEditorEl.addEventListener("show.bs.modal", function (event) {
            var trigger = event.relatedTarget;
            var recId = trigger && trigger.getAttribute("data-rec-id");
            if (recId) {
                loadRoleEditor(recId);
            }
        });
    }
})();
