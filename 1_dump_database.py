#!/usr/bin/env python3
"""
STEP 1a: DUMP DATABASE dari project SOURCE.
Jalanin: python3 1_dump_database.py [--step schema|auth|storage|data|all]

Butuh: pg_dump & psql (dari postgresql-client) sudah di PATH.
    sudo apt install postgresql-client

Script ini HANYA baca dari SOURCE. Tidak menyentuh TARGET sama sekali,
jadi aman dijalankan berkali-kali. Hasilnya disimpan sebagai file .sql
di OUTPUT_DIR (default ./migration_output), dipakai oleh 2_restore_database.py.
"""

import argparse
import sys
from pathlib import Path

from common import (
    header, ok, warn, die, load_env, get_conn, pg_args,
    output_dir, require_binary, run, test_conn, strip_create_schema_public,
)


def dump_schema(src, out_dir):
    warn("Dumping PUBLIC schema (structure only: tables, RLS policies, functions, triggers)...")
    target_file = f"{out_dir}/public_schema.sql"
    success = run(
        [
            "pg_dump", *pg_args(src),
            "--schema=public", "--schema-only",
            "--no-owner", "--no-privileges", "--no-tablespaces", "--no-comments",
            "--format=plain", f"--file={target_file}",
        ],
        env_extra={"PGPASSWORD": src["password"]},
    )
    if not success:
        die("Gagal dump public schema!")
    strip_create_schema_public(target_file)
    ok(f"public_schema.sql tersimpan di {target_file}")


def dump_auth(src, out_dir):
    warn("Dumping AUTH data (users, identities, dll)...")
    target_file = f"{out_dir}/auth_data.sql"
    success = run(
        [
            "pg_dump", *pg_args(src),
            "--schema=auth", "--data-only",
            # schema_migrations itu tabel internal buat Supabase Auth service (GoTrue)
            # sendiri buat nge-track versi migrasinya. Role postgres sengaja dikunci gak
            # bisa DELETE/INSERT ke tabel ini (permission denied), dan restore data ini
            # ke TARGET juga gak perlu - versi migrasi TARGET dikelola sendiri oleh
            # instance Supabase itu, independen dari SOURCE.
            "--exclude-table-data=auth.schema_migrations",
            "--no-owner", "--no-privileges", "--column-inserts",
            "--format=plain", f"--file={target_file}",
        ],
        env_extra={"PGPASSWORD": src["password"]},
    )
    if not success:
        die("Gagal dump auth data!")
    ok(f"auth_data.sql tersimpan di {target_file}")


def dump_storage(src, out_dir):
    warn("Dumping STORAGE metadata (bucket & object index, BUKAN file fisik)...")
    target_file = f"{out_dir}/storage_data.sql"
    success = run(
        [
            "pg_dump", *pg_args(src),
            "--schema=storage", "--data-only",
            # storage.migrations sama kayak auth.schema_migrations - tabel internal
            # buat Supabase Storage service sendiri, postgres gak punya izin tulis ke situ.
            "--exclude-table-data=storage.migrations",
            "--no-owner", "--no-privileges", "--column-inserts",
            "--format=plain", f"--file={target_file}",
        ],
        env_extra={"PGPASSWORD": src["password"]},
    )
    if not success:
        die("Gagal dump storage data!")
    ok(f"storage_data.sql tersimpan di {target_file}")
    warn("Catatan: ini cuma metadata. File fisiknya migrasi pakai 3_dump_storage.py + 4_restore_storage.py")


def dump_public_data(src, out_dir):
    warn("Dumping PUBLIC data (isi semua tabel)...")
    target_file = f"{out_dir}/public_data.sql"
    success = run(
        [
            "pg_dump", *pg_args(src),
            "--schema=public", "--data-only",
            "--no-owner", "--no-privileges", "--column-inserts",
            "--format=plain", f"--file={target_file}",
        ],
        env_extra={"PGPASSWORD": src["password"]},
    )
    if not success:
        die("Gagal dump public data!")
    ok(f"public_data.sql tersimpan di {target_file}")


def main():
    parser = argparse.ArgumentParser(description="Dump database Supabase (SOURCE only)")
    parser.add_argument(
        "--step", choices=["schema", "auth", "storage", "data", "all"], default="all",
        help="Dump cuma satu bagian aja (default: all)",
    )
    args = parser.parse_args()

    require_binary("pg_dump", "install: sudo apt install postgresql-client")
    require_binary("psql", "install: sudo apt install postgresql-client")

    load_env()
    src = get_conn("SOURCE")
    out_dir = output_dir()

    header("SUPABASE DUMP DATABASE (SOURCE -> file lokal)")

    warn("Testing connection ke SOURCE...")
    test_conn(src, "SOURCE")

    steps = {
        "schema": dump_schema,
        "auth": dump_auth,
        "storage": dump_storage,
        "data": dump_public_data,
    }

    if args.step == "all":
        for name, fn in steps.items():
            print(f"\n{'-'*56}")
            fn(src, out_dir)
    else:
        print(f"\n{'-'*56}")
        steps[args.step](src, out_dir)

    header("DUMP SELESAI!")
    print(f"File tersimpan di: {out_dir}/")
    print("Lanjut: python3 2_restore_database.py")


if __name__ == "__main__":
    main()