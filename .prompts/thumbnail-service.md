## DESCRIPTION

This task is intended to implement a thumbail service for SubmittedAsset and GeneratedAsset models. It does not
apply to any other type of asset.

Thumbnail assets are to be stored in the "thumbails" bucket associated with `buckets.THUMBNAILS_BUCKET`
in @app/shared/cloud-object-store/bucket_types.py. This bucket can be obtained from the `OBJECT_STORAGE_BUCKETS`
dict defined in the local.py configuration file. This is imported into the running Flask app using
app.config.from_pyfile() in @app/__init__.py.

Access to the object bucket goes through the ObjectStore abstraction. This is defined in
@app/shared/cloud-object-store/base.py. Interactions with the bucket should STRICTLY use only the
methods defined in this class.

Do not generate log_db_commit() calls in this task. These are automated workflows that we don't wish
to record in the workflow log, which is intended to record user-initiated actions (or actions where
we need an audit trail). This task doesn't fit into those categories.

This is a long refactoring task. Please write a status file to disk that can be committed to the repsoitory,
so that state can be recovered correctly if the task runs over several rate limit windows. Update this
status file periodically as you perform the refactorings.

## TASK 1

Design a Celery workflow to accept a GeneratedAsset or SubmittedAsset and generate a thumbnail for it.

The task should download the physical asset from the ObjectStore. Use the AssetCloudAdapter pattern to
do this, defined in @app/shared/asset_tools.py.

Once the asset is available, generate: (1) a "small" 200x200 thumbnail, and (2) a "medium" 400x400 thumbnail
using the preview-generator Python package, which you can assume to be installed. You may need to review the
GitHub homepage for this package at https://github.com/algoo/preview-generator.

This package needs a cache directory. We do not want thumbnails to accumulate within the Docker container and
its ephemeral file system. To fix this, we want to generate a new "scratch" cache each time we invoke
the generator. Plan an analogue of the ScratchFileManager context manager in @app/shared/scratch.py to obtain
a throwaway folder inside the app's scratch directory, which is cleaned up automatically when the context
manager exists. Use this as the cache directory from preview-generator. You can use the same cache for
generation of the "small" and "medium" thumbnails.

If both thumbnails generate correctly then they should be uploaded to the "thumbnails" bucket.
Generate ThumbnailAsset instances for these thumbnails and save them to the database.
Use the AssetUploadManager pattern defined in @app/shared/asset_tools.py. Read the upload_submitter_report()
view in @app/documents/views.py for an example of how to use this pattern.
The ThuumbnailAsset instances should be linked to the `small_thumbnail` and `medium_thumbnail` relationships
on GeneratedAsset and SubmittedAsset.

If an error occurs, then mark the `thumbnail_error` flag and save an error message, if possible to
the `thumbnail_error_message` field. If no error occurs, ensure `thumbnail_error` is set to False
and `thumbnail_error_message` is set to None.

## TASK 2

Revise all locations in the app where a GeneratedAsset or SubmittedAsset is created, and adjust these to
run the Celery thumbnailing task. Use appropriate helper functions to avoid repeating code.
You do not need to wait on the output of the thumbnailing task; it can be used fire-and-forget.

## TASK 3

Design a repeating maintenance task to check each GeneratedAsset and SubmittedAsset in the database
for thumbnails that are missing. If it finds missing assets, it should initiate a thumbnailing task,
unless the `thumbnail_error` flag is set to True, in which case it should be ignored. Add the signature
for this task to the ScheduledTaskMixin class in @app/admin/forms.py.

If either or both thumbail assets are marked as `lost`, then the ThumbnailAssets should be removed
and an attempt made to regenerate the thumbnails.

## TASK 4

Refactor the inspect_assets() view in @app/admin/utilities.py and the row formatter for its associated AJAX endpoint to
display an approriately sized thumbnail as part of the table. To do so you will need to obtain a URL
for the thumbnail from its object bucket, which is preferable to downloading the asset to the container's
ephemeral filesystem and re-serving it from there. However, you will need to stream the data from the URL
through the Flask app. This is because the object storage server will be reachable from the Flask app,
but may not be reachable from the public internet (either it is running in a Docker private network or it
is behind a corporate VPN). Plan and implement a mechanism to do this effectively, bearing in mind best
practices for Flask.

Although this view will show only one thumbail, surface information about both thumbnails in the display,
including their timestamp.

The inspect_assets() view should not separately show thumbail assets. It should only show them
as part of the display for their parent GeneratedAsset or SubmittedAsset.

The inspect_assets() view should surface any error states recorded by the `thumbnail_error` flag and
the `thumbnail_error_message` field. Design an attractive and professional UI to do so.

The inspect_assets() view should also surface any `lost` status to the user.

## TASK 5

When assets are deleted (mainly due to expiry), any dependent ThumbnailAssets instances should likewise be
deleted and any physical assets should be deleted from the object bucket.

Refactor maintenance asset_check_lost() and asset_check_unattached() to also check ThumbnailAsset instances.
It should check whether a ThumbnailAsset is attached to a GeneratedAsset or SubmittedAsset, and delete it if not.

Check the logic of the workflows that have been defined to ensure that ThumbnailAssets do not become orphaned.

## TASK 6

Refactor the @app/templates/documents/submitter_manager.html template to present a thumbnail for each
SubmittedAsset or GeneratedAsset that it shows. Use the pass-through-Flask service constructed in TASK 4 to
generate the URLs.

Refactor the @app/templates/convenor/docuemnts/period_manager.html template to present a thumbnail for each
SubmittedAsset or GeneratedAsset that it shows.

Refactor the @app/templates/convenor/markingevent/add_workflow_attachment.html template to present a
thumbnail for each SubmittedAsset or GeneratedAsset that it shows.

Refactor the @app/templates/convenor/markingeventedit_marking_workflow.html template to present a
thumbnail for each SubmittedAsset or GeneratedAsset that is attached to the workflow.

Refactor the @app/templates/student/dashboard/view_feedback.html template to present a thumbnail for each
SubmittedAsset or GeneratedAsset that it shows.

Refactor the @app/templates/convenor/dashboard/view_feedback.html template to present a thumbnail for each
SubmittedAsset or GeneratedAsset that it shows.

For now, leave the app/templates/faculty/view_feedback.html template along. This will soon be replaced.

