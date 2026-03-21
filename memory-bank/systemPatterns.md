# System Patterns

## Architecture Overview

### Application Structure

```
Flask Web Application (app/)
├── Blueprints (role-based modules)
│   ├── convenor/ - Project convenor functionality
│   ├── faculty/ - Faculty member views
│   ├── student/ - Student interfaces
│   ├── admin/ - System administration
│   ├── project_approver/ - Project approval workflows
│   ├── user_approver/ - User approval workflows
│   ├── office/ - Administrative office
│   └── [other role modules]
├── AJAX endpoints (ajax/)
│   └── Separated by module for async operations
├── Models (models/)
│   └── SQLAlchemy ORM definitions
├── Tasks (tasks/)
│   └── Celery background jobs
├── Services (services/)
│   └── Business logic and utilities
└── Templates (templates/)
    └── Jinja2 HTML templates
```

### Multi-Tenant Architecture

**Tenant Isolation**:

- Each academic program is a separate tenant
- Data isolation at database level
- Users can belong to multiple tenants
- Configuration per tenant

**Tenant Context**:

- Tenant selection/switching mechanism
- Scoped queries to current tenant
- Tenant-specific permissions
- Cross-tenant operations when appropriate (admin functions)

## Key Technical Decisions

### Framework Choice: Flask

- Lightweight and flexible
- Blueprint pattern for modular organization
- Extensive ecosystem
- Good performance for educational institution scale

### ORM: SQLAlchemy

- Robust relationship management
- Migration support via Alembic
- Complex query capabilities
- Database independence (using MySQL in production)

### Background Processing: Celery

- Async task execution
- Scheduled jobs via Beat
- Multiple workers for scalability
- Redis as message broker

### Object Storage

- File system or S3-compatible storage
- Separate buckets for different content types:
    - Project documents
    - Student submissions
    - Feedback files
    - Assets and resources
    - Backups

### Caching: Redis

- Session storage
- Rate limiting
- Cache invalidation patterns

## Design Patterns in Use

### Blueprint Pattern

Each role/feature area is a Flask Blueprint with:

- Routes/views
- Forms (Flask-WTF)
- Templates
- Role-specific logic

### Repository Pattern (Implicit)

- Models encapsulate data access
- Service layer for business logic
- Separation of concerns

### Factory Pattern

Application factory in `app/__init__.py`:

- Creates Flask app instance
- Registers blueprints
- Initializes extensions
- Configures based on environment

### Task Queue Pattern

- Long-running operations queued to Celery
- Email sending via background tasks
- Report generation
- Scheduled maintenance

### Decorator-Based Security

- Login required decorators
- Role-based access control
- Permission checking decorators

## Component Relationships

### Request Flow

```
User Request
    ↓
Nginx (reverse proxy)
    ↓
Gunicorn (WSGI server)
    ↓
Flask Application
    ↓
├─→ Authentication/Authorization
├─→ Blueprint Router
├─→ View Handler
├─→ Service Layer
├─→ Model/Database
└─→ Template Rendering
    ↓
Response to User
```

### Background Job Flow

```
Application
    ↓
Queue Task (Celery)
    ↓
Redis (broker)
    ↓
Celery Worker
    ↓
Execute Task
    ↓
├─→ Database updates
├─→ File operations
├─→ Email sending
└─→ Result storage
```

### Data Layer

```
Application
    ↓
SQLAlchemy ORM
    ↓
MySQL Database
    ├─→ Core application data
    ├─→ User accounts
    ├─→ Projects and assignments
    ├─→ Submissions and grades
    └─→ Configuration

Object Storage
    ├─→ Documents
    ├─→ Submissions
    └─→ Assets

MongoDB (selective)
    └─→ Specific data stores
```

## Critical Implementation Paths

### Project Creation Flow

1. Faculty creates project proposal
2. Validation of required fields
3. Approval workflow (if required)
4. Publication to catalog
5. Becomes available for student selection

### Student Assignment Flow

1. Students rank project preferences
2. Convenor runs allocation (algorithm or manual)
3. Assignments created in database
4. Notifications sent to students and supervisors
5. Project relationships activated

### Submission Flow

1. Student uploads document
2. File validation and virus scanning
3. Storage in object store
4. Database record creation
5. Supervisor notification
6. Marking workflow activation

### Notification Pattern

1. Event occurs (assignment, deadline, submission)
2. Task queued to Celery
3. Email template rendering
4. SMTP sending
5. Logging and audit trail

### Multi-Tenant Data Access

1. User authenticates
2. Tenant context established (from session or URL)
3. All queries scoped to tenant
4. Cross-tenant operations require explicit permission
5. Audit logging of tenant switches

## State Management

### Project States

- Draft → Approved → Published → Active → Complete → Archived

### Assignment States

- Waiting → Confirmed → In Progress → Submitted → Marked → Complete

### User States

- Pending → Active → Suspended → Archived

### Academic Year Cycles

- Setup → Project Selection → Assignment → Supervision → Assessment → Archive