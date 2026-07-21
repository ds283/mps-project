/*
 * Shared journal drawer + quick-add modal wiring.
 *
 * Any page that includes convenor/journal/_drawer.html and
 * convenor/journal/_add_modal.html (see .prompts/journal-redesign/04-shared-drawer.md)
 * should also load this script. It has no page-specific knowledge: it discovers
 * triggers by their data-bs-toggle/data-student-id attributes.
 */
(function () {
    "use strict";

    function scriptRoot() {
        return typeof $SCRIPT_ROOT !== "undefined" ? $SCRIPT_ROOT : "";
    }

    function showToast(message, category) {
        var container = document.getElementById("journalToastContainer");
        if (!container) {
            container = document.createElement("div");
            container.id = "journalToastContainer";
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

    function loadDrawer(studentId, triggerEl) {
        var drawerEl = document.getElementById("journalDrawer");
        var bodyEl = document.getElementById("journalDrawerBody");
        var subtitleEl = document.getElementById("journalDrawerSubtitle");
        if (!drawerEl || !bodyEl) {
            return;
        }

        drawerEl.setAttribute("data-student-id", studentId);
        if (subtitleEl) {
            subtitleEl.textContent = (triggerEl && triggerEl.getAttribute("data-student-name")) || "";
        }
        bodyEl.innerHTML = '<div class="text-center text-secondary py-4"><i class="fas fa-spinner fa-spin"></i> Loading&hellip;</div>';

        var returnUrl = drawerEl.getAttribute("data-return-url") || window.location.href;
        var returnText = drawerEl.getAttribute("data-return-text") || document.title.trim();
        var params = new URLSearchParams({url: returnUrl, text: returnText});

        fetch(scriptRoot() + "/convenor/journal_drawer_ajax/" + studentId + "?" + params.toString(), {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load journal entries");
                }
                return response.text();
            })
            .then(function (html) {
                bodyEl.innerHTML = html;
                bindMarkReadForm(bodyEl, studentId);
            })
            .catch(function () {
                bodyEl.innerHTML = '<div class="text-danger small p-2">Could not load journal entries.</div>';
            });
    }

    function bindMarkReadForm(scope, studentId) {
        var form = scope.querySelector("#journalMarkReadForm");
        if (!form) {
            return;
        }

        form.addEventListener("submit", function (e) {
            e.preventDefault();

            fetch(scriptRoot() + "/convenor/journal_mark_all_read/" + studentId, {
                method: "POST",
                credentials: "same-origin",
                body: new FormData(form),
            })
                .then(function (response) {
                    return response.json();
                })
                .then(function (data) {
                    if (data.success) {
                        loadDrawer(studentId);
                        window.refreshJournalIndicators(studentId);
                        notifyJournalUpdated(studentId);
                    }
                });
        });
    }

    function notifyJournalUpdated(studentId) {
        document.dispatchEvent(new CustomEvent("journal:updated", {detail: {studentId: studentId}}));
    }

    function populateQuickAddModal(triggerEl) {
        var modalEl = document.getElementById("journalAddModal");
        if (!modalEl) {
            return;
        }

        var drawerEl = document.getElementById("journalDrawer");
        var studentId = (triggerEl && triggerEl.getAttribute("data-student-id")) || (drawerEl && drawerEl.getAttribute("data-student-id"));
        var studentName =
            (triggerEl && triggerEl.getAttribute("data-student-name")) ||
            (drawerEl && document.getElementById("journalDrawerSubtitle") && document.getElementById("journalDrawerSubtitle").textContent);

        var studentIdInput = modalEl.querySelector("#quickAddStudentId");
        var nameEl = modalEl.querySelector("#quickAddStudentName");
        var pickerWrap = modalEl.querySelector("#quickAddStudentPickerWrap");
        var picker = modalEl.querySelector("#quickAddStudentPicker");

        if (!studentId && picker) {
            // No student pre-scoped by the trigger (e.g. the Journal tab's "Add entry…"
            // button): show the in-modal picker and let the user choose one.
            if (pickerWrap) {
                pickerWrap.style.display = "";
            }
            if (typeof $ !== "undefined" && $.fn.select2) {
                $(picker).val(null).trigger("change");
            } else {
                picker.value = "";
            }
            if (studentIdInput) {
                studentIdInput.value = "";
            }
            if (nameEl) {
                nameEl.textContent = "";
            }
        } else {
            if (pickerWrap) {
                pickerWrap.style.display = "none";
            }
            if (studentIdInput) {
                studentIdInput.value = studentId || "";
            }
            if (nameEl) {
                nameEl.textContent = studentName ? "— " + studentName : "";
            }
        }

        var alertEl = modalEl.querySelector("#journalAddFormAlert");
        if (alertEl) {
            alertEl.classList.add("d-none");
            alertEl.textContent = "";
        }

        var form = modalEl.querySelector("#journalAddForm");
        if (form) {
            form.reset();
        }
    }

    function flattenFormErrors(errors) {
        var messages = [];
        Object.keys(errors || {}).forEach(function (field) {
            (errors[field] || []).forEach(function (message) {
                messages.push(message);
            });
        });
        return messages;
    }

    function submitQuickAddForm(form) {
        var studentIdInput = form.querySelector("#quickAddStudentId");
        var studentId = studentIdInput ? studentIdInput.value : null;
        var alertEl = form.querySelector("#journalAddFormAlert");

        if (!studentId) {
            if (alertEl) {
                alertEl.textContent = "Please select a student.";
                alertEl.classList.remove("d-none");
            }
            return;
        }

        var submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
        }

        fetch(scriptRoot() + "/convenor/quick_add_journal_entry/" + studentId, {
            method: "POST",
            credentials: "same-origin",
            body: new FormData(form),
        })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                if (data.success) {
                    var modalEl = document.getElementById("journalAddModal");
                    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                    modal.hide();
                    showToast("Journal entry added.", "success");

                    var drawerEl = document.getElementById("journalDrawer");
                    if (drawerEl && drawerEl.getAttribute("data-student-id") === studentId) {
                        loadDrawer(studentId);
                    }
                    window.refreshJournalIndicators(studentId);
                    notifyJournalUpdated(studentId);
                } else if (alertEl) {
                    var messages = flattenFormErrors(data.errors);
                    alertEl.textContent = messages.length ? messages.join(" ") : "Could not save journal entry — please check the form.";
                    alertEl.classList.remove("d-none");
                } else {
                    showToast("Could not save journal entry — please check the form.", "error");
                }
            })
            .catch(function () {
                showToast("Could not save journal entry due to a network error.", "error");
            })
            .finally(function () {
                if (submitBtn) {
                    submitBtn.disabled = false;
                }
            });
    }

    window.refreshJournalIndicators = function (studentId) {
        fetch(scriptRoot() + "/convenor/journal_counts_ajax/" + studentId, {credentials: "same-origin"})
            .then(function (response) {
                return response.json();
            })
            .then(function (counts) {
                var visible = counts.visible || 0;
                var unread = counts.unread || 0;

                document.querySelectorAll('.journal-indicator[data-student-id="' + studentId + '"]').forEach(function (el) {
                    var cnt = el.querySelector(".cnt");
                    if (cnt) {
                        cnt.textContent = visible;
                    }

                    el.classList.toggle("has-unread", unread > 0);
                    el.classList.toggle("muted", visible === 0);
                    el.title =
                        visible === 0
                            ? "No entries visible to you"
                            : visible + " visible journal " + (visible === 1 ? "entry" : "entries") + (unread ? ", " + unread + " unread" : "");

                    var dot = el.querySelector(".jdot");
                    if (unread > 0 && !dot) {
                        dot = document.createElement("span");
                        dot.className = "jdot";
                        el.appendChild(dot);
                    } else if (unread === 0 && dot) {
                        dot.remove();
                    }

                    if (visible > 0) {
                        el.setAttribute("data-bs-toggle", "offcanvas");
                        el.setAttribute("data-bs-target", "#journalDrawer");
                    } else {
                        el.removeAttribute("data-bs-toggle");
                        el.removeAttribute("data-bs-target");
                    }
                });
            });
    };

    document.addEventListener("DOMContentLoaded", function () {
        var drawerEl = document.getElementById("journalDrawer");
        if (drawerEl) {
            drawerEl.addEventListener("show.bs.offcanvas", function (event) {
                var trigger = event.relatedTarget;
                var studentId = trigger && trigger.getAttribute("data-student-id");
                if (studentId) {
                    loadDrawer(studentId, trigger);
                }
            });
        }

        var modalEl = document.getElementById("journalAddModal");
        if (modalEl) {
            modalEl.addEventListener("show.bs.modal", function (event) {
                populateQuickAddModal(event.relatedTarget);
            });

            if (typeof $ !== "undefined" && $.fn.select2) {
                $("#quickAddProjectClasses").select2({
                    theme: "bootstrap-5",
                    selectionCssClass: "select2--small",
                    dropdownCssClass: "select2--small",
                    placeholder: "Select project classes (optional)...",
                    dropdownParent: $("#journalAddModal"),
                });
                $("#quickAddEntryType").select2({
                    theme: "bootstrap-5",
                    selectionCssClass: "select2--small",
                    dropdownCssClass: "select2--small",
                    minimumResultsForSearch: -1,
                    dropdownParent: $("#journalAddModal"),
                });

                var studentPicker = modalEl.querySelector("#quickAddStudentPicker");
                if (studentPicker) {
                    $(studentPicker).select2({
                        theme: "bootstrap-5",
                        selectionCssClass: "select2--small",
                        dropdownCssClass: "select2--small",
                        placeholder: "Select a student...",
                        dropdownParent: $("#journalAddModal"),
                    });
                }
            }

            var pickerEl = modalEl.querySelector("#quickAddStudentPicker");
            if (pickerEl) {
                pickerEl.addEventListener("change", function () {
                    var studentIdInput = modalEl.querySelector("#quickAddStudentId");
                    var nameEl = modalEl.querySelector("#quickAddStudentName");
                    var selected = pickerEl.options[pickerEl.selectedIndex];

                    if (studentIdInput) {
                        studentIdInput.value = pickerEl.value;
                    }
                    if (nameEl) {
                        nameEl.textContent = pickerEl.value && selected ? "— " + selected.textContent : "";
                    }
                });
            }

            var addForm = modalEl.querySelector("#journalAddForm");
            if (addForm) {
                addForm.addEventListener("submit", function (e) {
                    e.preventDefault();
                    submitQuickAddForm(addForm);
                });
            }
        }
    });
})();
