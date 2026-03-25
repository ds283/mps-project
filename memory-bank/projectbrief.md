# Project Brief: MPS Project Management System

## Project Name

MPS Project (Major Projects System)

## Core Purpose

A comprehensive web-based platform for managing student Major Projects (dissertations, final year projects) within an
academic institution. The system facilitates the entire lifecycle from project proposal through completion, managing
relationships between students, faculty supervisors, markers, and project convenors.

## Primary Goals

### Academic Process Management

- Manage project lifecycles across multiple academic years
- Handle project proposals, approvals, and assignments
- Track student progress through milestones and submissions
- Coordinate faculty supervision and marking

### Multi-Role Support

- **Students**: Browse, select, and work on projects
- **Faculty**: Propose projects, supervise students, mark work
- **Convenors**: Oversee program-level project coordination
- **Project Approvers**: Review and approve project proposals
- **Administrators**: System configuration and user management

### Workflow Automation

- Automated task scheduling and reminders
- Email notifications for key events
- Background job processing (Celery)
- Scheduled maintenance and reporting

### Data Management

- Multi-tenant architecture supporting multiple academic programs
- Secure document storage and retrieval
- Historical records and archiving
- Comprehensive audit trails

## Target Users

- Academic institutions offering project-based courses
- Students undertaking major projects
- Faculty members supervising and marking projects
- Academic administrators managing project systems

## Success Criteria

- Streamlined project allocation process
- Clear visibility of project status for all stakeholders
- Reduced administrative overhead
- Accurate tracking of academic requirements
- Secure and compliant data handling

## Technical Foundation

- Python/Flask web application
- SQLAlchemy ORM with MySQL database
- Celery for async task processing
- Docker containerization
- Object storage for documents
- Multi-tenant architecture

## Current Status

Production system actively managing student projects at an academic institution. Recent development has focused on
implementing campaign-specific functionality to support institutional requirements, including ATAS compliance campaigns
and email template management systems.

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

(No visible files)

# PyCharm Professional Open Tabs

(No open tabs)

# Current Time

3/25/2026, 10:18:57 PM (Europe/London, UTC+0:00)

# Context Window Usage

26,425 / 131K tokens used (20%)

# Current Mode

ACT MODE
</environment_details>