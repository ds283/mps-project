Clean up the SortableJS drag-and-drop implementation in the student bookmark reorder template. The file is
`app/templates/convenor/selector/bookmarks.html`.

**In the Jinja2 template:**

1. Currently the SortableJS library is imported using an explicit inline <script> tag. Elsewhere,
   this type of import is handled using a macro, so that all places where a library is used can be kept in sync.
   See, e.g., app/templates/bokeh.html`. Create a new macro file `sortable.html` and import the SortableJS library
   there.
2. Change `id="ranking"` to `class="ranking"` on the rank display span inside the `bookmark_projects` macro.
3. Add `data-id="{{ project.id }}"` to the outer row div (the one with `id="P-{{ project.id }}"`). Keep the existing
   `id` attribute — it may be used elsewhere.

**In the JavaScript block:**

3. Replace the `onSort` callback with `onEnd`, and add an early exit if the item was dropped back in its original
   position:
   ```javascript
   onEnd: function(e) {
       if (e.oldIndex === e.newIndex) return;
       // existing body
   }
   ```
4. Fix the rank display selector from `find('#ranking')` to `find('.ranking')`.
5. Declare `rspan` with `const`.
6. In `sendAjax`, push `items[i].dataset.id` instead of `$(items[i]).attr('id')`.
7. Wrap the `$.ajax` call in a debounce of 400 ms. Use a module-scoped `let _saveTimer = null` and `clearTimeout`/
   `setTimeout`.
8. Add an `error` callback to the `$.ajax` call that logs `'Failed to save bookmark order'` to the console.
9. Add a `beforeSend` hook via `$.ajaxSetup` that sets the `X-CSRFToken` header from `#csrf-token`. Place the
   `$.ajaxSetup` call once, before the `Sortable.create` call.

**In the template block that renders the form (outside the macro):**

10. Pass an empty `ReorderForm` instance into this template as `form` (you will need to check the corresponding view
    function and add `form=ReorderForm()` to the `render_template` call). Add a hidden input in the `bodyblock` before
    the card, inside the `{% if not sel.retired %}` guard that already wraps the script block:
    ```html
    <input type="hidden" id="csrf-token" value="{{ form.csrf_token._value() }}">
    ```

**In the Python view:**

11. Locate the view function that renders this template. Import `ReorderForm` (an empty `FlaskForm` subclass — create it
    in the appropriate forms file if it does not already exist) and pass `form=ReorderForm()` to `render_template`.
12. In the `update_student_bookmarks` endpoint, the incoming `ranking` list now contains bare integer strings (e.g.
    `["12", "7", "3"]`) rather than prefixed strings (e.g. `["P-12", "P-7", "P-3"]`). Update the server-side parsing
    accordingly — remove any prefix-stripping logic.

After making all changes, confirm that no other templates or JS files reference `#ranking` as an id selector, and flag
any that do.

**Repeat analogous steps for other templates that use SortableJS.**
