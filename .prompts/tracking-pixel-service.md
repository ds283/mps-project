## PREAMBLE

The purpose of this task is to develop a tracking pixel implementation for `EmailWorkflow`
instances.

### TASK 1. The tracking pixel implementation

Design a tracking pixel implementation based on the `EmailWorkflow`, `EmailWorkflowItem` and `EmailLog` models. The main
use case is that we'd like to know which students

- Use of a tracking pixel should be configurable at the level of an `EmailWorkflow`. You will need to add a new field
  `use_tracking_pixel` to the `EmailWorkflow` model in order to persist the configuration. Allow this setting to be
  edited in emailworkflow.edit_workflow()
- HTML to inject the trackig pixel should be generated at the time of sending the email in send_workflow_item().
  Please consider whether it is preferable to persist the unique identifier describing the tracking pixel on the
  `EmailWorkflowItem` or is corresponding `EmailLog`, and make a recommendation. We will want to persist the actual
  timestamp associated with retrieval of the tracking pixel on the `EmailLog` instance, NOT on `EmailWorkflowItem`,
  because the `EmailWorkflowItem` can be cleaned up later. When this happens, we do not wish to lose access to the
  tracking data.
- Please consider whether the HTML linking to the tracking pixel should be persisted in the database as part of the
  logged `EmailLog` instance and make a recommendation.
    - Pros: maximally explicit, does not hide information, shows the URL that was actually generated and passed to the
      recipient
    - Cons: raises risk of accidental activation of the tracking route
- A new route will be needed to serve the tracking pixel. This should query for the unique identifier and produce a
  timestamp showing when the email was opened.
- Adjust the display_email() route and its template to show whether the email was opened, and if so, the timestmap.
- Surface work-flow level tracking information to the `EmailWorkflow` inspector. In particular, consider the following
  pieces of data:
    - How many emails in the workflow have been opened, and how many are unchanged.
    - The timestamp of the first email opened.
    - The timestamp of the last email opened.

### TASK 2. Improve clean up of EmailWorkflow instances

Currently, there is a period task prune_email_log() in @app/tasks/email.py that deletes all `EmailLog` instances older
than a fixed cutoff. This is intended to prevent the email log from growing unboundedly large. In the current deployment
this is set at 104 weeks = 2 years.

We should also clean up EmailWorkflow instances that have been completed. It is useful to keep these around for some
time (especially if they are going to capture some engagement data at the level of an entire workflow). Probably the 104
week timescale is the right one to apply.

- Determine the current behaviour when `EmailLog` items are pruned. Are their linked `EmailWorkflowItem` instances left
  in the database? Likewise, determine the current behaviour when `EmailWorkflow` instances are pruned. Are `EmailLog`
  instances left orphaned in the database?
- Make a recommendation as to whether it is better to manage the lifecycle of `EmailLog` and `EmailWorkflowItem`
  instances together, rather than allowing them to become decoupled.
    - Pros for independence: there might be some scenarios where we need to know what email was actually sent, perhaps
      for compliance reasons, but the engagement-tracking provided by `EmailWorkflow` need not be retained
    - Pros for managing together: simplifies lifecycle management

Develop a recommendation for pruning old `EmailWorkflow` instances, either as part of general maintenance of `EmailLog`
or separately, as appopriate, depending on the outcome of the above.

### TASK 3. Improve visual presentation of @app/templates/admin/display_email.html

This is an old template, and its appearance is rather rudimentary. Develop a proposal to refine its visual style and
appearance, although keeping the overall UI experience consistent with the rest of the application.

- Where a linked `EmailWorkflowItem` instance is present, surface information to viewers with "admin" or "root" level
  roles about the `EmailWorkflowItem` instance and the `EmailWorkflow` it is drawn from.
- In these cases, also surface information about the engagement-tracking provided by `EmailWorkflow`
- Show whether this email is recorded as having been opened