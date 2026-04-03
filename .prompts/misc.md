- In schedule_close_marking_window() from @app/tasks/markingevent.py, please check whether multiple
  `DatabaseSchedulerEntry` instances will be generated if a marker returns to edit their report within the 24 hour
  window and reubmits the form. In this case, the desired behaviour is that editing window continues to close at 24
  hours from the **original submission**. If a `DatabaseSchedulerEntry` exists for this `MarkingReport`, then a new one
  should not be generated.