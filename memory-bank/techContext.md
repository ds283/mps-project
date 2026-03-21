# Technical Context

## Technology Stack

### Core Framework

- **Python 3.x** - Primary programming language
- **Flask** - Web framework
- **SQLAlchemy** - ORM and database toolkit
- **Alembic** - Database migration tool

### Frontend

- **Jinja2** - Template engine
- **Bootstrap** - CSS framework (via templates)
- **JavaScript/jQuery** - Client-side interactivity
- **AJAX** - Async operations

### Database & Storage

- **MySQL** - Primary relational database
- **Redis** - Cache and message broker
- **MongoDB** - Selective data storage
- **Object Storage** - File system or S3-compatible for documents

### Background Processing

- **Celery** - Distributed task queue
- **Celery Beat** - Periodic task scheduler
- **Flower** - Celery monitoring tool

### Deployment & Infrastructure

- **Docker** - Containerization
- **Gunicorn** - WSGI HTTP server
- **Nginx** - Reverse proxy and static file serving
- **Kubernetes** - Container orchestration (legacy deployments)

### Development Tools

- **PyCharm Professional** - IDE in use
- **Git** - Version control
- **pip** - Package management

## Development Setup

### Environment Structure

```
/Users/ds283/Documents/Code/MPS-Project/
├── app/                    # Main application code
├── migrations/             # Alembic database migrations
├── Deployments/            # Deployment configurations
│   ├── local/             # Local development
│   ├── SussexVM/          # VM deployment
│   └── suex-enginfprojects-prod/  # Production
├── basic_database/        # Initial database setup
├── mysql/                 # MySQL data directory
├── redis/                 # Redis data directory
├── mongodb/               # MongoDB data directory
├── objectstore-data/      # File storage
└── logs/                  # Application logs
```

### Key Configuration Files

- `pyproject.toml` - Python project metadata
- `requirements.txt` - Python dependencies
- `Dockerfile` - Container build instructions
- `docker-compose.yml` - Multi-container setup (if present)
- `gunicorn_config.py` - WSGI server configuration
- `nginx.conf` - Web server configuration

### Entry Points

- `mpsproject.py` - Main application entry
- `serve.py` - Development server
- `celery_node.py` - Celery worker
- `initdb.py` - Database initialization
- `migrate.py` - Database migration runner

### Startup Scripts

- `boot.sh` - Application bootstrap
- `launch_celery.sh` - Start Celery workers
- `launch_beat.sh` - Start Celery Beat scheduler
- `launch_flower.sh` - Start Flower monitoring
- `restart.sh` - Application restart

## Technical Constraints

### Database

- MySQL-specific features may be in use
- Multi-tenant data isolation required
- Migration compatibility across environments
- Character encoding (Latin1 fix script present)

### Performance

- Celery for long-running operations
- Redis caching for frequently accessed data
- Rate limiting on API endpoints
- Object storage for large files

### Security

- Role-based access control
- Multi-tenant data isolation
- Secure file upload/download
- Session management via Redis
- CSRF protection

### Scalability

- Horizontal scaling via multiple Celery workers
- Database connection pooling
- Stateless application design
- Load balancing via Nginx

## Dependencies

### Major Python Packages (from requirements.txt)

Key dependencies include:

- Flask and extensions (Flask-SQLAlchemy, Flask-WTF, Flask-Login, etc.)
- Celery for task queue
- PyMySQL for MySQL connectivity
- Redis-py for caching
- Boto3 for S3 (if using cloud storage)
- PyMuPDF for PDF handling
- Email libraries for notifications
- Authentication/security packages

### External Services

- **SMTP Server** - Email delivery
- **MySQL Server** - Database
- **Redis Server** - Cache/broker
- **Object Storage** - File storage (local or S3)

## Tool Usage Patterns

### Database Management

```bash
# Initialize database
python initdb.py

# Run migrations
python migrate.py upgrade head

# Create new migration
flask db migrate -m "description"
```

### Running the Application

```bash
# Development
python serve.py

# Production via Gunicorn
gunicorn -c gunicorn_config.py mpsproject:app
```

### Background Workers

```bash
# Start Celery worker
./launch_celery.sh

# Start Beat scheduler
./launch_beat.sh

# Monitor with Flower
./launch_flower.sh
```

### Docker Operations

```bash
# Build image
./build.sh

# Run containers
docker-compose up -d

# View logs
docker-compose logs -f
```

## Environment Configuration

### Configuration Patterns

- Environment-specific config files in `Deployments/`
- Separate configs for local, VM, and production
- Configuration loaded based on environment variable
- Secrets managed via environment variables or config files

### Database Configuration

- Connection strings per environment
- Connection pooling settings
- Migration tracking

### Celery Configuration

- Broker URL (Redis)
- Result backend
- Task routing
- Scheduled task definitions

### Storage Configuration

- Object storage backend selection
- Bucket/directory configuration
- Access credentials

## Testing Infrastructure

- Test files present (e.g., `test_pdf.py`)
- Testing patterns to be documented as encountered
- Database fixtures in `basic_database/`

## Deployment Environments

### Local Development

- Configuration in `Deployments/local/`
- Local MySQL, Redis, MongoDB
- File-based object storage
- Development server

### Sussex VM

- Configuration in `Deployments/SussexVM/`
- VM-hosted services
- Nginx reverse proxy
- Production-like setup

### Production (suex-enginfprojects-prod)

- Kubernetes deployment (legacy)
- Manual manifests
- High availability configuration
- Monitoring and logging

## Development Workflow

1. **Code Changes**
    - Edit Python/template files
    - Flask auto-reload in development
    - Manual restart for production

2. **Database Changes**
    - Create Alembic migration
    - Review generated migration
    - Test migration up/down
    - Apply to environments

3. **Dependency Updates**
    - Update requirements.txt
    - Rebuild Docker image
    - Test in staging environment

4. **Deployment**
    - Build Docker image
    - Push to registry
    - Update deployment configuration
    - Rolling update in production