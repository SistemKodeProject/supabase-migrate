# Security

These scripts handle production credentials and full database dumps.

- `.env`, `migration_output/`, `storage_backup/` and `folder_map.json` are
  git-ignored on purpose. Never force-add them.
- Dumps include `auth.users` (emails and password hashes). Treat the
  `migration_output/` folder like a production backup: encrypt it at rest and
  delete it when the migration is done.
- Rotate the service role keys, S3 keys and personal access tokens you used
  once the migration is complete.

To report a vulnerability in the scripts themselves, open a private security
advisory on GitHub or email the maintainers listed in the repository. Please
do not open a public issue for security reports.
