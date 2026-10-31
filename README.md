# Supabase Migration Tools

Move a whole Supabase project (database, auth users, storage buckets and files,
edge functions) to another Supabase project, with plain Python scripts you can
run step by step and re-run safely when something fails halfway.

[Bahasa Indonesia](README.id.md)

## Why this exists

Supabase has no built-in "clone this project" button, and the official
guides leave several gaps once your project is real-world sized:

- **IPv6-only direct connections.** `db.<ref>.supabase.co` no longer
  resolves on many home and office networks. These scripts use the Session
  Pooler endpoint, which has IPv4.
- **Dumps that die halfway.** Pooler connections and short
  `statement_timeout`s cut off large `pg_dump`s. Data is dumped **per table**
  with automatic retry and backoff, so one broken table never costs you the
  whole dump.
- **Dump and restore are separate.** If a restore step fails, fix the cause
  and re-run only that step. You never have to dump SOURCE again.
- **Supabase-internal tables.** Tables you cannot write to (for example
  `auth.schema_migrations`) are detected dynamically rather than hardcoded,
  so the scripts keep working as GoTrue and Storage change.
- **Egress quota locks.** Bucket metadata is read via Postgres instead of the
  Storage API, and storage files are synced S3 to S3 with `rclone`. There is
  also a path for pushing a local backup when SOURCE is locked by
  `exceed_egress_quota`.
- **Cross-account migrations.** Edge functions deploy with separate access
  tokens for SOURCE and TARGET.

## What gets migrated

| Component | How | Script |
|---|---|---|
| `public` schema (tables, RLS policies) | `pg_dump` schema-only | `1_dump_database.py` / `2_restore_database.py` |
| `auth` data (users, identities) | `pg_dump` data-only | same |
| `storage` metadata (buckets, object index) | `pg_dump` data-only | same |
| `public` data | per-table `pg_dump` with retry | same |
| Sequences | reset after restore | `2_restore_database.py --step sequences` |
| Storage buckets config | Postgres query, saved as `buckets.json` | `3_dump_storage.py` / `4_restore_storage.py` |
| Storage files | `rclone sync` S3 to S3 | `4_restore_storage.py` |
| Edge functions | Supabase CLI deploy | `5_migrate_edge_functions.py` |

Not migrated automatically (set these in the new project's dashboard):
edge function **secret values**, auth provider OAuth credentials, custom SMTP,
custom domains.

## Requirements

- Python 3.10+ and `pip install -r requirements.txt` (only `requests`)
- PostgreSQL client tools: `pg_dump`, `psql`
  (`sudo apt install postgresql-client` on Debian/Ubuntu, `brew install libpq` on macOS)
- [`rclone`](https://rclone.org/downloads) for storage files
- [Supabase CLI](https://supabase.com/docs/guides/cli) for edge functions

Tested on Linux and macOS. A PowerShell variant for Windows is maintained
separately.

## Quick start

```bash
git clone https://github.com/SistemKodeProject/supabase-migrate
cd supabase-migrate
pip install -r requirements.txt
cp .env.example .env    # fill in SOURCE_* and TARGET_*
```

Where each value comes from:

| Variable | Dashboard location |
|---|---|
| `*_HOST`, `*_USER`, `*_PORT` | Project Settings > Database > Connect > **Session pooler** tab. User is `postgres.<project_ref>`, not just `postgres`. |
| `*_PROJECT_REF` | the subdomain in `https://<ref>.supabase.co` |
| `*_SERVICE_ROLE_KEY` | Project Settings > API |
| `*_S3_ACCESS_KEY`, `*_S3_SECRET_KEY`, `*_S3_ENDPOINT` | Project Settings > Storage > S3 Connection > New access key |
| `*_ACCESS_TOKEN` | https://supabase.com/dashboard/account/tokens (per account) |

Then run the steps in order. Every script can also be run directly
(`python3 1_dump_database.py`); `migrate.py` just saves typing.

```bash
python3 migrate.py dump-db            # 1. SOURCE -> migration_output/*.sql   (read-only on SOURCE)
python3 migrate.py restore-db         # 2. migration_output/*.sql -> TARGET   (resets public schema on TARGET)
python3 migrate.py dump-storage       # 3. SOURCE bucket config -> buckets.json
python3 migrate.py restore-storage    # 4. recreate buckets + rclone sync S3 -> S3
python3 migrate.py functions          # 5. deploy supabase/functions/ to TARGET
```

## Step details

### 1. Dump database (SOURCE only)

```bash
python3 1_dump_database.py [--step schema|auth|storage|data|all]
```

Writes `public_schema.sql`, `auth_data.sql`, `storage_data.sql` and
`public_data.sql` to `OUTPUT_DIR` (default `./migration_output`). Safe to
run repeatedly. `--step data` re-dumps only the public table data.

Tuning in `.env`: `EXCLUDE_DATA_TABLES` to skip big log tables,
`DUMP_RETRIES` and `DUMP_RETRY_BACKOFF` for flaky connections.

### 2. Restore database (TARGET only)

```bash
python3 2_restore_database.py [--step schema|auth|storage|data|sequences|all]
```

Order matters: `schema -> auth -> storage -> data -> sequences`, because
`public.*` foreign keys point at `auth.users`. **`--step schema` drops and
recreates the `public` schema on TARGET.** If a step fails, read
`migration_output/log_*.txt`, fix the cause, and re-run only that step.

### 3. Dump storage buckets (SOURCE only)

```bash
python3 3_dump_storage.py
```

Reads `storage.buckets` through Postgres (not the Storage REST API, which
returns HTTP 402 when the project is over its egress quota) and writes
`migration_output/buckets.json`.

### 4. Restore buckets and sync files

```bash
python3 4_restore_storage.py [--only BUCKET] [--skip-sync]
```

Recreates each bucket on TARGET (existing buckets are left untouched), then
`rclone sync`s files directly from SOURCE S3 to TARGET S3. Interrupted? Run it
again with `--only <bucket>`; rclone skips files that already match.

### 5. Edge functions

```bash
python3 5_migrate_edge_functions.py
```

Downloads functions from SOURCE if `supabase/functions/` is empty, links the
CLI to TARGET, deploys every function, and lists the secret **names** on
SOURCE. Secret values are never exposed by Supabase, so set them manually:

```bash
supabase secrets set NAME=value --project-ref <TARGET_PROJECT_REF>
```

### Optional: local storage backup

```bash
python3 6_download_storage.py [--from SOURCE|TARGET] [--dest DIR] [--only BUCKET ...] [--dry-run]
```

Read-only. Downloads every object to `./storage_backup/<project_ref>/<bucket>/...`
with `rclone copy`. Re-run to resume.

### Optional: push a local backup to TARGET

```bash
cp folder_map.example.json folder_map.json   # describe your folder -> bucket layout
python3 push_local_backup.py /path/to/backup [--map folder_map.json] [--dry-run]
```

For when SOURCE is quota-locked but you have the files locally. Needs only
`TARGET_*` credentials.

## Verifying the result

```bash
psql -h <TARGET_HOST> -p 5432 -U postgres.<TARGET_REF> -d postgres
```

```sql
SELECT COUNT(*) FROM auth.users;
SELECT COUNT(*) FROM storage.objects;
\dt public.*
```

Compare the counts with SOURCE.

## Troubleshooting

**`could not translate host name`**: you are using the direct connection
host. Switch `*_HOST` to the Session Pooler endpoint and `*_USER` to
`postgres.<project_ref>`.

**`SSL connection has been closed unexpectedly` during dump**: a pooler
timeout on a big table. The per-table dump retries automatically; raise
`DUMP_RETRIES` or exclude the table with `EXCLUDE_DATA_TABLES` if it keeps
failing.

**Foreign key errors on restore**: run `2_restore_database.py` without
`--step` so `auth` is restored before `data`.

**HTTP 402 from the Storage API**: SOURCE is over its egress quota. Step 3
already avoids the API; for files use `push_local_backup.py` with a backup
you made earlier.

**`rclone: command not found`**: put the extracted binary in `/usr/local/bin`.

## Safety notes

- Dump scripts only read from SOURCE. Restore scripts only write to TARGET.
- `migration_output/` contains `auth.users` with password hashes. It is
  git-ignored; treat it as a production backup and delete it when done.
- Rotate the keys and tokens you used after the migration. See
  [SECURITY.md](SECURITY.md).

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
Test against throwaway projects only.

## License

[MIT](LICENSE)
