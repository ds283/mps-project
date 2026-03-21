# Active Context

## Current Work Focus

Initial memory bank setup - establishing baseline documentation for the MPS Project system.

## Recent Changes

- Created memory bank structure with core documentation files
- Documented project purpose, architecture, and technical foundation

## Next Steps

1. Monitor for specific development tasks or issues
2. Update memory bank as changes occur
3. Maintain documentation accuracy as system evolves

## Active Decisions and Considerations

### Documentation Maintenance

- Memory bank should be updated after significant changes
- Core files should remain focused and concise
- Additional context files can be created for complex features

### Project Observations

- Large, mature codebase with multiple subsystems
- Production system actively in use
- Multi-tenant architecture requires careful change management
- Background job processing via Celery for async operations

## Important Patterns and Preferences

### Code Organization

- Blueprint-based Flask application structure
- Separate modules for each role (convenor, faculty, student, admin, etc.)
- AJAX endpoints separated from main views
- Shared utilities and services in dedicated directories

### Data Layer

- SQLAlchemy ORM models
- Multi-tenant data isolation
- Object storage for files
- MongoDB for certain data stores

### Background Processing

- Celery workers for async tasks
- Scheduled tasks via Beat
- Email notifications
- Report generation

## Learnings and Project Insights

### Architecture Strengths

- Clear separation of concerns
- Role-based access control
- Scalable multi-tenant design
- Comprehensive test infrastructure

### Technical Debt Areas

- Legacy code sections may exist
- Database migrations to manage carefully
- Docker/deployment complexity

### Development Workflow

- Database migrations via Alembic
- Docker-based deployment
- Multiple environment configurations (local, SussexVM, production)
- Nginx reverse proxy configuration

## Context for Future Work

When working on this system:

1. **Always consider multi-tenancy** - changes must work across tenants
2. **Background jobs** - some operations should be async
3. **Audit trails** - changes to key data should be logged
4. **Email notifications** - user communication is important
5. **Role permissions** - verify access controls
6. **Database migrations** - schema changes require migrations
7. **Testing** - maintain test coverage for critical paths