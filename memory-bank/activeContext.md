# Active Context

## Current Work Focus (Updated: 2026-03-22)

### Email Template Management System

Recent work has focused on the email template management system, which is a critical component for managing automated
communications in the MPS project management system.

**Recent Implementation:**

- Email template CRUD operations with admin interface
- Template editing with Jinja2 syntax highlighting
- AJAX endpoints for template management
- Integration with existing notification system

**Key Files Modified:**

- `app/models/emails.py` - Email template data models
- `app/ajax/email_templates/email_templates.py` - AJAX endpoints for template operations
- `app/templates/admin/email_templates/edit.html` - Template editor interface
- `app/templates/admin/email_templates/list.html` - Template listing interface

### Current Status

The email template system is functional but may need additional testing and refinement. The system allows administrators
to:

- Create and edit email templates using Jinja2 syntax
- Preview templates before sending
- Manage template metadata (subject, sender info)
- Categorize templates by purpose

## Active Technical Patterns

### Email Template Architecture

1. **Model Layer**: `EmailTemplate` model in `app/models/emails.py`
    - Stores template content, metadata, and configuration
    - Links to notification system

2. **View Layer**: AJAX endpoints handle template operations
    - Server-side processing for template lists
    - Individual template CRUD operations

3. **Template Rendering**: Jinja2 syntax used for dynamic content
    - Context variables injected at send time
    - Preview capabilities for testing

### AJAX Pattern Usage

The email template system follows the established AJAX pattern:

- Server-side DataTables processing via `ServerSideProcessing.py`
- JSON responses for create/update/delete operations
- Error handling with flash messages
- Transaction rollback on failures

## Important Project Preferences

### Code Organization

- Admin functionality in `app/admin/` blueprint
- AJAX endpoints in `app/ajax/` organized by feature area
- Templates follow blueprint structure in `app/templates/`
- Models consolidated in `app/models/` by logical grouping

### Database Patterns

- SQLAlchemy ORM for all database operations
- Explicit transaction management with rollback
- Cascading deletes configured at model level
- Audit trails via timestamp fields

### UI/UX Patterns

- Bootstrap-based responsive design
- DataTables for list views with server-side processing
- Flash messages for user feedback
- Modal dialogs for edit operations
- WYSIWYG or syntax-highlighted editors for content

## Next Steps

### Email Template System

1. **Testing**: Verify template rendering with various context data
2. **Validation**: Ensure Jinja2 syntax validation on save
3. **Documentation**: Document available template variables per template type
4. **Integration**: Test integration with existing notification workflows

### General Project Health

1. **Code Review**: Review recent changes for consistency
2. **Testing**: Run test suite to verify no regressions
3. **Documentation**: Update API documentation if endpoints changed
4. **Deployment**: Prepare migration scripts if schema changed

## Recent Learnings

### Email Template System Design

- Jinja2 integration requires careful context management
- Template preview needs same context as actual sending
- Version control of templates may be needed for audit purposes
- Template categories help organize large numbers of templates

### Project Architecture Insights

- AJAX pattern provides good separation of concerns
- Server-side DataTables processing handles large datasets efficiently
- Blueprint organization keeps code modular and maintainable
- Flash message pattern provides consistent user feedback

## Known Issues & Considerations

### Technical Debt

- Some older views may not follow current AJAX patterns
- Test coverage may be incomplete for newer features
- Documentation may lag behind implementation

### Performance Considerations

- Email template rendering should be cached where possible
- Large template lists need pagination (handled by DataTables)
- Database queries should use eager loading for relationships

### Security Considerations

- Template content should be sanitized to prevent XSS
- Jinja2 sandbox mode may be needed for user-editable templates
- Access control must restrict template editing to admins
- Email sending should have rate limiting