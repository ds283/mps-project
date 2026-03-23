# Product Context

## What is MPS Project?

The MPS (Multi-Project System) Project is a comprehensive web application designed to manage academic research projects,
supervisions, and assessments in a university setting. It serves as a central platform for coordinating the entire
lifecycle of student projects, from initial project proposals through to final assessment and archiving.

## Problem It Solves

### Academic Project Management Complexity

Universities face significant challenges in managing student projects:

1. **Project Coordination**
    - Faculty members propose hundreds of projects annually
    - Projects need approval workflows across multiple levels
    - Difficult to track which projects are available, in use, or archived
    - Hard to ensure fair distribution of supervision workload

2. **Student Selection Process**
    - Students need to browse, compare, and select projects
    - Matching students to projects requires complex algorithms
    - Selection process must be fair and transparent
    - Preferences and constraints must be balanced

3. **Supervision Management**
    - Tracking supervisor-student meetings is manual and error-prone
    - No centralized record of supervision activities
    - Difficult to monitor student progress
    - Event scheduling across multiple students and supervisors is complex

4. **Assessment Workflows**
    - Multiple assessors with different roles (first marker, second marker, external)
    - Complex marking schemes with weighted components
    - Moderation processes require coordination
    - Grade calculations must be accurate and auditable
    - External examiner review needs to be tracked

5. **Administrative Overhead**
    - Generating reports for different stakeholders is time-consuming
    - Email communications are scattered and inconsistent
    - Document management lacks organization
    - Audit trails are incomplete or missing

6. **Multi-Program Complexity**
    - Different academic programs have different requirements
    - Each program may run on different timelines
    - Policies and procedures vary by program
    - Need to maintain data isolation while sharing resources

## How It Works

### Core Workflows

#### 1. Project Lifecycle

```
Faculty Proposal → Approval Workflow → Publication → Student Selection → 
Assignment → Supervision → Assessment → Archive
```

**Faculty Perspective:**

- Faculty members create project proposals with descriptions, requirements, and tags
- Projects go through approval workflow (office, approvers, system)
- Approved projects become available for student selection
- Faculty supervise assigned students
- Faculty participate in assessment process

**Student Perspective:**

- Students browse available projects via Project Hub
- Students rank their project preferences
- System matches students to projects
- Students confirm or decline assignments
- Students participate in supervision meetings
- Students submit work for assessment

**Administrator Perspective:**

- Administrators (convenors) manage approval workflows
- Configure selection periods and algorithms
- Monitor supervision activities
- Coordinate assessment processes
- Generate reports and analytics

#### 2. Supervision Events

The system tracks all supervision interactions:

- Scheduled meetings between students and supervisors
- Attendance recording
- Progress notes
- Milestone tracking
- Intervention alerts for at-risk students

#### 3. Assessment Process

Multi-stage assessment with various roles:

- Marking schemas define grading criteria and weights
- Multiple assessors (supervisors, second markers, third markers, externals)
- Mark submission with component breakdowns
- Moderation workflows
- Final grade calculation with audit trail
- External examiner review and comments

#### 4. Communication

Automated and manual communication:

- Email templates for common scenarios
- Event-triggered notifications
- Scheduled reminders
- Bulk communications to cohorts
- Customizable message content

## User Experience Goals

### For Students

- **Easy project discovery**: Browse and search projects with rich filtering
- **Clear selection process**: Understand how selection works and track status
- **Supervision visibility**: See upcoming meetings and track progress
- **Document management**: Upload and organize project documents
- **Transparent assessment**: Understand grading criteria and timeline

### For Faculty

- **Efficient project creation**: Quick entry of project details with reuse of past projects
- **Manageable supervision**: Track all supervisees in one place
- **Fair workload**: System helps balance supervision load
- **Streamlined assessment**: Clear marking workflows with component tracking
- **Communication tools**: Easy to send updates to students

### For Administrators

- **Centralized control**: Manage all aspects from one dashboard
- **Process automation**: Reduce manual coordination work
- **Real-time monitoring**: See status of all projects and students
- **Flexible configuration**: Adapt system to program requirements
- **Comprehensive reporting**: Generate needed reports quickly

### For External Examiners

- **Remote access**: Review assignments and marks online
- **Clear context**: See full project and assessment history
- **Structured feedback**: Provide comments in organized format
- **Audit trail**: All reviews are recorded and timestamped

## Key Features

### Multi-Tenant Architecture

- Support for multiple academic programs
- Data isolation between tenants
- Shared infrastructure with program-specific customization
- Cross-tenant resource sharing where appropriate

### Approval Workflows

- Configurable multi-stage approval process
- Role-based approval routing
- Approval history and audit trails
- Email notifications at each stage
- Bulk approval operations

### Intelligent Matching

- Algorithm-based student-project matching
- Considers student preferences
- Respects project capacities and constraints
- Handles edge cases (e.g., declining students, over/under subscription)
- Generates fair outcomes

### Document Management

- Organized file storage by project and student
- Access control based on roles
- Version tracking for important documents
- Integration with object storage (MinIO/S3)
- Backup and archival support

### Rich Reporting

- Project status reports
- Supervision activity reports
- Assessment summary reports
- Student progress reports
- Faculty workload reports
- Exportable to various formats (PDF, Excel)

### Flexible Email System

- Template-based emails with Jinja2 syntax
- Context-aware variable substitution
- Preview before sending
- Scheduled and event-triggered emails
- Bulk email support
- Email tracking and history

### Comprehensive Audit Trails

- Track all significant actions
- User attribution for changes
- Timestamp all operations
- Support compliance requirements
- Enable debugging and troubleshooting

## Technical Differentiation

### Why This System?

Unlike generic project management tools, MPS Project is:

1. **Purpose-built for academia**: Understands academic workflows, roles, and requirements
2. **Handles complexity**: Multi-stage approvals, complex matching, detailed assessment
3. **Multi-tenant**: Supports multiple programs with isolation and customization
4. **Integrated**: All aspects of project management in one system
5. **Scalable**: Handles hundreds of projects and thousands of students
6. **Flexible**: Configurable to different academic program needs

### Competitive Advantages

- **Deep domain knowledge**: Built specifically for academic project management
- **Proven in production**: Active use in real academic settings
- **Comprehensive feature set**: Covers entire project lifecycle
- **Modern architecture**: Microservices-ready, scalable design
- **Open source potential**: Can be customized and extended

## Success Criteria

### User Satisfaction

- Students find projects they're interested in
- Faculty spend less time on administrative tasks
- Administrators have visibility and control
- Assessment process is fair and transparent

### Operational Efficiency

- Reduced manual coordination work
- Fewer errors in assignments and grading
- Faster turnaround on approvals and communications
- Better resource utilization

### Data Quality

- Complete records of all activities
- Accurate audit trails
- Reliable reporting data
- Consistent data across system

### System Reliability

- High availability during critical periods (selection, deadlines)
- Data integrity maintained
- Secure handling of sensitive information
- Performant under load

## Future Vision

### Short-term Enhancements

- Improved mobile experience
- Enhanced analytics and dashboards
- Better integration with external systems
- Expanded notification options

### Long-term Evolution

- Machine learning for better matching
- Real-time collaboration features
- Advanced analytics and predictions
- API for third-party integrations
- Broader applicability beyond original use case