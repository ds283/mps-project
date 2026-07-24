/*
 * Matching Workspace — shared student drawer + unified role editor modal wiring.
 *
 * Loaded by app/templates/admin/matching_workspace/workspace.html. Any element carrying
 * data-bs-toggle="offcanvas" data-bs-target="#matchStudentDrawer" data-rec-id="..." opens the
 * student inspector for that MatchingRecord; any element carrying
 * data-bs-toggle="modal" data-bs-target="#matchRoleEditorModal" data-rec-id="..." opens the
 * unified role editor for that record. Content for both is populated by AJAX. An element
 * carrying data-bs-toggle="offcanvas" data-bs-target="#matchCommentsPanel" data-rec-id="..."
 * opens the review-comments panel scoped to that record — its By-student tab shows only that
 * student's threads, and the composer posts against them.
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

    // The Student pane (Phase 2) is a server-rendered, paginated list, not a DataTable — the
    // current URL already carries view + filters + group_by + page + per_page, so a full reload
    // re-renders it in place. The Faculty pane still uses a DataTable (removed in a later phase),
    // so that branch is kept as the fast path while it still applies.
    function reloadWorkspace() {
        window.location.reload();
    }

    function reloadStudentTable() {
        if (window.matchStudentTable) {
            window.matchStudentTable.ajax.reload(null, false);
        } else {
            reloadWorkspace();
        }
    }

    // ── Drawer navigation chain ─────────────────────────────────────────────
    //
    // Cross-links open one inspector from another (an allocated-student chip in the faculty drawer
    // opens the student drawer, say). Bootstrap supports only one open offcanvas, so each hop hides
    // the current drawer before showing the next; this stack records the hops so the "Back" control
    // in the header can rewind them. Opening a drawer from the page itself resets the stack, so
    // "Back" renders only when the drawer was reached as part of a chain.

    var DRAWER_KINDS = {
        student: {
            elId: "matchStudentDrawer",
            backId: "matchStudentDrawerBack",
            subtitleId: "matchStudentDrawerSubtitle",
            idAttr: "data-rec-id",
            load: function (id, name) {
                loadDrawer(id, null, name);
            },
        },
        faculty: {
            elId: "matchFacultyDrawer",
            backId: "matchFacultyDrawerBack",
            subtitleId: "matchFacultyDrawerSubtitle",
            idAttr: "data-fac-id",
            load: function (id, name) {
                loadFacultyDrawer(id, null, name);
            },
        },
    };

    var drawerChain = [];
    var drawerChainNavigating = false;

    function captureDrawerState(kind) {
        var spec = DRAWER_KINDS[kind];
        var el = spec && document.getElementById(spec.elId);
        var id = el && el.getAttribute(spec.idAttr);
        if (!id) {
            return null;
        }
        var subtitleEl = document.getElementById(spec.subtitleId);
        return {kind: kind, id: id, name: subtitleEl ? subtitleEl.textContent : ""};
    }

    // Show the "Back" control for whichever drawer is on screen, labelled with the drawer we would
    // return to; hide it in every drawer when the chain is empty.
    function syncDrawerBackControls() {
        var previous = drawerChain.length ? drawerChain[drawerChain.length - 1] : null;

        Object.keys(DRAWER_KINDS).forEach(function (kind) {
            var backEl = document.getElementById(DRAWER_KINDS[kind].backId);
            if (!backEl) {
                return;
            }
            var labelEl = backEl.querySelector(".mw-drawer-back-label");
            if (previous) {
                if (labelEl) {
                    labelEl.textContent = previous.name || "Back";
                }
                backEl.setAttribute("title", "Back to " + (previous.name || "the previous inspector"));
                backEl.classList.remove("d-none");
            } else {
                backEl.classList.add("d-none");
            }
        });
    }

    function resetDrawerChain() {
        drawerChain = [];
        syncDrawerBackControls();
    }

    // Swap the drawer currently on screen (fromKind) for `target` = {kind, id, name}. When `push`
    // is set the outgoing drawer is recorded so that "Back" returns to it.
    function navigateToDrawer(target, fromKind, push) {
        var spec = DRAWER_KINDS[target.kind];
        var targetEl = spec && document.getElementById(spec.elId);
        if (!targetEl) {
            return;
        }

        if (push && fromKind) {
            var origin = captureDrawerState(fromKind);
            if (origin) {
                drawerChain.push(origin);
            }
        }

        var show = function () {
            drawerChainNavigating = false;
            spec.load(target.id, target.name);
            syncDrawerBackControls();
            bootstrap.Offcanvas.getOrCreateInstance(targetEl).show();
        };

        var fromSpec = fromKind && DRAWER_KINDS[fromKind];
        var fromEl = fromSpec && document.getElementById(fromSpec.elId);
        var fromInstance = fromEl && bootstrap.Offcanvas.getInstance(fromEl);
        if (fromInstance && fromEl.classList.contains("show")) {
            drawerChainNavigating = true;
            fromEl.addEventListener("hidden.bs.offcanvas", show, {once: true});
            fromInstance.hide();
        } else {
            show();
        }
    }

    Object.keys(DRAWER_KINDS).forEach(function (kind) {
        var spec = DRAWER_KINDS[kind];
        var drawerEl = document.getElementById(spec.elId);
        var backEl = document.getElementById(spec.backId);

        if (backEl) {
            backEl.addEventListener("click", function () {
                var previous = drawerChain.pop();
                if (previous) {
                    navigateToDrawer(previous, kind, false);
                }
            });
        }

        // Dismissing a drawer outright ends the chain; a hide that is part of a hop does not.
        // The persistent listener registered here runs before the one-shot handler installed by
        // navigateToDrawer, so drawerChainNavigating is still set when a hop is in flight.
        if (drawerEl) {
            drawerEl.addEventListener("hidden.bs.offcanvas", function () {
                if (!drawerChainNavigating) {
                    resetDrawerChain();
                }
            });
        }
    });

    // ── Student drawer ──────────────────────────────────────────────────────

    function loadDrawer(recId, triggerEl, name) {
        var drawerEl = document.getElementById("matchStudentDrawer");
        var bodyEl = document.getElementById("matchStudentDrawerBody");
        var subtitleEl = document.getElementById("matchStudentDrawerSubtitle");
        if (!drawerEl || !bodyEl) {
            return;
        }

        drawerEl.setAttribute("data-rec-id", recId);
        var studentName = name || (triggerEl && triggerEl.getAttribute("data-student-name")) || "";
        if (subtitleEl && studentName) {
            subtitleEl.textContent = studentName;
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

                bindHintDropdowns(bodyEl, recId);
                bindDrawerSwapRecords(bodyEl);

                var commentsLink = bodyEl.querySelector(".mw-drawer-open-comments");
                if (commentsLink) {
                    commentsLink.addEventListener("click", function () {
                        var targetRecId = commentsLink.getAttribute("data-rec-id");
                        var focusBody = commentsLink.getAttribute("data-comment-focus") === "1";
                        var drawerInstance = bootstrap.Offcanvas.getInstance(drawerEl);
                        if (drawerInstance) {
                            drawerEl.addEventListener(
                                "hidden.bs.offcanvas",
                                function () {
                                    openCommentsPanelForRecord(targetRecId, focusBody);
                                },
                                {once: true}
                            );
                            drawerInstance.hide();
                        } else {
                            openCommentsPanelForRecord(targetRecId, focusBody);
                        }
                    });
                }
            })
            .catch(function () {
                bodyEl.innerHTML = '<div class="text-danger small p-2">Could not load student inspector.</div>';
            });
    }

    // Bind the "Change hint" dropdowns inside the ranked-selection table. Each item POSTs the
    // new hint value, then repaints the drawer so the badge colour/label reflect the change.
    function bindHintDropdowns(scope, recId) {
        scope.querySelectorAll(".mw-set-hint").forEach(function (item) {
            item.addEventListener("click", function (e) {
                e.preventDefault();
                if (item.classList.contains("active")) {
                    return;
                }
                var selId = item.getAttribute("data-sel-id");
                var hint = item.getAttribute("data-hint");
                var csrfForm = scope.querySelector("#matchStudentDrawerCsrf");
                if (!selId || hint === null || !csrfForm) {
                    return;
                }

                fetch(scriptRoot() + "/admin/match_set_hint/" + recId + "/" + selId + "/" + hint, {
                    method: "POST",
                    credentials: "same-origin",
                    body: new FormData(csrfForm),
                })
                    .then(function (response) {
                        return response.json();
                    })
                    .then(function (data) {
                        if (data.success) {
                            showToast("Selection hint updated.", "success");
                            loadDrawer(recId);
                        } else {
                            showToast(data.message || "Could not update the selection hint.", "error");
                        }
                    })
                    .catch(function () {
                        showToast("Could not update the selection hint due to a network error.", "error");
                    });
            });
        });
    }

    // Sibling-allocation cards in the period-context header swap the drawer body to that other
    // MatchingRecord in place — no chain hop is pushed, since this stays within the same
    // student/drawer, just a different submission period.
    function bindDrawerSwapRecords(scope) {
        scope.querySelectorAll(".mw-drawer-swap-record").forEach(function (card) {
            card.addEventListener("click", function (e) {
                e.preventDefault();
                var targetRecId = card.getAttribute("data-rec-id");
                if (targetRecId) {
                    loadDrawer(targetRecId);
                }
            });
        });
    }

    var studentDrawerEl = document.getElementById("matchStudentDrawer");
    if (studentDrawerEl) {
        studentDrawerEl.addEventListener("show.bs.offcanvas", function (event) {
            var trigger = event.relatedTarget;
            var recId = trigger && trigger.getAttribute("data-rec-id");
            if (recId) {
                // Opened from the page rather than from another drawer: this is the root of a chain.
                resetDrawerChain();
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

    var ROLE_EDITOR_MULTISELECTS = ["responsible_supervisors", "supervisors", "markers"];

    function collectRoleEditorSelections(scope) {
        var selections = {};
        ROLE_EDITOR_MULTISELECTS.forEach(function (name) {
            var sel = scope.querySelector('select[name="' + name + '"]');
            if (sel) {
                selections[name] = Array.prototype.map.call(sel.selectedOptions, function (opt) {
                    return opt.value;
                });
            }
        });
        return selections;
    }

    function restoreRoleEditorSelections(scope, selections) {
        if (!selections || typeof $ === "undefined") {
            return;
        }
        ROLE_EDITOR_MULTISELECTS.forEach(function (name) {
            var sel = scope.querySelector('select[name="' + name + '"]');
            if (sel && selections[name]) {
                // val() silently drops values with no matching option, so selections that are
                // out of scope for the newly selected project fall away naturally
                $(sel).val(selections[name]).trigger("change");
            }
        });
    }

    function bindRoleEditorProjectChange(scope, recId) {
        var projSelect = scope.querySelector('select[name="project"]');
        if (!projSelect || typeof $ === "undefined") {
            return;
        }
        // reload the fragment when the project changes, so the scoped supervisor/marker
        // choice lists track the selected project; preserve in-progress selections where
        // they remain available
        $(projSelect).on("change", function () {
            loadRoleEditor(recId, projSelect.value, collectRoleEditorSelections(scope));
        });
    }

    function loadRoleEditor(recId, projectId, preservedSelections) {
        var contentEl = document.getElementById("matchRoleEditorModalContent");
        if (!contentEl) {
            return;
        }

        contentEl.innerHTML = '<div class="modal-body text-center text-secondary py-4"><i class="fas fa-spinner fa-spin"></i> Loading&hellip;</div>';

        var params = returnParams();
        if (projectId) {
            params.set("project_id", projectId);
        }

        fetch(scriptRoot() + "/admin/match_role_editor_ajax/" + recId + "?" + params.toString(), {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load role editor");
                }
                return response.text();
            })
            .then(function (html) {
                contentEl.innerHTML = html;
                initSelect2(contentEl);
                restoreRoleEditorSelections(contentEl, preservedSelections);
                bindRoleEditorForm(contentEl, recId);
                bindRoleEditorProjectChange(contentEl, recId);
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

    // ── Faculty drawer ──────────────────────────────────────────────────────

    function reloadFacultyTable() {
        if (window.matchFacultyTable) {
            window.matchFacultyTable.ajax.reload(null, false);
        }
    }

    function loadFacultyDrawer(facId, triggerEl, name) {
        var drawerEl = document.getElementById("matchFacultyDrawer");
        var bodyEl = document.getElementById("matchFacultyDrawerBody");
        var subtitleEl = document.getElementById("matchFacultyDrawerSubtitle");
        if (!drawerEl || !bodyEl) {
            return;
        }

        var attemptId = drawerEl.getAttribute("data-attempt-id");

        drawerEl.setAttribute("data-fac-id", facId);
        var facName = name || (triggerEl && triggerEl.getAttribute("data-fac-name")) || "";
        if (subtitleEl && facName) {
            subtitleEl.textContent = facName;
        }
        bodyEl.innerHTML = '<div class="text-center text-secondary py-4"><i class="fas fa-spinner fa-spin"></i> Loading&hellip;</div>';

        fetch(
            scriptRoot() + "/admin/match_faculty_drawer_ajax/" + attemptId + "/" + facId + "?" + returnParams().toString(),
            {credentials: "same-origin"}
        )
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load faculty inspector");
                }
                return response.text();
            })
            .then(function (html) {
                bodyEl.innerHTML = html;
                bindOpenStudentLinks(bodyEl, "faculty");
            })
            .catch(function () {
                bodyEl.innerHTML = '<div class="text-danger small p-2">Could not load faculty inspector.</div>';
            });
    }

    // Allocated-student chips and candidate names in the faculty drawer cross-link to the student
    // inspector; the hop is handed to navigateToDrawer so the student drawer gains a "Back" control
    // returning to the faculty drawer we came from.
    function bindOpenStudentLinks(scope, sourceKind) {
        scope.querySelectorAll(".mw-open-student").forEach(function (link) {
            link.addEventListener("click", function (e) {
                e.preventDefault();

                var recId = link.getAttribute("data-rec-id");
                if (!recId) {
                    return;
                }

                navigateToDrawer({kind: "student", id: recId, name: link.getAttribute("data-student-name") || ""}, sourceKind, true);
            });
        });
    }

    var facultyDrawerEl = document.getElementById("matchFacultyDrawer");
    if (facultyDrawerEl) {
        facultyDrawerEl.addEventListener("show.bs.offcanvas", function (event) {
            var trigger = event.relatedTarget;
            var facId = trigger && trigger.getAttribute("data-fac-id");
            if (facId) {
                resetDrawerChain();
                loadFacultyDrawer(facId, trigger);
            }
        });
    }

    // ── Faculty reassignment workspace ──────────────────────────────────────

    function bindAssignButtons(scope, attemptId, facId) {
        var buttons = scope.querySelectorAll(".mw-fac-assign-btn");
        buttons.forEach(function (btn) {
            btn.addEventListener("click", function () {
                var selectorId = btn.getAttribute("data-selector-id");
                var projectId = btn.getAttribute("data-project-id");
                var csrfForm = scope.querySelector("#matchFacultyAssignCsrf");
                if (!selectorId || !projectId || !csrfForm) {
                    return;
                }

                btn.disabled = true;

                fetch(
                    scriptRoot() + "/admin/faculty_reassign_assign/" + attemptId + "/" + facId + "/" + selectorId + "/" + projectId,
                    {method: "POST", credentials: "same-origin", body: new FormData(csrfForm)}
                )
                    .then(function (response) {
                        return response.json();
                    })
                    .then(function (data) {
                        if (data.success) {
                            showToast("Student reassigned.", "success");
                            reloadFacultyTable();
                            loadReassignWorkspace(attemptId, facId);

                            var drawerEl = document.getElementById("matchFacultyDrawer");
                            if (drawerEl && drawerEl.getAttribute("data-fac-id") === String(facId) && drawerEl.classList.contains("show")) {
                                loadFacultyDrawer(facId);
                            }
                        } else {
                            showToast(data.message || "Could not reassign this student.", "error");
                            btn.disabled = false;
                        }
                    })
                    .catch(function () {
                        showToast("Could not reassign this student due to a network error.", "error");
                        btn.disabled = false;
                    });
            });
        });
    }

    function loadReassignWorkspace(attemptId, facId) {
        var contentEl = document.getElementById("matchFacultyReassignModalContent");
        if (!contentEl) {
            return;
        }

        contentEl.innerHTML = '<div class="modal-body text-center text-secondary py-4"><i class="fas fa-spinner fa-spin"></i> Loading&hellip;</div>';

        fetch(
            scriptRoot() + "/admin/faculty_reassign_ajax/" + attemptId + "/" + facId + "?" + returnParams().toString(),
            {credentials: "same-origin"}
        )
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load reassignment workspace");
                }
                return response.text();
            })
            .then(function (html) {
                contentEl.innerHTML = html;
                bindAssignButtons(contentEl, attemptId, facId);
                bindReassignStudentLinks(contentEl);
            })
            .catch(function () {
                contentEl.innerHTML = '<div class="modal-body text-danger small">Could not load the reassignment workspace.</div>';
            });
    }

    // Currently-assigned students in the reassignment workspace cross-link to the student inspector,
    // mirroring the faculty drawer's allocated-student chips. A modal and an offcanvas cannot be
    // shown together, so the workspace is dismissed first; if the faculty drawer is still open
    // behind it, that drawer becomes the "Back" target for the student drawer we open.
    function bindReassignStudentLinks(scope) {
        scope.querySelectorAll(".mw-open-student").forEach(function (link) {
            link.addEventListener("click", function (e) {
                e.preventDefault();

                var recId = link.getAttribute("data-rec-id");
                if (!recId) {
                    return;
                }

                var target = {kind: "student", id: recId, name: link.getAttribute("data-student-name") || ""};
                var facultyEl = document.getElementById(DRAWER_KINDS.faculty.elId);
                var fromKind = facultyEl && facultyEl.classList.contains("show") ? "faculty" : null;

                var modalEl = document.getElementById("matchFacultyReassignModal");
                var modalInstance = modalEl && bootstrap.Modal.getInstance(modalEl);
                if (modalInstance && modalEl.classList.contains("show")) {
                    modalEl.addEventListener(
                        "hidden.bs.modal",
                        function () {
                            navigateToDrawer(target, fromKind, fromKind !== null);
                        },
                        {once: true}
                    );
                    modalInstance.hide();
                } else {
                    navigateToDrawer(target, fromKind, fromKind !== null);
                }
            });
        });
    }

    var reassignModalEl = document.getElementById("matchFacultyReassignModal");
    if (reassignModalEl) {
        reassignModalEl.addEventListener("show.bs.modal", function (event) {
            var trigger = event.relatedTarget;
            var facId = trigger && trigger.getAttribute("data-fac-id");
            var attemptId = reassignModalEl.getAttribute("data-attempt-id");
            if (facId) {
                reassignModalEl.setAttribute("data-fac-id", facId);
                loadReassignWorkspace(attemptId, facId);
            }
        });
    }

    // ── Review comments panel ───────────────────────────────────────────────

    function initCommentsSelect2(scope, panelEl) {
        if (typeof $ === "undefined" || !$.fn.select2) {
            return;
        }
        $(scope)
            .find("select.select2")
            .select2({
                selectionCssClass: "select2-small",
                dropdownCssClass: "select2-small",
                dropdownParent: $(panelEl),
                width: "100%",
            });
    }

    function csrfFormData(extra) {
        var csrfForm = document.getElementById("matchCommentsCsrfForm");
        var data = new FormData(csrfForm);
        if (extra) {
            Object.keys(extra).forEach(function (key) {
                data.append(key, extra[key]);
            });
        }
        return data;
    }

    // The panel's view state (resolved-state filter, scoped record, active tab) lives on the
    // offcanvas element so that a re-fetch after a mutation returns the user to exactly where they
    // were, rather than resetting to the default Global/Unresolved view.
    function commentsViewState(panelEl) {
        return {
            state: panelEl.getAttribute("data-state") || "unresolved",
            recordId: panelEl.getAttribute("data-record-id") || "",
            tab: panelEl.getAttribute("data-tab") || "global",
        };
    }

    function setCommentsViewState(panelEl, view) {
        panelEl.setAttribute("data-state", view.state || "unresolved");
        panelEl.setAttribute("data-tab", view.tab || "global");
        if (view.recordId) {
            panelEl.setAttribute("data-record-id", view.recordId);
        } else {
            panelEl.removeAttribute("data-record-id");
        }
    }

    function updateCommentBadges(data) {
        var unresolved = document.getElementById("matchCommentsUnresolvedBadge");
        if (unresolved && typeof data.unresolved_count !== "undefined") {
            unresolved.textContent = data.unresolved_count;
            unresolved.classList.toggle("d-none", !data.unresolved_count);
        }

        var fresh = document.getElementById("matchCommentsNewBadge");
        if (fresh && typeof data.new_count !== "undefined") {
            fresh.textContent = data.new_count + " new";
            fresh.classList.toggle("d-none", !data.new_count);
        }
    }

    function bindCommentThreadActions(scope, attemptId) {
        scope.querySelectorAll(".mw-comment-reply-toggle").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var commentId = btn.getAttribute("data-comment-id");
                var box = scope.querySelector('.mw-comment-reply-box[data-comment-id="' + commentId + '"]');
                if (box) {
                    box.classList.toggle("d-none");
                    var textarea = box.querySelector(".mw-comment-reply-body");
                    if (textarea && !box.classList.contains("d-none")) {
                        textarea.focus();
                    }
                }
            });
        });

        // "Post reply", "Reply and resolve" and "Reopen and reply" all hit the same endpoint with a
        // different transition; the reply and the thread state change commit together server-side
        scope.querySelectorAll(".mw-comment-reply-submit").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var commentId = btn.getAttribute("data-comment-id");
                var box = scope.querySelector('.mw-comment-reply-box[data-comment-id="' + commentId + '"]');
                var textarea = box ? box.querySelector(".mw-comment-reply-body") : null;
                var body = textarea ? textarea.value.trim() : "";
                if (!body) {
                    return;
                }

                var siblings = box ? Array.prototype.slice.call(box.querySelectorAll(".mw-comment-reply-submit")) : [btn];
                siblings.forEach(function (el) {
                    el.disabled = true;
                });

                fetch(scriptRoot() + "/admin/reply_match_comment/" + commentId, {
                    method: "POST",
                    credentials: "same-origin",
                    body: csrfFormData({body: body, transition: btn.getAttribute("data-transition") || "none"}),
                })
                    .then(function (response) {
                        return response.json();
                    })
                    .then(function (data) {
                        if (data.success) {
                            updateCommentBadges(data);
                            reloadCommentsPanel(attemptId);
                            reloadStudentTable();
                        } else {
                            showToast(data.message || "Could not post this reply.", "error");
                            siblings.forEach(function (el) {
                                el.disabled = false;
                            });
                        }
                    })
                    .catch(function () {
                        showToast("Could not post this reply due to a network error.", "error");
                        siblings.forEach(function (el) {
                            el.disabled = false;
                        });
                    });
            });
        });

        scope.querySelectorAll(".mw-comment-resolve-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var commentId = btn.getAttribute("data-comment-id");
                btn.disabled = true;

                fetch(scriptRoot() + "/admin/resolve_match_comment/" + commentId, {
                    method: "POST",
                    credentials: "same-origin",
                    body: csrfFormData(),
                })
                    .then(function (response) {
                        return response.json();
                    })
                    .then(function (data) {
                        if (data.success) {
                            updateCommentBadges(data);
                            reloadCommentsPanel(attemptId);
                            reloadStudentTable();
                        } else {
                            showToast(data.message || "Could not update this comment.", "error");
                            btn.disabled = false;
                        }
                    })
                    .catch(function () {
                        showToast("Could not update this comment due to a network error.", "error");
                        btn.disabled = false;
                    });
            });
        });
    }

    // Rewrite the filter-pill counts for the active tab. The pills reflect only what the visible tab
    // shows, and the per-tab counts are shipped once as JSON so a client-side tab switch needs no
    // re-fetch (which would also prematurely clear the "New" pills).
    function updatePillCounts(scope, tab) {
        var container = scope.querySelector("#mwCommentFilters");
        if (!container) {
            return;
        }
        var counts;
        try {
            counts = JSON.parse(container.getAttribute("data-pill-counts") || "{}")[tab];
        } catch (e) {
            counts = null;
        }
        if (!counts) {
            return;
        }
        container.querySelectorAll(".mw-comment-filter").forEach(function (pill) {
            var span = pill.querySelector(".mw-comment-filter-count");
            var key = pill.getAttribute("data-state");
            if (span && typeof counts[key] !== "undefined") {
                span.textContent = counts[key];
            }
        });
    }

    // Tab switching is done here rather than with bootstrap.Tab so the active tab can be part of
    // the persisted view state and the composer/banner/pills can follow it.
    function showCommentsTab(scope, panelEl, tab) {
        scope.querySelectorAll(".mw-comment-tab").forEach(function (btn) {
            btn.classList.toggle("active", btn.getAttribute("data-tab") === tab);
        });
        scope.querySelectorAll(".mw-comments-pane").forEach(function (pane) {
            pane.classList.toggle("d-none", pane.getAttribute("data-tab") !== tab);
        });

        var view = commentsViewState(panelEl);
        view.tab = tab;
        setCommentsViewState(panelEl, view);

        // the composer posts against whichever scope the visible tab represents; on the Global tab it
        // is always whole-match, even when the panel is scoped to a student for the list view
        var scopeInput = scope.querySelector("#mwComposerScope");
        if (scopeInput) {
            scopeInput.value = tab === "student" ? "assignment" : "global";
        }

        // student context (select or "Scoped to …" caption) belongs to the By-student tab only
        var studentCtx = scope.querySelector("#mwComposerStudentCtx");
        if (studentCtx) {
            studentCtx.classList.toggle("d-none", tab !== "student");
        }

        // the scope banner is a By-student affordance; hide it on the Global tab
        var scopeBanner = scope.querySelector("#mwCommentsScopeBanner");
        if (scopeBanner) {
            scopeBanner.classList.toggle("d-none", tab !== "student");
        }

        updatePillCounts(scope, tab);
    }

    // Filter pills, tab switches and inbox drill-in are all the same operation: change one piece of
    // view state, then re-fetch the fragment for it.
    function bindCommentNavigation(scope, panelEl, attemptId) {
        scope.querySelectorAll(".mw-comment-filter, .mw-comment-filter-link").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.preventDefault();
                var view = commentsViewState(panelEl);
                view.state = btn.getAttribute("data-state");
                setCommentsViewState(panelEl, view);
                reloadCommentsPanel(attemptId);
            });
        });

        scope.querySelectorAll(".mw-comment-tab").forEach(function (btn) {
            btn.addEventListener("click", function () {
                showCommentsTab(scope, panelEl, btn.getAttribute("data-tab"));
            });
        });

        scope.querySelectorAll(".mw-comment-open-student").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var view = commentsViewState(panelEl);
                view.recordId = btn.getAttribute("data-rec-id");
                view.tab = "student";
                setCommentsViewState(panelEl, view);
                reloadCommentsPanel(attemptId);
            });
        });

        var clearScope = scope.querySelector("#mwCommentsClearScope");
        if (clearScope) {
            clearScope.addEventListener("click", function () {
                var view = commentsViewState(panelEl);
                view.recordId = "";
                view.tab = "student";
                setCommentsViewState(panelEl, view);
                reloadCommentsPanel(attemptId);
            });
        }

        var inboxFilter = scope.querySelector("#mwInboxFilter");
        if (inboxFilter) {
            inboxFilter.addEventListener("input", function () {
                var needle = inboxFilter.value.trim().toLowerCase();
                scope.querySelectorAll(".mw-inbox-row").forEach(function (row) {
                    // a name search overrides the "first 25 only" cap, otherwise a match sitting in
                    // the hidden tail would look like no match at all
                    var name = (row.getAttribute("data-student-name") || "").toLowerCase();
                    var hidden = needle ? name.indexOf(needle) === -1 : row.classList.contains("mw-inbox-overflow");
                    row.classList.toggle("d-none", hidden);
                });
            });
        }

        var showMore = scope.querySelector("#mwInboxShowMore");
        if (showMore) {
            showMore.addEventListener("click", function () {
                scope.querySelectorAll(".mw-inbox-overflow").forEach(function (row) {
                    row.classList.remove("d-none");
                    row.classList.remove("mw-inbox-overflow");
                });
                showMore.classList.add("d-none");
            });
        }
    }

    function bindCommentComposer(scope, attemptId) {
        var formEl = scope.querySelector("#mwComposerForm");
        var toggle = scope.querySelector("#mwComposerToggle");
        var cancel = scope.querySelector("#mwComposerCancel");
        if (!formEl) {
            return;
        }

        // the composer stays collapsed to a button so it is always visible at the foot of the panel
        // without eating the height the thread list needs
        function expand(focus) {
            formEl.classList.remove("d-none");
            if (toggle) {
                toggle.classList.add("d-none");
            }
            if (focus) {
                var body = formEl.querySelector("#mwComposerBody");
                if (body) {
                    body.focus();
                }
            }
        }

        function collapse() {
            formEl.classList.add("d-none");
            if (toggle) {
                toggle.classList.remove("d-none");
            }
        }

        if (toggle) {
            toggle.addEventListener("click", function () {
                expand(true);
            });
        }
        if (cancel) {
            cancel.addEventListener("click", collapse);
        }
        scope.mwExpandComposer = expand;

        formEl.addEventListener("submit", function (e) {
            e.preventDefault();

            var submitBtn = formEl.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
            }

            fetch(scriptRoot() + "/admin/post_match_comment/" + attemptId, {
                method: "POST",
                credentials: "same-origin",
                body: new FormData(formEl),
            })
                .then(function (response) {
                    return response.json();
                })
                .then(function (data) {
                    if (data.success) {
                        updateCommentBadges(data);
                        reloadCommentsPanel(attemptId);
                        reloadStudentTable();
                    } else {
                        var messages = [];
                        Object.keys(data.errors || {}).forEach(function (field) {
                            (data.errors[field] || []).forEach(function (message) {
                                messages.push(message);
                            });
                        });
                        showToast(messages.length ? messages.join(" ") : data.message || "Could not post this comment.", "error");
                        if (submitBtn) {
                            submitBtn.disabled = false;
                        }
                    }
                })
                .catch(function () {
                    showToast("Could not post this comment due to a network error.", "error");
                    if (submitBtn) {
                        submitBtn.disabled = false;
                    }
                });
        });
    }

    // Stamp the read marker once the body has been delivered. The render used the *previous*
    // marker, so the "New" pills stay visible on the view that clears them.
    function markCommentsRead(attemptId) {
        fetch(scriptRoot() + "/admin/mark_match_comments_read/" + attemptId, {
            method: "POST",
            credentials: "same-origin",
            body: csrfFormData(),
        })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                if (data.success) {
                    updateCommentBadges(data);
                }
            })
            .catch(function () {
                /* a lost read receipt is not worth interrupting the user for */
            });
    }

    function reloadCommentsPanel(attemptId) {
        loadCommentsPanel(attemptId, null, false);
    }

    function loadCommentsPanel(attemptId, focusRecId, focusBody) {
        var panelEl = document.getElementById("matchCommentsPanel");
        var bodyEl = document.getElementById("matchCommentsPanelBody");
        if (!panelEl || !bodyEl) {
            return;
        }

        if (focusRecId) {
            setCommentsViewState(panelEl, {state: commentsViewState(panelEl).state, recordId: focusRecId, tab: "student"});
        }

        var view = commentsViewState(panelEl);
        var params = returnParams();
        params.set("state", view.state);
        params.set("tab", view.tab);
        if (view.recordId) {
            params.set("record_id", view.recordId);
        }

        bodyEl.innerHTML = '<div class="text-center text-secondary py-4"><i class="fas fa-spinner fa-spin"></i> Loading&hellip;</div>';

        fetch(scriptRoot() + "/admin/match_comments_ajax/" + attemptId + "?" + params.toString(), {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load review comments");
                }
                return response.text();
            })
            .then(function (html) {
                bodyEl.innerHTML = html;

                var root = bodyEl.querySelector("#mwComments");
                if (!root) {
                    return;
                }

                // the fragment is authoritative about scope — an unknown record id is dropped
                // server-side — so adopt what it actually rendered
                setCommentsViewState(panelEl, {
                    state: root.getAttribute("data-state"),
                    recordId: root.getAttribute("data-record-id"),
                    tab: root.getAttribute("data-tab"),
                });

                initCommentsSelect2(bodyEl, panelEl);
                bindCommentThreadActions(bodyEl, attemptId);
                bindCommentNavigation(bodyEl, panelEl, attemptId);
                bindCommentComposer(bodyEl, attemptId);
                showCommentsTab(bodyEl, panelEl, root.getAttribute("data-tab") || "global");

                if (focusBody && typeof bodyEl.mwExpandComposer === "function") {
                    bodyEl.mwExpandComposer(true);
                }

                markCommentsRead(attemptId);
            })
            .catch(function () {
                bodyEl.innerHTML = '<div class="text-danger small p-2">Could not load review comments.</div>';
            });
    }

    // Opens the comments panel scoped to one student's assignment from outside the panel itself
    // (e.g. the "View full conversation" link in the student drawer). Bootstrap's offcanvas
    // show() takes no relatedTarget, so the target record is stashed on the panel element and
    // picked up by the show.bs.offcanvas listener below.
    function openCommentsPanelForRecord(recId, focusBody) {
        var commentsPanelEl = document.getElementById("matchCommentsPanel");
        if (!commentsPanelEl) {
            return;
        }
        commentsPanelEl.setAttribute("data-pending-rec-id", recId);
        commentsPanelEl.setAttribute("data-pending-focus", focusBody ? "1" : "0");
        bootstrap.Offcanvas.getOrCreateInstance(commentsPanelEl).show();
    }
    window.matchWorkspaceOpenComments = openCommentsPanelForRecord;

    var commentsPanelEl = document.getElementById("matchCommentsPanel");
    if (commentsPanelEl) {
        commentsPanelEl.addEventListener("show.bs.offcanvas", function (event) {
            var attemptId = commentsPanelEl.getAttribute("data-attempt-id");
            var trigger = event.relatedTarget;
            var recId = trigger ? trigger.getAttribute("data-rec-id") : commentsPanelEl.getAttribute("data-pending-rec-id");
            var focusBody = trigger ? trigger.getAttribute("data-comment-focus") === "1" : commentsPanelEl.getAttribute("data-pending-focus") === "1";
            commentsPanelEl.removeAttribute("data-pending-rec-id");
            commentsPanelEl.removeAttribute("data-pending-focus");

            // every open starts from the default view: unresolved first, and scoped only if this
            // particular trigger asked for a student — otherwise a scope left over from a previous
            // open would silently hide most of the panel
            setCommentsViewState(commentsPanelEl, {
                state: "unresolved",
                recordId: recId || "",
                tab: recId ? "student" : "global",
            });

            if (attemptId) {
                loadCommentsPanel(attemptId, recId, focusBody);
            }
        });
    }
})();
