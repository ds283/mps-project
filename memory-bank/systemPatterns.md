# System Patterns

## Architecture Overview

### Multi-Tenant Flask Application

The MPS Project is a sophisticated Flask-based web application designed for managing academic projects, supervisions,
and assessments. The system supports multiple tenants with isolated data.

**Core Architecture:**

- **Blueprint-based modular design**: Each major feature area is a Flask blueprint
- **Multi-database architecture**: MySQL for relational data, MongoDB for documents, Redis for caching
- **Async task processing**: Celery for background jobs with Redis broker
- **Object storage**: MinIO/S3-compatible storage for files

### Application Structure

```
app/
├── __init__.py          # Application factory
├── models/              # SQLAlchemy models
├── admin/               # Admin blueprint
├── convenor/            # Convenor (coordinator) blueprint
├── faculty/             # Faculty member blueprint
├── student/             # Student blueprint
├── ajax/                # AJAX endpoints (per blueprint)
├── templates/           # Jinja2 templates (per blueprint)
├── static/              # Static assets
├── tasks/               # Celery tasks
├── services/            # Business logic services
└── tools/               # Utility functions
```

## Key Design Patterns

### 1. Blueprint Organization

Each functional area is organized as a Flask blueprint with consistent structure:

```
blueprint_name/
├── __init__.py          # Blueprint registration
├── views.py             # Route handlers
├── forms.py             # WTForms form definitions
```

Corresponding AJAX endpoints:

```
ajax/blueprint_name/
├── __init__.py
├── feature.py           # AJAX endpoints for specific features
```

### 2. AJAX Pattern for Interactive Features

**Standard AJAX Implementation:**

1. **Server-Side DataTables Processing**

- Uses `ServerSideProcessing.py` utility class
- Handles pagination, sorting, filtering
- Returns JSON with data and metadata

   ```python
   # Pattern in ajax endpoints
   from ..tools.ServerSideProcessing import ServerSideHandler
   
   @blueprint.route('/ajax/list')
   def ajax_list():
       handler = ServerSideHandler(request, query, columns)
       return handler.build_response()
   ```

2. **CRUD Operations**

- Create/Update/Delete via AJAX POST
- Return JSON with success/error status
- Flash messages for user feedback
- Database transaction management

   ```python
   @blueprint.route('/ajax/edit/<int:id>', methods=['POST'])
   def ajax_edit(id):
       try:
           # Perform operation
           db.session.commit()
           return jsonify({'success': True})
       except Exception as e:
           db.session.rollback()
           return jsonify({'success': False, 'message': str(e)})
   ```

3. **Client-Side Integration**

- DataTables for list views
- AJAX forms with JSON responses
- Bootstrap modals for edit dialogs
- Flash message display

### 3. Database Access Pattern

**SQLAlchemy ORM with Explicit Transaction Management:**

```python
# Standard pattern
try:
    # Create/modify objects
    db.session.add(object)
    db.session.commit()
except Exception:
    db.session.rollback()
    raise
```

**Key Principles:**

- Use relationship loading strategies (eager, lazy, subquery)
- Avoid N+1 query problems with `joinedload()`
- Use database-level cascades for deletions
- Maintain referential integrity through foreign keys

### 4. Email Template System Pattern

**Three-Layer Architecture:**

1. **Model Layer** (`app/models/emails.py`)

- `EmailTemplate` model stores template metadata and content
- Jinja2 template syntax in content field
- Links to notification types/categories

2. **Service Layer** (email sending services)

- Template resolution by type/category
- Context data preparation
- Template rendering with Jinja2
- Queue email jobs to Celery

3. **Admin Interface**

- Template CRUD via AJAX endpoints
- Syntax-highlighted editor
- Preview functionality
- Template variable documentation

### 5. Campaign Management Pattern

**Tenant-Based Campaign Tracking:**

```python
# Tenant model with campaign flags
class Tenant(db.Model):
    in_2026_ATAS_campaign = db.Column(db.Boolean, default=False)


# Campaign logic with dynamic form generation
def check_campaign(user_data):
    projects = []

    # Define dynamic form
    class InputForm(Form):
        submit = SubmitField("Continue")

    # Add fields dynamically based on user's projects
    for project in eligible_projects:
        setattr(InputForm, f"project_{project.id}_field", FieldType(...))
        projects.append(project)

    return {'projects': projects, 'form': InputForm}
```

**Key Characteristics:**

- Campaign features tied to tenant configuration
- Dynamic form generation for variable data sets
- Year-specific campaign tracking for flexibility
- Reusable blueprint structure for future campaigns
- Faculty-facing workflows with validation

**Common Use Cases:**

- ATAS compliance campaigns
- Project tagging initiatives
- Data collection from faculty
- Periodic update requirements
- Institution-specific workflows

### 6. Task Queue Pattern

**Celery-based Async Processing:**

```python
# Task definition
@celery.task(bind=True)
def long_running_task(self, arg1, arg2):
    # Update progress
    self.update_state(state='PROGRESS', meta={'current': 1, 'total': 10})
    # Perform work
    return result


# Task invocation
task = long_running_task.apply_async(args=[arg1, arg2])
```

**Common Use Cases:**

- Email sending
- PDF generation
- Report generation
- Batch processing
- Scheduled maintenance tasks

### 7. Multi-Tenancy Pattern

**Tenant Isolation:**

- Each tenant has separate data partition
- Tenant context stored in session/request
- Database queries filtered by tenant
- File storage organized by tenant

**Implementation:**

```python
# Automatic tenant filtering in queries
@property
def tenant_query(self):
    return self.query.filter_by(tenant_id=current_tenant.id)
```

## Component Relationships

### Request Flow

1. **HTTP Request** → Flask routing
2. **Authentication** → User session validation
3. **Authorization** → Role-based access control
4. **View Handler** → Business logic
5. **Service Layer** → Complex operations
6. **Model Layer** → Database operations
7. **Template Rendering** → Response generation

### Data Flow

1. **User Input** → Form validation (WTForms)
2. **Business Logic** → Service functions
3. **Database** → SQLAlchemy ORM
4. **Cache** → Redis for frequently accessed data
5. **File Storage** → MinIO/S3 for documents
6. **Background Tasks** → Celery for async work

## Critical Implementation Paths

### Project Lifecycle

1. Project creation by faculty
2. Approval workflow (multi-stage)
3. Student selection process
4. Assignment to students
5. Supervision period management
6. Assessment and grading
7. Archive and reporting

### Supervision Events

1. Event scheduling
2. Student/supervisor notifications
3. Attendance tracking
4. Feedback collection
5. Progress monitoring

### Assessment Workflow

1. Marking schema definition
2. Assessor assignment
3. Mark submission
4. Moderation process
5. Final grade calculation
6. External examiner review

## Performance Patterns

### Caching Strategy

- **Flask-Caching** for view caching
- **Redis** for session storage
- **Memoization** for expensive computations
- **Database query result caching**

### Query Optimization

- **Eager loading** for relationships
- **Index usage** for common queries
- **Query result pagination**
- **Subquery optimization**

### Async Processing

- **Celery tasks** for long operations
- **Progress tracking** for user feedback
- **Result backend** for task results
- **Retry logic** for failures

## Security Patterns

### Authentication & Authorization

- **Flask-Login** for session management
- **Role-based access control** (RBAC)
- **Tenant isolation** in queries
- **CSRF protection** on forms

### Data Validation

- **WTForms** validation
- **SQLAlchemy** constraints
- **Custom validators** for business rules
- **Sanitization** of user input

### Secure Communications

- **HTTPS** enforcement
- **Secure cookie** settings
- **CORS** configuration
- **Rate limiting** on endpoints

## Error Handling Patterns

### Graceful Degradation

- Try/except blocks with rollback
- User-friendly error messages
- Logging of technical details
- Fallback behaviors

### Monitoring & Logging

- Application logging to files
- Error tracking (potential integration)
- Performance metrics
- Audit trails for critical operations

# task_progress RECOMMENDED

When starting a new task, it is recommended to include a todo list using the task_progress parameter.

1. Include a todo list using the task_progress parameter in your next tool call
2. Create a comprehensive checklist of all steps needed
3. Use markdown format: - [ ] for incomplete, - [x] for complete

**Benefits of creating a todo/task_progress list now:**

- Clear roadmap for implementation
- Progress tracking throughout the task
- Nothing gets forgotten or missed
- Users can see, monitor, and edit the plan

**Example structure:**```

- [ ] Analyze requirements
- [ ] Set up necessary files
- [ ] Implement main functionality
- [ ] Handle edge cases
- [ ] Test the implementation
- [ ] Verify results```

Keeping the task_progress list updated helps track progress and ensures nothing is missed.

<environment_details>

# PyCharm Professional Visible Files

memory-bank/activeContext.md

# PyCharm Professional Open Tabs

memory-bank/projectbrief.md
memory-bank/productContext.md
memory-bank/activeContext.md

# Current Time

3/25/2026, 10:24:13 PM (Europe/London, UTC+0:00)

# Context Window Usage

33,016 / 131K tokens used (25%)

# Current Mode

ACT MODE
</environment_details>