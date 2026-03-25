# Technical Context

## Core Technologies

### Backend Framework

- **Flask 2.x**: Python web framework
    - Blueprint-based modular architecture
    - Jinja2 templating engine
    - Werkzeug WSGI utilities
    - Development server and CLI tools

### Database Systems

1. **MySQL 8.x** (Primary relational database)
    - User accounts and authentication
    - Project and supervision data
    - Assessment and grading records
    - Tenant configuration
    - Audit trails

2. **MongoDB** (Document storage)
    - File metadata
    - Complex document structures
    - Flexible schema for varied data

3. **Redis** (Cache and message broker)
    - Session storage
    - Cache backend
    - Celery message broker
    - Rate limiting

### Object Storage

- **MinIO** (S3-compatible object storage)
    - Project documents
    - Submitted work
    - Generated reports
    - Backup files
    - Assets and media

### Task Queue

- **Celery 5.x**: Distributed task queue
    - Email sending
    - PDF generation
    - Report creation
    - Scheduled jobs
    - Batch processing

- **Celery Beat**: Task scheduler
    - Periodic maintenance
    - Scheduled notifications
    - Automated cleanup
    - Report generation

- **Flower**: Task monitoring UI
    - Task status monitoring
    - Worker management
    - Task statistics

## Frontend Technologies

### UI Framework

- **Bootstrap 4/5**: Responsive CSS framework
    - Grid system
    - Components (modals, alerts, cards)
    - Forms and inputs
    - Utilities

### JavaScript Libraries

- **jQuery 3.x**: DOM manipulation and AJAX
- **DataTables**: Interactive tables with server-side processing
- **Chart.js**: Data visualization (if used)
- **Select2**: Enhanced select boxes
- **Bootstrap-datepicker**: Date selection
- **Moment.js**: Date/time manipulation

### AJAX & API

- **RESTful endpoints**: JSON-based API
- **Server-side DataTables**: Paginated table data
- **AJAX forms**: Asynchronous form submission
- **JSON responses**: Standardized response format

## Python Ecosystem

### Core Dependencies

**Web Framework:**

- `Flask` - Web framework
- `Flask-SQLAlchemy` - ORM integration
- `Flask-Login` - User session management
- `Flask-WTF` - Form handling
- `Flask-Migrate` - Database migrations
- `Flask-Mail` - Email integration
- `Flask-Caching` - Caching support
- `Flask-Limiter` - Rate limiting

**Database:**

- `SQLAlchemy` - ORM
- `PyMySQL` - MySQL driver
- `pymongo` - MongoDB driver
- `redis` - Redis client

**Task Queue:**

- `celery` - Task queue
- `flower` - Monitoring

**File Handling:**

- `PyMuPDF` (fitz) - PDF manipulation
- `python-docx` - Word document handling
- `openpyxl` - Excel files
- `boto3` - S3/MinIO client

**Utilities:**

- `python-dateutil` - Date parsing
- `pytz` - Timezone handling
- `bleach` - HTML sanitization
- `validators` - Input validation
- `click` - CLI commands

### Development Tools

- `alembic` - Database migrations (via Flask-Migrate)
- `pytest` - Testing framework (if configured)
- `black` - Code formatting (if used)
- `flake8` - Linting (if used)

## Deployment Architecture

### Containerization

- **Docker**: Application containerization
    - Multi-stage builds
    - Service orchestration with docker-compose
    - Volume mounts for persistence
    - Network isolation

### Container Services

```yaml
services:
  - web: Flask application (gunicorn)
  - nginx: Reverse proxy and static files
  - mysql: Primary database
  - mongodb: Document database
  - redis: Cache and broker
  - celery: Task workers
  - beat: Task scheduler
  - flower: Task monitoring
  - minio: Object storage
```

### WSGI Server

- **Gunicorn**: Production WSGI server
    - Worker processes
    - Async workers (gevent/eventlet)
    - Graceful reloads
    - Access logging

### Reverse Proxy

- **Nginx**: HTTP server and reverse proxy
    - SSL/TLS termination
    - Static file serving
    - Request routing
    - Load balancing
    - Caching headers
    - Compression (gzip)

## Configuration Management

### Environment-Based Config

- `local.py` - Local development
- `config.py` - Base configuration
- Environment variables for secrets
- Tenant-specific overrides

### Configuration Categories

1. **Database**: Connection strings, pool sizes
2. **Security**: Secret keys, CSRF tokens
3. **Email**: SMTP settings
4. **Storage**: MinIO/S3 credentials
5. **Celery**: Broker URL, result backend
6. **Features**: Feature flags, limits

## Development Environment

### Local Setup

1. **Python virtual environment** (venv)
2. **Docker Compose** for services
3. **Local database** initialization scripts
4. **Development server** (Flask built-in)

### Database Initialization

- `initdb.py` - Database setup script
- `basic_database/` - SQL seed data
- Migration scripts via Alembic

### Running Locally

```bash
# Start services
docker-compose up -d

# Run migrations
flask db upgrade

# Start development server
python serve.py

# Start Celery worker
celery -A celery_node worker

# Start Celery beat
celery -A celery_node beat
```

## Testing Strategy

### Test Types

1. **Unit tests**: Individual functions/methods
2. **Integration tests**: Component interactions
3. **End-to-end tests**: Full workflows
4. **API tests**: Endpoint responses

### Testing Tools

- `pytest` - Test runner
- `pytest-flask` - Flask test utilities
- `factory-boy` - Test data generation (if used)
- `faker` - Fake data (if used)

## Version Control

### Git Workflow

- **Repository**: GitHub
- **Branching**: Feature branches
- **Commits**: Descriptive messages
- **Tags**: Release versioning

### Current State

- Latest commit: `bbc1c995856965bd9f108f22198e3eaaf25d68a1`
- Repository: `https://github.com/ds283/mps-project.git`

## Build & Deployment

### Build Process

1. **Docker image build**: Multi-stage Dockerfile
2. **Dependency installation**: pip from requirements.txt
3. **Static asset collection**: Flask static files
4. **Database migrations**: Alembic upgrade

### Deployment Targets

- **Local**: Development environment
- **SussexVM**: VM-based deployment
- **Production**: Kubernetes/VM (legacy configurations exist)

### Deployment Scripts

- `boot.sh` - Container startup
- `build.sh` - Image build
- `restart.sh` - Service restart
- `migrate.py` - Database migration helper

## Monitoring & Logging

### Application Logging

- Python `logging` module
- File-based logs in `logs/`
- Nginx access/error logs
- Celery task logs

### Log Rotation

- Logrotate configuration
- Automatic cleanup
- Archive old logs

## Security Considerations

### Secrets Management

- Environment variables for credentials
- No secrets in version control
- Separate configs per environment

### Database Security

- Connection over TLS (production)
- User permissions per service
- Regular backups
- SQL injection prevention (SQLAlchemy)

### Application Security

- CSRF protection on forms
- XSS prevention (template escaping)
- SQL injection prevention (ORM)
- Rate limiting on endpoints
- Secure session cookies
- HTTPS enforcement

## Performance Optimization

### Caching Layers

1. **Redis cache**: Frequently accessed data
2. **Template caching**: Rendered templates
3. **Query caching**: Database results
4. **Static file caching**: Browser cache headers

### Database Optimization

- Indexed columns for common queries
- Eager loading for relationships
- Connection pooling
- Query result pagination

### Background Processing

- Celery for long-running tasks
- Async email sending
- Batch operations
- Scheduled maintenance

## IDE & Development Tools

### Primary IDE

- **PyCharm Professional**: Python IDE
    - Integrated debugger
    - Database tools
    - Docker integration
    - Git integration
    - Code navigation

### Shell Environment

- **Zsh**: Default shell
- **Home directory**: `/Users/ds283`
- **Operating system**: macOS Tahoe

## Known Constraints & Limitations

### Technical Debt

- Some legacy code patterns
- Incomplete test coverage
- Documentation gaps
- Mixed Python versions support

### Performance Considerations

- Large dataset queries need optimization
- File uploads limited by server config
- Email sending rate limits
- Celery worker capacity

### Browser Support

- Modern browsers (Chrome, Firefox, Safari, Edge)
- Bootstrap 4/5 compatibility requirements
- JavaScript required for full functionality

## Upgrade Path

### Python Version

- Current: Python 3.x (specific version from requirements)
- Target: Stay on supported versions
- Migration: Test thoroughly before upgrade

### Framework Updates

- Flask: Monitor for security updates
- SQLAlchemy: Major version migrations need planning
- Celery: Background compatibility considerations
- Bootstrap: UI refresh required for major versions

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

memory-bank/systemPatterns.md

# PyCharm Professional Open Tabs

memory-bank/projectbrief.md
memory-bank/productContext.md
memory-bank/activeContext.md
memory-bank/systemPatterns.md

# Current Time

3/25/2026, 10:24:38 PM (Europe/London, UTC+0:00)

# Context Window Usage

36,736 / 131K tokens used (28%)

# Current Mode

ACT MODE
</environment_details>