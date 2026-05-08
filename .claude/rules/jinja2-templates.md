---
paths:
  - app/templates/**
---

# Jinja2 templates

## Global context

The following variables are available in the global context for all templates:

- `is_faculty` is True for users with a "faculty" role
- `is_student` is True for users with a "student" role
- `is_convenor` is True for users with a "convenor" role (not necessarily for the project class relevant for the template)
- `is_root` is True for users with a "root" role
- `is_admin` is True for users with an "admin" role
- `is_office` is True for users with an "office" role
- `is_authenticated` is True for authenticated users
- `current_user` is the current user object
- `current_tenant` is the current tenant object

Look in `_build_global_context()` in `app/shared/context/global_context.py` for more variables.

## Bootstrap markup

- Prefer not to use `bg-info` or `text-info` classes, which are hard to read.
- Do not use `text-warning` which is hard to read.
