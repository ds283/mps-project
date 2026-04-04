## DESCRIPTION

This task aims to improve the functionality and performance of tracking of background Celery tasks launched via the
`TaskRecord` system.

`TaskRecord` models are used to record information about Celery tasks that are launched within the web user interface.
The intention is that the user can be notified about progress of the task, and especially when the task fails. However,
this is not properly implemented in practice.

- If the Celery workflow fails, this is not properly detected and the `TaskRecord` is orphaned and never updated. Such
  tasks create a backlog of tasks stored in the back end in the `RUNNING` state, but which are not really running.
- When the app starts up, there is no check whether the associated task is still running or has produced output in the
  Celery results backend. This is another way that `TaskRecord` instances become orphaned.

Please consider these problems and make a recommendation for how to fix both issues.

- On startup we wish to check whether tasks in the `TaskWorkflowStatesMixin.PENDING` or
  `TaskWorkflowStatesMixin.RUNNING` states are still running present in the Celery queue. If present, the workflow state
  held on the `TaskRecord` instance should be updated. If they are no longer present, and no result is available in the
  Celery results backend, some default action must be taken, probably to mark the task as `TERMINATED`.

- Please consider whether the design of Celery workflows in the application is suitable for the intended use case. The
  intention is that Celery task ids are assigned via the register_task() function. However, if workflows replace
  themslves with other workflows (chains, groups, or chords), will these task ids mutate?

- It would be preferable not to have to poll for the state of each task, which is inefficient

