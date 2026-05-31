# Convenor CTA banner architecture

## Rule

CTA (call-to-action) alert banners on convenor inspector pages **must** be rendered via the
`render_convenor_actions` macro in `app/templates/macros.html`. Do **not** write raw alert HTML
directly into templates for this purpose.

## How it works

**Model layer** — `app/models/markingevent.py`:

- `ConvenorActionButton` — a single button or link: `label`, `url`, `method` ("GET"/"POST"),
  `outline` (True → `btn-outline-<severity>`), `icon` (FA name without `fa-`, e.g. `"search"`).
- `ConvenorAction` — one banner: `severity`, `title`, `description`, `icon` (FA name, default
  `"exclamation-circle"`), `buttons` (list of `ConvenorActionButton`).

**Macro** — `render_convenor_actions(actions, form=none)` in `app/templates/macros.html`:

Renders each action as:
```
alert alert-<severity>  d-flex align-items-center gap-3
  fa-<icon> fa-lg flex-shrink-0
  flex-grow-1: <strong>title</strong> &mdash; description
  [buttons: GET → <a>, POST → <form> using form.hidden_tag()]
```

## View function pattern

Build a `banners` list of `ConvenorAction` objects in the view, then pass `banners=banners,
form=ActionForm()` to the template. One shared `ActionForm()` supplies the CSRF token for all
POST buttons on the page.

```python
from ..models.markingevent import ConvenorAction, ConvenorActionButton

banners = []
if some_condition:
    banners.append(ConvenorAction(
        severity="danger", icon="paper-plane",
        title="N reports ready to distribute",
        description="Assessors cannot begin marking until notified.",
        buttons=[
            ConvenorActionButton(label="View reports", outline=True, icon="search", url=view_url),
            ConvenorActionButton(label="Distribute all", icon="paper-plane", method="POST", url=action_url),
        ],
    ))
```

## Template pattern

```jinja2
{% from "macros.html" import render_convenor_actions %}
…
{% if banners %}
    <div class="mt-3 mb-2">
        {{ render_convenor_actions(banners, form=form) }}
    </div>
{% endif %}
```

## What this does NOT cover

- Informational notices that use `icon_block` (e.g. "event is closed") — these are passive and
  do not require action; keep them as direct `icon_block` calls.
- The `web_validation_failures` card in `marking_reports_inspector.html` — it has a
  per-report tabular structure that cannot be expressed as a flat `ConvenorAction`.
