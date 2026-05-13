## Summary

The similarity card detail inspector `app/templates/dashboard/similarity_concern_detail.html`
does not surface enough detail to allow the user to resolve the concern.

The A and B students in the pair are shown in 2-column format. Each student is identified by
name. Extra contextual information is given on a subrow: candidate number, project class name,
academic cycle.

In addition to this information, I would like to have:

- The project tile
- The project owner
- The names of any staff with defined `SubmissionRole`s for this `SubmissionRecord`. Group these
  by "Supervisors", "Markers", "Moderators". You need not include presentation assessors or
  other roles; these are the primary ones. 