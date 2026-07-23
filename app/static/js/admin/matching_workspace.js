/*
 * Matching Workspace — shared student drawer + unified role editor modal wiring.
 *
 * Loaded by app/templates/admin/matching_workspace/workspace.html. Any element carrying
 * data-bs-toggle="offcanvas" data-bs-target="#matchStudentDrawer" data-rec-id="..." opens the
 * student inspector for that MatchingRecord; any element carrying
 * data-bs-toggle="modal" data-bs-target="#matchRoleEditorModal" data-rec-id="..." opens the
 * unified role editor for that record. Content for both is populated by AJAX. An element
 * carrying data-bs-toggle="offcanvas" data-bs-target="#matchCommentsPanel" data-rec-id="..."
 * opens the review-comments panel pre-scoped to that record's "By assignment" tab.
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

                bindHintDropdowns(bodyEl, recId);

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

    function loadFacultyDrawer(facId, triggerEl) {
        var drawerEl = document.getElementById("matchFacultyDrawer");
        var bodyEl = document.getElementById("matchFacultyDrawerBody");
        var subtitleEl = document.getElementById("matchFacultyDrawerSubtitle");
        if (!drawerEl || !bodyEl) {
            return;
        }

        var attemptId = drawerEl.getAttribute("data-attempt-id");

        drawerEl.setAttribute("data-fac-id", facId);
        if (subtitleEl) {
            subtitleEl.textContent = (triggerEl && triggerEl.getAttribute("data-fac-name")) || "";
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
            })
            .catch(function () {
                bodyEl.innerHTML = '<div class="text-danger small p-2">Could not load faculty inspector.</div>';
            });
    }

    var facultyDrawerEl = document.getElementById("matchFacultyDrawer");
    if (facultyDrawerEl) {
        facultyDrawerEl.addEventListener("show.bs.offcanvas", function (event) {
            var trigger = event.relatedTarget;
            var facId = trigger && trigger.getAttribute("data-fac-id");
            if (facId) {
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
            })
            .catch(function () {
                contentEl.innerHTML = '<div class="modal-body text-danger small">Could not load the reassignment workspace.</div>';
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

    function bindCommentThreadActions(scope, attemptId) {
        scope.querySelectorAll(".mw-comment-reply-toggle").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var commentId = btn.getAttribute("data-comment-id");
                var box = scope.querySelector('.mw-comment-reply-box[data-comment-id="' + commentId + '"]');
                if (box) {
                    box.classList.toggle("d-none");
                }
            });
        });

        scope.querySelectorAll(".mw-comment-reply-submit").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var commentId = btn.getAttribute("data-comment-id");
                var box = scope.querySelector('.mw-comment-reply-box[data-comment-id="' + commentId + '"]');
                var textarea = box ? box.querySelector(".mw-comment-reply-body") : null;
                var body = textarea ? textarea.value.trim() : "";
                if (!body) {
                    return;
                }

                btn.disabled = true;

                fetch(scriptRoot() + "/admin/reply_match_comment/" + commentId, {
                    method: "POST",
                    credentials: "same-origin",
                    body: csrfFormData({body: body}),
                })
                    .then(function (response) {
                        return response.json();
                    })
                    .then(function (data) {
                        if (data.success) {
                            loadCommentsPanel(attemptId);
                        } else {
                            showToast(data.message || "Could not post this reply.", "error");
                            btn.disabled = false;
                        }
                    })
                    .catch(function () {
                        showToast("Could not post this reply due to a network error.", "error");
                        btn.disabled = false;
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
                            loadCommentsPanel(attemptId);
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

    function bindCommentComposer(formEl, attemptId) {
        if (!formEl) {
            return;
        }

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
                        loadCommentsPanel(attemptId);
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

    function selectAssignmentComposer(scope, recId, focusBody) {
        var tabBtn = document.getElementById("mwAssignmentTabBtn");
        if (tabBtn) {
            if (typeof bootstrap !== "undefined" && bootstrap.Tab) {
                bootstrap.Tab.getOrCreateInstance(tabBtn).show();
            } else {
                tabBtn.click();
            }
        }

        var select = scope.querySelector("#mwAssignmentComposerStudent");
        if (select) {
            select.value = recId;
            if (typeof $ !== "undefined" && $.fn.select2) {
                $(select).trigger("change.select2").trigger("change");
            } else {
                select.dispatchEvent(new Event("change"));
            }
        }

        if (focusBody) {
            var body = scope.querySelector("#mwAssignmentComposerBody");
            if (body) {
                window.setTimeout(function () {
                    body.focus();
                }, 150);
            }
        }
    }

    function loadCommentsPanel(attemptId, focusRecId, focusBody) {
        var panelEl = document.getElementById("matchCommentsPanel");
        var bodyEl = document.getElementById("matchCommentsPanelBody");
        if (!panelEl || !bodyEl) {
            return;
        }

        bodyEl.innerHTML = '<div class="text-center text-secondary py-4"><i class="fas fa-spinner fa-spin"></i> Loading&hellip;</div>';

        fetch(scriptRoot() + "/admin/match_comments_ajax/" + attemptId + "?" + returnParams().toString(), {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load review comments");
                }
                return response.text();
            })
            .then(function (html) {
                bodyEl.innerHTML = html;
                initCommentsSelect2(bodyEl, panelEl);
                bindCommentThreadActions(bodyEl, attemptId);
                bindCommentComposer(document.getElementById("mwGlobalComposerForm"), attemptId);
                bindCommentComposer(document.getElementById("mwAssignmentComposerForm"), attemptId);

                if (focusRecId) {
                    selectAssignmentComposer(bodyEl, focusRecId, focusBody);
                }
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
            if (attemptId) {
                loadCommentsPanel(attemptId, recId, focusBody);
            }
        });
    }
})();
