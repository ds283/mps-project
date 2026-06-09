# Phase 5a — Create `pclass_form.html`

**Prerequisite: Phase 1 is complete. `pclass_base.html` exists and is verified.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

Create a new base template `convenor/dashboard/pclass_form.html` that combines the
persistent project-class header and pill bar (from `pclass_base.html`) with the centred
card form layout (from `base_form.html`). This template will be used in a later phase by
all convenor form templates that currently extend `base_form.html`.

This phase creates and verifies the new base template only. No existing templates are
changed in this phase.

---

## Step 1 — Read before writing

Read these files in full before writing anything:

- `app/templates/base_form.html` — record every block it defines with its default content
- `app/templates/convenor/dashboard/pclass_base.html` — confirm the block structure,
  specifically that it overrides `pillblock` and leaves `bodyblock` free for child templates
- `app/templates/convenor/dashboard/nav.html` — confirm `pillblock` is the correct
  override point
- `app/templates/base_app.html` — confirm it defines `bodyblock`
- These three form templates that override non-standard blocks in `base_form.html`, to
  confirm `pclass_form.html`'s block defaults will satisfy them:
    - `app/templates/convenor/markingevent/edit_marking_event.html` — overrides `header`
      and `footer`
    - `app/templates/convenor/marking/remove_markers.html` — overrides `card_classes` and
      `card_header_classes`
    - Any other convenor form template identified in the Phase 0b reconnaissance that
      overrides a block other than `formtitle`, `form_content`, `scripts`, or `title`

---

## Step 2 — Create `pclass_form.html`

Create `app/templates/convenor/dashboard/pclass_form.html`.

### Inheritance

```jinja
{% extends "convenor/dashboard/pclass_base.html" %}
```

### Block structure

`pclass_form.html` must override `bodyblock` to reproduce the centred card layout from
`base_form.html` exactly. Copy the structural markup from `base_form.html` — do not
paraphrase or simplify it. The blocks it must define, with their `base_form.html` defaults:

| Block name             | Default content                                                          |
|------------------------|--------------------------------------------------------------------------|
| `header_margin_column` | `col-1`                                                                  |
| `header_body_column`   | `col-10`                                                                 |
| `header`               | _(empty)_                                                                |
| `margin_column`        | `col-1`                                                                  |
| `body_column`          | `col-10`                                                                 |
| `card_classes`         | `border-primary`                                                         |
| `card_header_classes`  | `bg-primary text-white`                                                  |
| `card_header`          | `<div class="card-header ...">{% block formtitle %}{% endblock %}</div>` |
| `formtitle`            | _(empty)_                                                                |
| `card_body_classes`    | _(empty)_                                                                |
| `form_content`         | _(empty)_                                                                |
| `footer`               | _(empty)_                                                                |

The `bodyblock` override in `pclass_form.html` must be a verbatim copy of `base_form.html`'s
`bodyblock`, not a reimplementation. Read `base_form.html` and copy it exactly.

### What `pclass_form.html` must NOT do

- Must not override `pillblock` — this is inherited from `pclass_base.html` and must
  not be touched
- Must not redefine `title` — child templates set this themselves
- Must not add any new blocks beyond those in `base_form.html`
- Must not import any macros or add any JavaScript

---

## Step 3 — Verification

Perform these checks by reading the files you have written:

1. **Inheritance chain**: Confirm the chain is:
   `pclass_form.html` → `pclass_base.html` → `nav.html` → `base_app.html` → `base.html`
   Each `extends` must point to the immediate parent only.

2. **Block completeness**: Grep `base_form.html` for `{% block`. List every block name
   found. Confirm every one of them is defined in `pclass_form.html` with the same default
   content. Any block present in `base_form.html` but absent from `pclass_form.html` is a
   defect that will break child templates.

3. **No pillblock override**: Confirm `pclass_form.html` does not contain `{% block pillblock %}`.

4. **Override compatibility**: For each of the three form templates identified in Step 1
   that override non-standard blocks, confirm that the block they override is defined in
   `pclass_form.html` with a compatible default. Specifically:
    - `edit_marking_event.html` overrides `header` and `footer` — both must exist in
      `pclass_form.html`
    - `remove_markers.html` overrides `card_classes` and `card_header_classes` — both must
      exist in `pclass_form.html`

5. **No regressions to `base_form.html`**: Confirm `base_form.html` is unchanged (same
   line count and content as before this phase).

Report the result of each check. If any check fails, fix it before finishing.