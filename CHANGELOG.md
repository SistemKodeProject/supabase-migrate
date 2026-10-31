# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `migrate.py`: single entry point that dispatches to the numbered scripts.
- `folder_map.example.json` and `--map` option for `push_local_backup.py`.
- MIT license, English README, CONTRIBUTING, SECURITY, issue and PR templates.
- GitHub Actions CI: byte-compile, ruff lint, CLI smoke tests, secret scan.
- `requirements.txt` and ruff configuration in `pyproject.toml`.

### Changed
- `push_local_backup.py` reads its local-folder to bucket mapping from
  `folder_map.json` instead of a hardcoded list.
- `.gitignore` and `.env.example` no longer reference project-specific names.
- Indonesian README moved to `README.id.md`.

## [0.1.0] - 2026-10-19

### Added
- Database dump and restore split into two scripts with per-step retry.
- Per-table data dump with retry and backoff; `EXCLUDE_DATA_TABLES` support.
- Dynamic detection of unwritable Supabase-internal tables during restore.
- Storage bucket dump via Postgres (avoids Storage API egress quota) and
  restore with `rclone` S3 to S3 sync.
- Edge function migration via the Supabase CLI with per-account access tokens.
- Read-only local download of storage files, and push of a local backup to
  TARGET when SOURCE is quota-locked.
