# Contributing

Thanks for taking the time to contribute.

## Reporting bugs

Open an issue using the bug report template. Include the script name, the
`--step`/options you used, and the relevant log excerpt from
`migration_output/`. **Strip hostnames, project refs, keys and user data
before pasting.**

## Development setup

```bash
git clone https://github.com/SistemKodeProject/supabase-migrate
cd supabase-migrate
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt ruff
cp .env.example .env   # fill with a throwaway test project, never production
```

Checks that CI runs:

```bash
python -m py_compile *.py
ruff check .
python migrate.py --help
```

## Testing changes safely

Always test against two throwaway Supabase projects (free tier is enough).
Restore scripts **reset the `public` schema on TARGET**, so never point
`TARGET_*` at a project you care about while developing.

## Pull requests

- One logical change per PR.
- Keep the dump/restore split: scripts that read from SOURCE must never
  write to it, and restore scripts must never touch SOURCE.
- Update `README.md` (and `README.id.md` if you can) when options change.
- Add a line to `CHANGELOG.md` under *Unreleased*.
- Never commit `.env`, `migration_output/`, `storage_backup/` or
  `folder_map.json`. CI runs a secret scan and will fail the build.

## Code style

- Python 3.10+, standard library plus `requests` only.
- `ruff` with the config in `pyproject.toml`.
- Console output helpers live in `common.py` (`ok`, `warn`, `fail`, `die`,
  `header`). Use them instead of bare `print` for status lines.
- New user-facing text should be in English. Existing Indonesian strings are
  being translated gradually; PRs that translate them are welcome.
