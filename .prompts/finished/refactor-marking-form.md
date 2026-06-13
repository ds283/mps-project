You are refactoring the Jinja2 template `app/templates/faculty/marking_form.html`
in a Flask/Bootstrap 5 application. The goal is to implement a refined UI for
the supervision events section, and apply consistent card styling throughout
the whole form. Work only within this template file unless told otherwise.

---

## 1. Global card styling

Replace ALL instances of coloured card headers and borders with a neutral,
unified treatment:

- Remove `border-primary`, `border-secondary`, `border-success` from every
  `<div class="card ...">`. Replace with `border-0 shadow-sm`.
- Remove `bg-primary`, `bg-secondary`, `bg-success` (and `text-white`) from
  every `<div class="card-header ...">`. Replace with `bg-body-tertiary`.
- The one exception: the validation failure modal header may keep
  `bg-danger text-white` as it signals a genuine error state.
- Change the modal's "Return to form" dismiss button from `btn-danger` to
  `btn-secondary`.
- Change the locked-form banner from `alert-secondary` to `alert-warning`.

---

## 2. Supervision events section

This section already exists in the template, gated by
`{% if (is_supervisor_role or is_elevated) and supervision_events %}`.

Replace the current tile grid entirely with the following design.

### 2a. Attendance summary line

Replace the `<div class="text-secondary fs-2 mb-2">` attendance heading with:

```html

<div class="d-flex align-items-baseline gap-2 mb-3">
    <span class="text-body-secondary" style="font-size:0.8125rem;">Attendance</span>
    <span class="fw-500 text-success" style="font-size:1.125rem;">
    {% if attendance_percent is not none %}
      {{ attendance_percent | round(0) | int }}%
    {% else %}
      &mdash;
    {% endif %}
  </span>
    <span class="text-body-secondary" style="font-size:0.8125rem;">
    {{ attendance_recorded }}/{{ attendance_total }}
  </span>
</div>
```

### 2b. Timeline (wide viewports)

Replace the `<div class="d-flex flex-row flex-wrap gap-2">` tile grid with a
two-layout system: a dot timeline for wide screens and a compact list for
narrow screens. Both are rendered in the DOM; CSS controls which is visible.

Add this CSS block once, inside the template's `{% block scripts %}` (or a
`<style>` tag immediately before the supervision card):

```css
.ev-timeline {
    display: flex;
    align-items: flex-start;
}

.ev-session {
    display: flex;
    flex-direction: column;
    align-items: center;
    flex: 1;
    min-width: 0;
    position: relative;
}

.ev-connector {
    position: absolute;
    top: 11px;
    left: 50%;
    right: -50%;
    height: 1px;
    background-color: var(--bs-border-color);
    z-index: 0;
}

.ev-session:last-child .ev-connector {
    display: none;
}

.ev-dot {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6875rem;
    position: relative;
    z-index: 1;
    flex-shrink: 0;
    border: 0.5px solid transparent;
}

.ev-dot-ok {
    background: var(--bs-success-bg-subtle);
    color: var(--bs-success-text-emphasis);
    border-color: var(--bs-success-border-subtle);
}

.ev-dot-note {
    background: var(--bs-info-bg-subtle);
    color: var(--bs-info-text-emphasis);
    border-color: var(--bs-info-border-subtle);
    cursor: pointer;
}

.ev-dot-note:hover {
    filter: brightness(0.9);
}

.ev-dot-absent {
    background: var(--bs-danger-bg-subtle);
    color: var(--bs-danger-text-emphasis);
    border-color: var(--bs-danger-border-subtle);
}

.ev-date {
    font-size: 0.625rem;
    color: var(--bs-secondary-color);
    margin-top: 4px;
    white-space: nowrap;
}

.ev-list {
    display: none;
}

@media (max-width: 540px) {
    .ev-timeline {
        display: none;
    }

    .ev-list {
        display: block;
    }
}

.ev-popover {
    position: absolute;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    width: 240px;
    z-index: 200;
    display: none;
}

.ev-popover.show {
    display: block;
}

.ev-priv-badge {
    font-size: 0.625rem;
    background: var(--bs-warning-bg-subtle);
    color: var(--bs-warning-text-emphasis);
    border-radius: 3px;
    padding: 1px 5px;
}
```

### 2c. Jinja loop for the timeline

Replace the old event loop with:

```jinja2
{# --- Dot timeline (wide) --- #}
<div class="ev-timeline" id="ev-timeline-wide">
  {% for ev in supervision_events %}
    {%- set has_notes = ev.meeting_summary or ev.supervision_notes -%}
    {%- set notes_long = ((ev.meeting_summary | default('') | length)
                         + (ev.supervision_notes | default('') | length)) > 300 -%}

    {%- if ev.monitor_attendance and ev.attendance is not none -%}
      {%- if ev.attendance == 0 -%}
        {%- set dot_class = 'ev-dot-ok' -%}{%- set dot_icon = 'check' -%}
      {%- elif ev.attendance == 1 -%}
        {%- set dot_class = 'ev-dot-ok' -%}{%- set dot_icon = 'clock' -%}
      {%- elif ev.attendance in (2, 3) -%}
        {%- set dot_class = 'ev-dot-absent' -%}{%- set dot_icon = 'times' -%}
      {%- else -%}
        {%- set dot_class = '' -%}{%- set dot_icon = 'question' -%}
      {%- endif -%}
    {%- else -%}
      {%- set dot_class = '' -%}{%- set dot_icon = 'minus' -%}
    {%- endif -%}
    {%- if has_notes -%}{%- set dot_class = dot_class + ' ev-dot-note' -%}{%- endif -%}

    <div class="ev-session" style="position:relative;">
      <div class="ev-connector"></div>

      {%- if has_notes %}
        <div class="ev-dot {{ dot_class }}"
             role="button" tabindex="0"
             aria-label="{{ ev.get_start_time().strftime('%d %b') if ev.get_start_time() else ev.name }} — has notes"
             onclick="evTogglePop('ev-pop-{{ ev.id }}', event)">
          <i class="fas fa-{{ dot_icon }} fa-fw"></i>
        </div>
      {%- else %}
        <div class="ev-dot {{ dot_class }}">
          <i class="fas fa-{{ dot_icon }} fa-fw"></i>
        </div>
      {%- endif %}

      <div class="ev-date">
        {{ ev.get_start_time().strftime("%d %b") if ev.get_start_time() else ev.name }}
      </div>

      {%- if has_notes %}
        {%- if notes_long %}
          {# Long notes: popover shows truncated text + "Read full notes" link to offcanvas #}
          <div class="ev-popover card shadow-sm border-0 p-2" id="ev-pop-{{ ev.id }}">
            <button class="btn-close position-absolute top-0 end-0 m-1" style="font-size:0.6rem;"
                    onclick="evClosePop('ev-pop-{{ ev.id }}')" aria-label="Close"></button>
            <div class="text-body-secondary mb-1" style="font-size:0.6875rem;">
              {{ ev.get_start_time().strftime("%d %B %Y") if ev.get_start_time() else ev.name }}
            </div>
            {% if ev.meeting_summary %}
              <div class="fw-500 mb-1" style="font-size:0.6875rem;">Meeting summary</div>
              <div style="font-size:0.6875rem;">
                {{ ev.meeting_summary | striptags | truncate(120) }}
              </div>
            {% endif %}
            <button class="btn btn-link btn-sm p-0 mt-1 text-start"
                    style="font-size:0.6875rem;"
                    onclick="evClosePop('ev-pop-{{ ev.id }}');
                             new bootstrap.Offcanvas(document.getElementById('ev-oc-{{ ev.id }}')).show()">
              <i class="fas fa-arrow-right fa-fw"></i> Read full notes
            </button>
          </div>

          {# Offcanvas for long notes #}
          <div class="offcanvas offcanvas-end" tabindex="-1"
               id="ev-oc-{{ ev.id }}"
               aria-labelledby="ev-oc-label-{{ ev.id }}">
            <div class="offcanvas-header border-bottom">
              <h5 class="offcanvas-title" id="ev-oc-label-{{ ev.id }}" style="font-size:0.875rem;">
                <i class="fas fa-notes-medical fa-fw me-1"></i>
                {{ ev.get_start_time().strftime("%d %B %Y") if ev.get_start_time() else ev.name }}
              </h5>
              <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Close"></button>
            </div>
            <div class="offcanvas-body small">
              {% if ev.meeting_summary %}
                <p class="fw-500 text-body-secondary mb-1" style="font-size:0.75rem;">
                  <i class="fas fa-users fa-fw me-1"></i> Meeting summary
                </p>
                <div class="mb-3">{{ ev.meeting_summary | safe }}</div>
              {% endif %}
              {% if ev.supervision_notes %}
                <p class="fw-500 text-body-secondary mb-1" style="font-size:0.75rem;">
                  <i class="fas fa-lock fa-fw me-1"></i> Supervision notes
                  <span class="ev-priv-badge">private</span>
                </p>
                <div>{{ ev.supervision_notes | safe }}</div>
              {% endif %}
            </div>
          </div>

        {%- else %}
          {# Short notes: popover only #}
          <div class="ev-popover card shadow-sm border-0 p-2" id="ev-pop-{{ ev.id }}">
            <button class="btn-close position-absolute top-0 end-0 m-1" style="font-size:0.6rem;"
                    onclick="evClosePop('ev-pop-{{ ev.id }}')" aria-label="Close"></button>
            <div class="text-body-secondary mb-2" style="font-size:0.6875rem;">
              {{ ev.get_start_time().strftime("%d %B %Y") if ev.get_start_time() else ev.name }}
            </div>
            {% if ev.meeting_summary %}
              <div class="mb-2">
                <div class="fw-500 mb-1" style="font-size:0.6875rem;">
                  <i class="fas fa-users fa-fw me-1"></i> Meeting summary
                </div>
                <div style="font-size:0.6875rem;">{{ ev.meeting_summary | safe }}</div>
              </div>
            {% endif %}
            {% if ev.supervision_notes %}
              <div>
                <div class="fw-500 mb-1" style="font-size:0.6875rem;">
                  <i class="fas fa-lock fa-fw me-1"></i> Supervision notes
                  <span class="ev-priv-badge">private</span>
                </div>
                <div style="font-size:0.6875rem;">{{ ev.supervision_notes | safe }}</div>
              </div>
            {% endif %}
          </div>
        {%- endif %}
      {%- endif %}
    </div>
  {% endfor %}
</div>

{# --- Compact list (narrow / mobile) --- #}
<div class="ev-list mt-1" id="ev-list-narrow">
  {% for ev in supervision_events %}
    {%- set has_notes = ev.meeting_summary or ev.supervision_notes -%}
    {%- set notes_long = ((ev.meeting_summary | default('') | length)
                         + (ev.supervision_notes | default('') | length)) > 300 -%}
    <div class="d-flex align-items-start gap-2 py-2
                border-bottom border-light-subtle">
      <div class="ev-dot flex-shrink-0
                  {{ 'ev-dot-note' if has_notes else 'ev-dot-ok' }}"
           style="margin-top:2px;">
        <i class="fas fa-{{ 'notes-medical' if has_notes else 'check' }} fa-fw"></i>
      </div>
      <div class="flex-fill" style="min-width:0;">
        <div style="font-size:0.8125rem; font-weight:500;">
          {{ ev.get_start_time().strftime("%d %b %Y") if ev.get_start_time() else ev.name }}
        </div>
        <div class="text-body-secondary" style="font-size:0.75rem;">
          {{ ev.attendance_str if ev.attendance is not none else 'Attendance not recorded' }}
        </div>
        {% if has_notes %}
          {% if notes_long %}
            <button class="btn btn-link btn-sm p-0 mt-1 text-start"
                    style="font-size:0.75rem;"
                    onclick="new bootstrap.Offcanvas(document.getElementById('ev-oc-{{ ev.id }}')).show()">
              <i class="fas fa-notes-medical fa-fw"></i> View notes
            </button>
          {% else %}
            {% if ev.meeting_summary %}
              <div class="mt-1 text-body-secondary" style="font-size:0.75rem;">
                {{ ev.meeting_summary | striptags | truncate(160) }}
              </div>
            {% endif %}
          {% endif %}
        {% endif %}
      </div>
    </div>
  {% endfor %}
</div>

{# Legend #}
<div class="d-flex flex-wrap gap-3 mt-3" style="font-size:0.75rem; color:var(--bs-secondary-color);">
  <div class="d-flex align-items-center gap-1">
    <div class="ev-dot ev-dot-ok" style="width:13px;height:13px;font-size:0;"></div>
    Attended
  </div>
  <div class="d-flex align-items-center gap-1">
    <div class="ev-dot ev-dot-note" style="width:13px;height:13px;font-size:0;"></div>
    Has notes — click to read
  </div>
  <div class="d-flex align-items-center gap-1">
    <div class="ev-dot ev-dot-absent" style="width:13px;height:13px;font-size:0;"></div>
    Absent
  </div>
</div>
```

### 2d. JavaScript for popover toggle

Add this script block once near the bottom of `{% block scripts %}`:

```javascript
function evTogglePop(id, e) {
    e.stopPropagation();
    var el = document.getElementById(id);
    var isOpen = el.classList.contains('show');
    document.querySelectorAll('.ev-popover.show').forEach(p => p.classList.remove('show'));
    if (!isOpen) el.classList.add('show');
}

function evClosePop(id) {
    document.getElementById(id).classList.remove('show');
}

document.addEventListener('click', function (e) {
    if (!e.target.closest('.ev-session')) {
        document.querySelectorAll('.ev-popover.show').forEach(p => p.classList.remove('show'));
    }
});
```

---

## 3. Grade field layout

Find the `ftype == 'percent'` branch in the mark scheme loop
(inside the `{% elif ftype in ('number', 'percent') %}` block). Replace the
`row g-2` column layout for the range hint with:

```jinja2
<div class="mb-3">
  {{ wtf.render_field(form[key]) }}
  <div class="form-text">Range: 0 – 100%</div>
</div>
```

Remove the `<div class="col-md-8">` / `<div class="col-md-4 small ...">` wrapper.

---

## 4. Page header

Replace the existing `d-flex align-items-center mt-3 mb-3 gap-2` header div with:

```html

<div class="d-flex align-items-center gap-2 border-bottom pb-2 mt-3 mb-3">
    <a class="btn btn-sm btn-outline-secondary" href="{{ url }}">
        <i class="fas fa-arrow-left fa-fw"></i> Return
    </a>
    <h5 class="mb-0 fw-500">
        <i class="fas fa-marker fa-fw me-1 text-body-secondary"></i>
        Marking report for {{ record.student_identifier['label'] }}
    </h5>
</div>
```

---

## 5. Do not change

- The template's `{% extends %}`, `{% import %}`, `{% from %}` declarations.
- The form's `hidden_tag`, `action`, `method`, or any WTForms field rendering
  other than the percent range hint in step 3.
- The LLM feedback blocks (already commented out).
- Any Python view code, models, or other templates.