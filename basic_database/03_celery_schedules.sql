INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (3, 'Prune email log at 104 weeks', 'app.tasks.prune_email.prune_email_log', 5, null, 'null', '{"interval": "weeks", "duration": 104}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (5, 'Scheduled backup', 'app.tasks.backup.backup', 13, null, 'null', '{"type": 1, "tag": "backup", "description": "Regular scheduled backup"}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (6, 'Thin backups', 'app.tasks.backup.thin', 7, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (7, 'Enforce maximum backup size', 'app.tasks.backup.limit_size', 8, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (9, 'Drop absent backups', 'app.tasks.backup.drop_absent_backups', 8, null, 'null', '{}', 'default', null, null, null, 0, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (10, 'Update LiveProject popularity data', 'app.tasks.popularity.update_popularity_data', 6, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (11, 'Thin LiveProject popularity data', 'app.tasks.popularity.thin', 7, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (12, 'Regular database maintenance', 'app.tasks.maintenance.maintenance', 8, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (13, 'Garbage collection for expired assets', 'app.tasks.maintenance.asset_garbage_collection', 8, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (17, 'Garbage collection for batch student import', 'app.tasks.batch_create.garbage_collection', 8, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (18, 'Process pings from front-end clients', 'app.tasks.system.process_pings', 11, null, 'null', '{}', 'priority', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (19, 'Send email notifications', 'app.tasks.email_notifications.send_daily_notifications', null, 1, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (20, 'Perform MongoDB session maintenance', 'app.tasks.sessions.sift_sessions', 8, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (21, 'Synchronize Canvas user database with submitter databases', 'app.tasks.canvas.canvas_user_checkin', 8, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (22, 'Synchronize Canvas submission availability for active submission periods', 'app.tasks.canvas.canvas_submission_checkin', 8, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (23, 'Prune background task list at 6 weeks', 'app.tasks.background_tasks.prune_background_tasks', 5, null, 'null', '{"interval": "weeks", "duration": 6}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (24, 'Test for lost assets', 'app.tasks.maintenance.asset_check_lost', 12, null, '["D.Seery@sussex.ac.uk"]', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (25, 'Test for unattached assets', 'app.tasks.maintenance.asset_check_unattached', 12, null, '["D.Seery@sussex.ac.uk"]', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (26, 'Test for and fix unencrypted assets', 'app.tasks.maintenance.fix_unencrypted_assets', 14, null, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
INSERT INTO celery_schedules (id, name, task, interval_id, crontab_id, arguments, keyword_arguments, queue, exchange, routing_key, expires, enabled, last_run_at, total_run_count, date_changed, owner_id) VALUES (27, 'Send Cloud API audit events to telemetry bucket', 'app.tasks.cloud_api_audit.send_api_events_to_telemetry', null, 2, 'null', '{}', 'default', null, null, null, 1, null, 0, null, 1);
