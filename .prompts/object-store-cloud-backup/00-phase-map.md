# Object store cloud backup — phase map

Eight phases, each a standalone Claude Code prompt.
All prompts live at `.prompts/object-store-cloud-backup/`.

| Phase | File | Scope | Kind |
|-------|------|-------|------|
| 1 | `phase1-provider-layer.md` | Chunked upload + folder-listing cache in `BoxCloudStorageProvider` and `CloudStorageProvider` ABC | Python only |
| 2 | `phase2-orm-model.md` | `ObjectStoreBackupRecord` model + Alembic migration | Python only |
| 3 | `phase3-backup-task.md` | `app/tasks/object_store_backup.py` — backup Beat task only | Python only |
| 4 | `phase4-beat-schedule.md` | `initdb.py` schedule registration + `instance/local.py` config keys | Python only |
| 5 | `phase5-restore-task.md` | Restore tasks (`restore_object_store_bucket`, `restore_all_object_store_buckets`) | Python only |
| 6 | `phase6-routes.md` | Flask routes + `CloudBackupConfigForm` + `CloudBackupRestoreForm` in `admin/forms.py` | Python only |
| 7 | `phase7-cloud-tab-template.md` | `cloud_backup.html` template + AJAX formatter | Template only |
| 8 | `phase8-overview-integration.md` | `nav.html` pill + cloud-status strip in `overview.html` | Template only |

## Dependency order

```
Phase 1 (provider layer)
    └── Phase 2 (ORM model)
            └── Phase 3 (backup task)
                    └── Phase 4 (schedule + config)
                    └── Phase 5 (restore tasks)
                            └── Phase 6 (routes + forms)
                                    └── Phase 7 (cloud tab template)
                                    └── Phase 8 (overview integration)
```

Phases 7 and 8 are independent of each other and can run in either order
after Phase 6.
