# Return-link convention: `url` / `text`

When a page links to a secondary view that the user will return from (a preview, an editor, a
sub-list, a management page), the return target is threaded through **two query parameters**:

| Param  | Meaning                                                                                                                       |
|--------|-------------------------------------------------------------------------------------------------------------------------------|
| `url`  | The URL to return to (a same-site path). **This is the canonical name — never `return_to`, `back`, `next`, `redirect`, etc.** |
| `text` | Optional human-readable label for the "Back" link (e.g. `"project list"`).                                                    |

This is a long-standing repo convention (see `app/admin/assessments.py`, `app/admin/matching.py`,
and the `url_for(..., url=..., text=...)` links throughout `app/templates/faculty/`). New and
refactored code must follow it rather than inventing a new parameter name.

> Do not confuse `url`/`text` with `redirect_url()` (`app/shared/utils.py`), which is a *different*
> mechanism: it derives a fallback destination from `next` / the HTTP referrer / a default endpoint,
> and is a reasonable **default** for `url` when none was supplied — not a replacement for it.

## Producing the link (templates)

Pass `url` (and usually `text`) into the `url_for` for the target view:

```jinja2
<a href="{{ url_for('faculty.project_preview', id=data.id,
                    url=url_for('faculty.edit_projects'), text='project list') }}">Preview</a>
```

`url` is normally `url_for('some.view', …)` or `request.full_path` (to come back to the current
page with its query string intact).

## Consuming it (GET views)

Read both params, supplying a sensible default destination when `url` is absent, and forward them
to the template:

```python
url = request.args.get("url", None)
text = request.args.get("text", None)
if url is None:
    url = url_for("blueprint.default_view", …)
    text = "default label"
...
return render_template_context("…", url=url, text=text, …)
```

The template renders the Back control from these:

```jinja2
<a class="btn btn-sm btn-outline-secondary" href="{{ url }}">
    <i class="fas fa-arrow-left fa-fw"></i> {{ text|capitalize_first or 'Back' }}
</a>
```

The `capitalize_first` filter should be used as a defence against an older implementation/convention
where the return text was passed **without** a leading capital letter.

Note that `capitalize` must **not** be used, because this replaces capital letters everywhere
except the first character. That is **wrong** behaviour in this context.

## Replace the older system

Older templates used different markup for this UI element:

```HTML

<div class="top-return-link">
    <a class="text-decoration-none" href="{{ url }}">
        <i class="fas fa-backward"></i> Return to {{text}}
    </a>
</div>
```

Sometimes this appears both as a header and footer.

This can be replaced opportunistically if you are making edits to a template that uses this
convention. When doing so, replace only the header link; delete the footer link.

## Threading through POST forms

A page reached with `?url=…` that posts actions (create/edit/delete) must **preserve the return
target across the POST → redirect** so the user lands back where they started:

- Render `url` into every form as a hidden input: `<input type="hidden" name="url" value="{{ url }}">`.
- In the POST view read it back with `request.form.get("url")` and re-attach it to the redirect,
  e.g. `redirect(url_for("…", …, url=url))`.

`app/tickets/labels.py` + `app/templates/tickets/labels.html` are the canonical example of this
GET-render → hidden-input → POST-redirect round-trip (the `_back(tenant_id, url=None)` helper).

## Open-redirect safety

Because `url` becomes a redirect/`href` target, **validate it is a local same-site path** before
using it, and fall back to a safe default otherwise. Use the `labels.py` `_safe_return` pattern:

```python
def _safe_return(url):
    """Accept only a local, same-site path; otherwise fall back to a safe default."""
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return url_for("some.safe_default")
```

Never redirect to a raw externally-supplied `url` without this guard.
