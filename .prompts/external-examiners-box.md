## Summary

The codebase already features functionality to hold a Box OAuth token allowing upload.
This task will implement to upload assets to a specified Box folder.

## Upload per `MarkingWorkflow`

In the `MarkingWorkflow` inspector
`app/templates/convenor/markingevent/event_marking_workflows_inspector.html`,
please add a menu item "Externals upload to Box..." to the "Actions" dropdown menu
rendered by the AJAX row formatter.