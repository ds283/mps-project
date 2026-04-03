## PREAMBLE

The purpose of this task is to develop a tracking pixel implementation for `EmailWorkflow`
instances.

Design a tracking pixel implementation based on the `EmailWorkflow`, `EmailWorkflowItem` and `EmailLog` models.

- Use of a tracking pixel should be configurable at the level of an `EmailWorkflow`. You will need to add a new field
  `use_tracking_pixel` to the `EmailWorkflow` model in order to persist the configuration. Allow this setting to be
  edited in emailworkflow.edit_workflow()
- HTML to to inject the trackig pixel should be generated at the time of sending the email in send_workflow_item().
  Please consider whether it is preferable to persist the unique identifier describing the tracking pixel on the
  `EmailWorkflowItem` or is corresponding `EmailLog`, and make a recommendation. We will want to persist the actual
  timestamp associated with retrieval of the tracking pixel on the `EmailLog` instance, NOT on `EmailWorkflowItem`,
  because the `EmailWorkflowItem` can be cleaned up later. When this happens, we do not wish to lose access to the
  tracking data.
- A new route will be needed to serve the tracking pixel. This should query for the unique identifier and produce a
  timestamp showing when the email was opened.
- Adjust the display_email() route and its template to show whether the email was opened, and if so, the timestmap.
- Surface work-flow level tracking information to the `EmailWorkflow` inspector. In particular, consider the following
  pieces of data:
    - How many emails in the workflow have been opened, and how many are unchanged.
    - The timestamp of the first email opened.
    - The timestamp of the last email opened.