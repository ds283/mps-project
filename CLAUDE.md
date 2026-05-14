# CLAUDE.md

## Project Overview

**MPS Project (Major Projects System)** is a Flask-based web platform for managing student major projects (
dissertations, final-year projects) at the University of Sussex. It handles the full lifecycle: project proposals,
student selection, supervision assignments, marking, and reporting.

## Development Commands

### Local Development

```bash
# Install Python dependencies
pip install -r requirements.txt

# Start the development web server (Waitress on port 5000)
python serve.py

# Start Celery worker (for background tasks: emails, PDFs, reports)
celery -A celery_node.celery worker -Ofair --loglevel=INFO -E --concurrency=4 --max-memory-per-child=800000 -Q default,priority

# Start Celery Beat scheduler
celery -A celery_node.celery beat --scheduler app.sqlalchemy_scheduler:DatabaseScheduler --loglevel=INFO
```

### Docker (Full Stack)

```bash
# Build and start all services
./build.sh

# Restart web/worker/scheduler/flower services only
./restart.sh

# Start services without rebuilding
docker compose up -d
```

### Linting & Formatting

```bash
# Lint with ruff
ruff check .

# Format with black (150 char line length)
black .
```

There is no project-level test suite.

## Architecture

### Blueprint Structure

The application uses Flask blueprints, one per user role:

- `app/admin/` — System administration
- `app/convenor/` — Project coordinators/convenors
- `app/faculty/` — Supervisors and markers
- `app/student/` — Student project selection and submission
- `app/ajax/` — Server-side AJAX endpoints (DataTables, form widgets)
- `app/shared/` — Cross-blueprint utilities and views

Each blueprint follows the same pattern: `__init__.py` registers routes, with views broken into sub-modules for complex
areas.
There are also utility blueprints for tasks that span multiple roles, such as producing reports, or which provide common
services:

- `app/documents/` — Handle uploaded documents
- `app/projechub/` — Handle services associated with a lightweight learning management system for each student's project
- `app/manage_users/` — User management and role assignment

### Database Models (`app/models/`)

The models directory contains ~27 files. Key domains:

- `users.py`, `faculty.py`, `students.py` — People and roles
- `projects.py`, `project_class.py` — Project definitions and classes
- `submissions.py` — Student submission tracking
- `assessment.py`, `markingevent.py` — Marking workflows and events
- `emails.py` — Email template system
- `academic.py` — Academic year / period structure
- `utilities.py` — Shared mixins and helper models

### Multi-Database Architecture

| Database              | Use                                                    |
|-----------------------|--------------------------------------------------------|
| MySQL/MariaDB         | Primary relational data (users, projects, assessments) |
| MongoDB               | Session storage, flexible document data                |
| Redis                 | Celery broker, Flask-Caching, Flask-Limiter, sessions  |
| MinIO (S3-compatible) | File storage (submissions, reports, backups)           |

### Async Task Queue

All long-running work goes through Celery (`app/tasks/`): sending emails, generating PDFs, building reports, running
batch operations. The scheduler uses a database-backed APScheduler (`app.sqlalchemy_scheduler:DatabaseScheduler`).

### Frontend

Server-side rendered Jinja2 templates with Bootstrap 4/5, jQuery, DataTables (server-side processing for all large
tables), Select2, TinyMCE (rich text), and Chart.js. Static assets are managed via Flask-Assets.

### Multi-Tenancy

The system supports multiple institutional tenants. Queries are automatically scoped by tenant context stored in the
database. The `Tenant` model controls per-institution configuration.

### Key Application Entry Points

- `mpsproject.py` — Flask app entry point (`create_app()` factory in `app/__init__.py`)
- `serve.py` — Dev/production server; also runs DB initialization checks and data migrations on startup
- `boot.sh` — Docker container entrypoint (runs `flask db upgrade`, then `serve.py`)
- `celery_node.py` — Celery application instance
- `initdb.py` — One-time database population logic (called from `serve.py` if tables are empty)

### Database Migrations

Migrations use Flask-Migrate (Alembic). Migrations cannot be generated directly from the shell. The Flask app
needs configuration, which is only available inside a Docker container.

Do NOT generate Alembic migrations by calling `flask db migrate`. Instead, write migrations by hand.
Ensure that you do NOT duplicate migration identifiers. Ensure that you carefully read the migration chain
and add new migrations at the tip. Do not create forks.

## Implementation policies

- Inspector list views should use a DataTables front end backed by an AJAX endpoint, with AJAX row
  formatters implemented in `app/ajax/convenor`. See `.claude/rules/ajax-datatables.md` for
  ServerSideSQLHandler configuration and row-formatter patterns.
- Use the select2() library to render QuerySelectField and QueryMultipleSelectField fields. Use the
  `select2-small` value for the `selectionCssClasss` and `dropdownCssClass` properties.
- Changes to the database are instrumented using the log_db_commit() function defined in
  `app/shared/workflow_logging.py`. These are intended to log user-initiated workflow events, or actions taken
  by background tasks when an audit log may be needed. Exclude periodic maintenance tasks or low-level activity
  that would generate a lot of noise.
- Access to object buckets goes through the ObjectStore abstraction. This is defined in
  @app/shared/cloud-object-store/base.py. Interactions with the bucket should STRICTLY use only the
  methods defined in this class.
- When defining add/edit WTForms, share as much configuration as possible using mixins
- All POST forms must be backed by a WTForms `Form` instance (using `flask_security.forms.Form` as
  the base class, consistent with the rest of the project). Use `{{ form.hidden_tag() }}` in templates
  for CSRF protection — never inject a raw `csrf_token` into the template context or use
  `{{ csrf_token() }}` directly. Even button-only forms with no user input must use this pattern.
  The app does not use Flask-WTF's `CSRFProtect` globally, so `{{ csrf_token() }}` is not
  available as a Jinja2 global. GET views that render a template containing a POST form should
  instantiate and pass the form object; POST views should instantiate the form and call
  `form.validate_on_submit()` rather than checking `request.method == "POST"` manually.
- **Never mutate `field.validators` after form instantiation.** WTForms 3.x stores the
  validators list by reference (not by copy) on the shared `UnboundField`, so
  `form.field.validators.append(v)` permanently mutates the class-level list and accumulates
  stale validators across requests. Instead, pass request-specific validators via
  `form.validate_on_submit(extra_validators={"field_name": [v]})` or
  `form.validate(extra_validators={"field_name": [v]})`. This applies to all static form
  classes; factory-generated classes (e.g. from `MarkingWorkflowFormFactory`) create a fresh
  class per call and are not affected, but should follow the same pattern for consistency.

### DateTime

Do not use datetime.datetime.utcnow(), which is deprecated. Prefer datetime.datetime.now().

## UI conventions

### Staff initials avatars

Whenever a staff member's initials are displayed in a UI component (avatar circles, monogram
badges, etc.), always derive them from `user.initials` — the canonical `@property` defined on
the `User` model in `app/models/users.py`.

**Never** compute initials ad hoc in a template, view function, or JavaScript snippet.

In Jinja2 templates: `{{ role.user.initials }}`
In Python: `initials = user.initials`

