# Implement revised `marking_dashboard.html` — hierarchy, colour, and typography fixes

Apply the following changes to `app/templates/dashboards/marking_dashboard.html`.
Make all changes within the existing file. Do not touch the data layer, view function, or any other template.

---

## Fix 1 — Promote `ProjectClass` to a section-break header

The current period/pclass sub-header (the `div` with class `bg-light border-bottom` that renders the period name and
pclass name together) must be split into two separate elements. Introduce a new pclass-level header that renders once
per `pclass_section`, outside the `period_section` loop.

The new pclass header should:

- Sit immediately above the period sub-header
- Use `border-left: 4px solid` with `pclass_section.pclass.colour` as the accent colour (guard for `None`)
- Use `color-mix(in srgb, <pclass.colour> 12%, white)` as the background (guard for `None`; fall back to
  `var(--bs-light)`)
- Use `var(--bs-body-color)` for text — never `pclass.text_colour`, which is computed for full-saturation badges and is
  inappropriate for a pastel background
- Display `pclass_section.pclass.name` as the primary element, `fw-semibold`, at approximately `0.95rem`

---

## Fix 2 — Demote the period sub-header

The existing period sub-header should be retained as a subordinate label beneath the pclass header. Modify it so that:

- It no longer carries `pclass_section.pclass.name` (now redundant with Fix 1)
- It uses a lighter visual weight: `bg-light` background, `text-body-secondary` colouring, `small` text
- It is indented slightly relative to the pclass header (e.g. `ps-4` or `px-4` with increased left padding) to reinforce
  the visual hierarchy

---

## Fix 3 — Event card left-border accent keyed to FSM workflow state

Each event card (the `div` with class `border-bottom bg-white px-4 py-3`) should gain a left-border accent. Add
`border-start border-4` and map `event.workflow_state` to a Bootstrap border colour utility using the existing
`_state_badge` dict as a reference for the state constants:

| State                        | Border class       |
|------------------------------|--------------------|
| `WAITING`                    | `border-secondary` |
| `OPEN`                       | `border-primary`   |
| `READY_TO_CONFLATE`          | `border-success`   |
| `READY_TO_GENERATE_FEEDBACK` | `border-warning`   |
| `READY_TO_PUSH_FEEDBACK`     | `border-warning`   |
| `CLOSED`                     | `border-dark`      |

Use a Jinja2 mapping dict (same pattern as `_state_badge`) to keep this clean. Add a small bottom margin between
consecutive event cards (`mb-2` or `mb-3`) so cards within the same period are visually separated.

---

## Fix 4 — Remove redundant pclass name from event convenor line

In the event header, the convenor metadata line currently ends with `&middot; {{ pclass_section.pclass.name }}`. Remove
this fragment — it is redundant once Fix 1 is in place.

---

## Typography — replace all inline `style` font-size attributes with named CSS classes

Add the following utility classes to the project's shared CSS override file (check `.claude/rules/` for any rule
specifying the correct file location):

```css
/* Micro-label: decorative section headings, e.g. HEALTH INDICATORS */
.text-micro {
    font-size: 0.65rem;
    letter-spacing: 0.05em;
}

/* Secondary annotation: tile footers, count labels */
.text-caption {
    font-size: 0.75rem;
}

/* Tertiary metadata: workflow role/scheme/count lines */
.text-meta {
    font-size: 0.80rem;
}
```

Then in the template, replace every inline `style` font-size attribute as follows:

| Location                  | Was                                             | Replace with                                               |
|---------------------------|-------------------------------------------------|------------------------------------------------------------|
| "HEALTH INDICATORS" label | `style="font-size:10px; letter-spacing:0.05em"` | class `text-micro`                                         |
| All tile footer `div`s    | `style="font-size:10px"`                        | class `text-caption`                                       |
| Workflow metadata line    | `style="font-size:11px; color:#666;"`           | classes `text-meta text-body-secondary`                    |
| Grade SD/CV tile value    | `style="font-size:15px; color:#1a1a1a;"`        | classes `fw-bold text-body` (remove inline style entirely) |

Also remove the `.small` class from any tile footer `div` that carries it alongside the inline font-size — the
`.text-caption` class provides the sizing directly.

---

## Verification

After applying changes, visually confirm with the known test case visible in the screenshot (event: "A2 report 2026",
pclass: "Final Year Project (BSc)"):

1. "Final Year Project (BSc)" appears as a clearly distinct section header above the period strip, with a coloured left
   accent and pastel background
2. "Submission Period #1 · 2025–2026" appears as a subordinate label beneath it, without the pclass name
3. The "A2 report 2026" event card has a blue left border (state: Open)
4. The tile footer text ("18% awaiting", "97% awaiting", etc.) is visibly larger than before
5. The workflow metadata line ("Role: Marker · Scheme: …") uses `text-body-secondary` colour rather than the previous
   grey `#666`
6. No `style="font-size:..."` or `style="color:#..."` attributes remain anywhere in the template