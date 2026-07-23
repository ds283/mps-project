/*
 * Matching Workspace — top-level Matches list (matching_dashboard.html).
 *
 * Loads the card list via AJAX from cheap fields only; each card's expensive statistics bundle
 * (score/programme-pref/hint/delta/CATS/errors/warnings) is fetched separately, on demand, when
 * its "Compute summary statistics" button is pressed (or via "Compute all"). See
 * .prompts/matching-workspace/PLAN.md ("no new caching" non-goal).
 */
(function () {
    "use strict";

    function scriptRoot() {
        return typeof $SCRIPT_ROOT !== "undefined" ? $SCRIPT_ROOT : "";
    }

    function cardsFeedUrl() {
        var params = new URLSearchParams();
        if (typeof MDASH_PCLASS_ID !== "undefined" && MDASH_PCLASS_ID !== null) {
            params.set("pclass_id", MDASH_PCLASS_ID);
        } else if (typeof MDASH_YEAR !== "undefined" && MDASH_YEAR !== null) {
            params.set("year", MDASH_YEAR);
        }
        return scriptRoot() + "/admin/matches_v2_ajax?" + params.toString();
    }

    function loadCards() {
        var container = document.getElementById("mdash-cards");
        if (!container) {
            return;
        }

        fetch(cardsFeedUrl(), {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to load matches");
                }
                return response.json();
            })
            .then(function (data) {
                var cards = (data && data.cards) || [];
                if (cards.length === 0) {
                    container.innerHTML = '<div class="text-center text-secondary py-4">No matches to display.</div>';
                    return;
                }
                container.innerHTML = cards.map(function (card) {
                    return card.html;
                }).join("");
            })
            .catch(function () {
                container.innerHTML = '<div class="text-center text-danger py-4">Could not load the matches list.</div>';
            });
    }

    function computeStatistics(btn) {
        var matchId = btn.getAttribute("data-match-id");
        var target = document.getElementById("mdash-stats-" + matchId);
        if (!target) {
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Computing&hellip;';

        fetch(scriptRoot() + "/admin/match_statistics_ajax/" + matchId, {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to compute statistics");
                }
                return response.text();
            })
            .then(function (html) {
                target.innerHTML = html;
                btn.remove();
            })
            .catch(function () {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-sync-alt me-1"></i>Compute summary statistics';
            });
    }

    document.addEventListener("DOMContentLoaded", function () {
        loadCards();

        var container = document.getElementById("mdash-cards");
        if (container) {
            container.addEventListener("click", function (event) {
                var btn = event.target.closest(".mdash-compute-btn");
                if (btn) {
                    computeStatistics(btn);
                }
            });
        }

        var computeAllBtn = document.getElementById("mdash-compute-all-btn");
        if (computeAllBtn) {
            computeAllBtn.addEventListener("click", function () {
                document.querySelectorAll(".mdash-compute-btn").forEach(function (btn) {
                    computeStatistics(btn);
                });
            });
        }
    });
})();
