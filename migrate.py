#!/usr/bin/env python3
"""
Single entry point for the migration scripts.

    python3 migrate.py <command> [args passed through to the script]

Commands:
    dump-db            -> 1_dump_database.py
    restore-db         -> 2_restore_database.py
    dump-storage       -> 3_dump_storage.py
    restore-storage    -> 4_restore_storage.py
    functions          -> 5_migrate_edge_functions.py
    download-storage   -> 6_download_storage.py
    push-backup        -> push_local_backup.py

Examples:
    python3 migrate.py dump-db --step data
    python3 migrate.py restore-storage --only avatars
    python3 migrate.py download-storage --dry-run

The numbered scripts still work on their own; this wrapper only saves typing.
"""

import os
import subprocess
import sys

COMMANDS = {
    "dump-db": "1_dump_database.py",
    "restore-db": "2_restore_database.py",
    "dump-storage": "3_dump_storage.py",
    "restore-storage": "4_restore_storage.py",
    "functions": "5_migrate_edge_functions.py",
    "download-storage": "6_download_storage.py",
    "push-backup": "push_local_backup.py",
}


def usage(code=0):
    print(__doc__.strip())
    sys.exit(code)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        usage(0 if len(sys.argv) >= 2 else 1)
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}\n")
        usage(1)
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, COMMANDS[cmd])
    sys.exit(subprocess.call([sys.executable, script, *sys.argv[2:]]))


if __name__ == "__main__":
    main()
