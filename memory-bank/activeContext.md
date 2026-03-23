# Active Context

## Current Work Focus (Updated: 2026-03-23)

### ATAS Campaign System for 2026

Recent work has focused on implementing an ATAS (Academic Technology Approval Scheme) campaign system for the 2026
academic year. This system helps manage project availability for students who are subject to ATAS restrictions.

**Recent Implementation:**

- Added ATAS campaign tracking to Tenant model
- Created campaign-specific workflows for faculty to update projects
- Implemented project tag assignment enforcement
- Dynamic form generation for project ATAS status and labeling

**Key Files Modified/Created:**

- `app/models/tenants.py` - Added `in_2026_ATAS_campaign` field to Tenant model
- `app/campaigns/tools.py` - Campaign logic for checking and processing ATAS projects
- `app/campaigns/views.py` - View handler for ATAS 2026 campaign workflow
- Related template files for campaign UI

### Current Status

The ATAS campaign system is operational and allows:

- Tracking which tenants are participating in the 2026 ATAS campaign
- Faculty members to update ATAS restrictions on their projects
- Enforcement of project tag requirements for ATAS-enabled project classes
- Dynamic form generation based on each faculty member's active projects
- Bulk processing of project updates with validation

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

### ATAS Campaign System

1. **Testing**: Verify campaign workflow with various faculty project configurations
2. **Validation**: Ensure all ATAS-enabled projects are properly tagged
3. **Documentation**: Document ATAS campaign process for administrators
4. **Monitoring**: Track campaign participation and completion rates

### General Project Health

1. **Code Review**: Review ATAS campaign implementation for consistency
2. **Testing**: Run test suite to verify no regressions from new campaign feature
3. **Documentation**: Update administrator documentation with ATAS campaign instructions
4. **Deployment**: Prepare migration scripts for tenant model changes

## Recent Learnings

### ATAS Campaign System Design

- Campaign-specific features can be tied to tenant configuration
- Dynamic form generation allows flexible handling of variable project lists
- Faculty-facing workflows need clear guidance and validation
- Project tag enforcement can be integrated with campaign workflows

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
- Campaign-based features benefit from dedicated blueprint organization

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