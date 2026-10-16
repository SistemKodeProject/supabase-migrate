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
import os
import sys
from pathlib import Path

from common import (
    header, ok, warn, fail, die, load_env, get_conn, pg_args,
    output_dir, require_binary, run, run_with_retry, test_conn,
    strip_create_schema_public, get_unwritable_tables, get_public_tables,
)


def dump_schema(src, out_dir):
    warn("Dumping PUBLIC schema (structure only: tables, RLS policies, functions, triggers)...")
    target_file = f"{out_dir}/public_schema.sql"
    success = run_with_retry(
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
    skip_tables = get_unwritable_tables(src, "auth")
    if skip_tables:
        warn(f"Skip tabel internal auth (gak ada izin INSERT/DELETE): {', '.join(skip_tables)}")
    success = run_with_retry(
        [
            "pg_dump", *pg_args(src),
            "--schema=auth", "--data-only",
            *[f"--exclude-table-data=auth.{t}" for t in skip_tables],
            "--no-owner", "--no-privileges",
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
    skip_tables = get_unwritable_tables(src, "storage")
    if skip_tables:
        warn(f"Skip tabel internal storage (gak ada izin INSERT/DELETE): {', '.join(skip_tables)}")
    success = run_with_retry(
        [
            "pg_dump", *pg_args(src),
            "--schema=storage", "--data-only",
            *[f"--exclude-table-data=storage.{t}" for t in skip_tables],
            "--no-owner", "--no-privileges",
            "--format=plain", f"--file={target_file}",
        ],
        env_extra={"PGPASSWORD": src["password"]},
    )
    if not success:
        die("Gagal dump storage data!")
    ok(f"storage_data.sql tersimpan di {target_file}")
    warn("Catatan: ini cuma metadata. File fisiknya migrasi pakai 3_dump_storage.py + 4_restore_storage.py")

def dump_public_data(src, out_dir):
    """
    Dump data schema public SATU TABEL PER SATU TABEL (bukan sekali pg_dump
    buat semua tabel sekaligus). Alasannya: kalau ada tabel gede (misal
    log/webhook table) yang bikin koneksi ke Session Pooler putus di tengah
    ("SSL connection has been closed unexpectedly"), pendekatan lama bikin
    SELURUH dump gagal dan tabel yang udah kelar ikut hilang. Dengan per-tabel:
    - tiap tabel gagal otomatis di-retry (lihat run_with_retry / DUMP_RETRIES)
    - tabel yang berhasil TETAP kesimpen walau ada tabel lain yang gagal
    - tabel yang mau di-skip total bisa diset di .env: EXCLUDE_DATA_TABLES=a,b,c
    """
    warn("Dumping PUBLIC data (isi semua tabel, satu per satu biar tahan gangguan koneksi)...")
    target_file = f"{out_dir}/public_data.sql"

    exclude_env = os.environ.get("EXCLUDE_DATA_TABLES", "")
    excluded = {t.strip() for t in exclude_env.split(",") if t.strip()}
    if excluded:
        warn(f"Skip data tabel (dari EXCLUDE_DATA_TABLES di .env): {', '.join(sorted(excluded))}")

    tables = [t for t in get_public_tables(src) if t not in excluded]
    if not tables:
        die("Gak ada tabel public buat di-dump (cek EXCLUDE_DATA_TABLES di .env).")

    tables_dir = Path(out_dir) / "public_data_tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    # Bersihin sisa file tabel dari run sebelumnya (misal ada tabel yang udah
    # dihapus di SOURCE, biar gak ke-restore data basi punya tabel itu).
    for old_file in tables_dir.glob("*.sql"):
        old_file.unlink()

    open(target_file, "w", encoding="utf-8").close()  # kosongin/buat file

    failed = []
    for i, table in enumerate(tables, 1):
        print(f"      [{i}/{len(tables)}] {table}...", end=" ", flush=True)
        tmp_file = tables_dir / f"{table}.sql"
        success = run_with_retry(
            [
                "pg_dump", *pg_args(src),
                "--data-only",
                f'--table=public."{table}"',
                "--no-owner", "--no-privileges",
                "--format=plain", f"--file={tmp_file}",
            ],
            env_extra={"PGPASSWORD": src["password"]},
            quiet=True,
        )
        if not success:
            print("GAGAL")
            failed.append(table)
            tmp_file.unlink(missing_ok=True)
            continue
        print("OK")
        with open(tmp_file, "r", encoding="utf-8") as f_in, \
             open(target_file, "a", encoding="utf-8") as f_out:
            f_out.write(f_in.read())
        # NB: tmp_file per-tabel SENGAJA dibiarkan ada di public_data_tables/
        # (bukan dihapus) - dipakai 2_restore_database.py buat restore per-tabel juga.

    if failed:
        fail(f"{len(failed)} tabel GAGAL di-dump setelah {os.environ.get('DUMP_RETRIES', '3')}x percobaan: {', '.join(failed)}")
        warn("Data tabel di atas TIDAK ada di public_data.sql. Opsi:")
        warn("  1. Jalankan ulang 'python3 1_dump_database.py --step data' (tabel yang udah OK bakal didump ulang juga, gpp)")
        warn("  2. Kalau tabelnya emang gak penting (misal log/webhook), tambahin ke .env: EXCLUDE_DATA_TABLES=" + ",".join(failed))
        die("Dump public data selesai SEBAGIAN (ada tabel yang gagal, lihat di atas).")

    ok(f"public_data.sql tersimpan di {target_file} ({len(tables)} tabel)")


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