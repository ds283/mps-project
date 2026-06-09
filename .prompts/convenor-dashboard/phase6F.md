# Prompt F — Move "Reset popularity" to Popular projects card header

**Prerequisite: Prompt E is complete and verified.**

**No reconnaissance step required. Two surgical edits only.**

---

## Objective

Move the "Reset popularity" button from the lifecycle card's action buttons block into
the header of the Popular projects card, where it belongs alongside the data it affects.
The action buttons block in the lifecycle card becomes empty and is removed entirely.

---

## Edit 1 — Add "Reset popularity" to the Popular projects card header

In `app/templates/convenor/dashboard/status.html`, locate the Popular projects card
header (inside the `{% if pclass.publish %}` block in the right column):

```jinja
{# Before #}
<div class="card-header py-2">
    <span class="fw-semibold text-secondary small">
        <i class="fas fa-fire fa-fw"></i> Popular projects
    </span>
</div>
```

Replace with:

```jinja
{# After #}
<div class="card-header py-2 d-flex justify-content-between align-items-center">
    <span class="fw-semibold text-secondary small">
        <i class="fas fa-fire fa-fw"></i> Popular projects
    </span>
    <a href="{{ url_for('convenor.reset_popularity_data', id=config.id) }}"
       class="btn btn-xs btn-outline-secondary">
        <i class="fas fa-sync fa-fw"></i> Reset popularity
    </a>
</div>
```

---

## Edit 2 — Remove the now-empty action buttons block from the lifecycle card

Locate the action buttons block immediately before the closing `</div></div>{% endif %}`
of the lifecycle card body (the block added by Prompt B and left with only a comment
after Prompt E moved Close selections into the form):

```jinja
{# Remove this entire block #}
<div class="d-flex gap-1 flex-wrap mt-2">
    <a href="{{ url_for('convenor.reset_popularity_data', id=config.id) }}"
       class="btn btn-xs btn-outline-secondary">
        <i class="fas fa-sync fa-fw"></i> Reset popularity
    </a>
    {# Close selections has moved into the SELECTIONS_OPEN branch above #}
</div>
```

Remove the entire `<div>` including its contents. Do not replace it with anything.

---

## Verification

1. **`reset_popularity_data` appears exactly once**: Grep `status.html` for
   `reset_popularity_data`. Must return exactly one result, inside the Popular
   projects card header.

2. **Action buttons block gone**: Grep `status.html` for
   `d-flex gap-1 flex-wrap mt-2` in the vicinity of the lifecycle card closing tags.
   Must return zero results at that location. (The same class combination may appear
   elsewhere in the file — check the context of any results to confirm none are
   the removed block.)

3. **Popular projects card header has `d-flex justify-content-between`**: Grep
   `status.html` for `Popular projects`. Confirm the enclosing `card-header` div
   has `d-flex justify-content-between align-items-center`.

Report results of all three checks. Fix any failures before finishing.