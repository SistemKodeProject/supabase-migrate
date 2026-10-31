#!/usr/bin/env python3
"""
STEP 1b: RESTORE DATABASE ke project TARGET.
Jalanin: python3 2_restore_database.py [--step schema|auth|storage|data|sequences|all]

Butuh: psql sudah di PATH, dan file dump dari 1_dump_database.py sudah ada
di OUTPUT_DIR (default ./migration_output).

PENTING: script ini TIDAK dump ulang dari SOURCE. Kalau salah satu tahap
restore gagal, benerin masalahnya (misal cek log_*.txt), lalu jalanin lagi
dengan --step <bagian yang gagal> aja - gak perlu dump ulang atau
mengulang tahap yang sudah sukses.

Urutan default (--step all): schema -> auth -> storage -> data -> sequences
Urutan ini PENTING karena foreign key public.* nunjuk ke auth.users,
jadi auth harus di-restore duluan sebelum public data.
"""

import argparse
import os
from pathlib import Path

from common import (
    header, ok, warn, fail, die, load_env, get_conn, pg_args,
    output_dir, require_binary, run, run_with_retry, test_conn, query_values,
)


CLEAN_SCHEMA_SQL = """
SET session_replication_role = replica;
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = '{schema}'
      -- tabel yang kita gak punya izin INSERT/DELETE (tabel internal service
      -- Supabase kayak schema_migrations, buckets_vectors, vector_indexes, dll)
      -- di-skip di sini secara dinamis lewat has_table_privilege, BUKAN hardcode
      -- nama - soalnya daftar tabel internal ini beda-beda tiap versi Supabase.
      AND has_table_privilege(format('%I.%I', schemaname, tablename)::regclass, 'DELETE')
  LOOP
    EXECUTE format('DELETE FROM %I.%I', '{schema}', r.tablename);
  END LOOP;
END $$;
SET session_replication_role = origin;
"""


def clean_schema(dst, schema):
    """
    Hapus semua row di semua tabel pada schema tsb (pakai DELETE + replica mode,
    BUKAN TRUNCATE, biar gak ke-cascade ke tabel public yang mungkin punya FK
    ke schema ini - misal auth.users dipakai FK oleh public.quiz_user_progress dll).
    Ini yang bikin step auth/storage aman dijalanin BERKALI-KALI kapanpun,
    walau run sebelumnya sempat insert sebagian lalu terputus.
    """
    warn(f"Membersihkan data lama di schema '{schema}' (biar gak duplicate key pas re-insert)...")
    success = run(
        ["psql", *pg_args(dst), "-v", "ON_ERROR_STOP=1"],
        env_extra={"PGPASSWORD": dst["password"]},
        input_text=CLEAN_SCHEMA_SQL.format(schema=schema),
    )
    if not success:
        die(f"Gagal membersihkan schema '{schema}' sebelum restore!")
    ok(f"Schema '{schema}' sudah bersih, siap di-insert ulang")


def require_dump_file(out_dir, filename):
    path = Path(out_dir) / filename
    if not path.exists():
        die(
            f"File {path} tidak ditemukan.\n"
            f"      Jalankan dulu: python3 1_dump_database.py --step "
            f"{filename.replace('.sql', '').replace('public_', '').replace('_data', '')}"
        )
    return str(path)


RESTORE_SCHEMA_GRANTS_SQL = """
GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO postgres, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON ROUTINES TO postgres, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO postgres, anon, authenticated, service_role;
"""


def reset_target_schema(dst):
    warn("Reset schema public di TARGET (biar bersih dari sisa run sebelumnya)...")
    warn("PERINGATAN: ini akan MENGHAPUS semua tabel/type/function di schema public TARGET saat ini!")

    # DROP SCHEMA public CASCADE ikut nge-drop extension yang di-install di
    # schema public (misal postgis -> public.geography). Catat dulu, terus
    # bikin ulang setelah schema dibuat lagi, biar dump yang refer ke
    # public.geography/public.geometry dll gak error "type does not exist".
    public_exts = query_values(
        dst, "SELECT extname FROM pg_extension WHERE extnamespace = 'public'::regnamespace;"
    )
    recreate_exts = "".join(
        f'CREATE EXTENSION IF NOT EXISTS "{ext}" WITH SCHEMA public;' for ext in public_exts
    )
    success = run(
        ["psql", *pg_args(dst), "-v", "ON_ERROR_STOP=1",
         "-c", "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;" + recreate_exts],
        env_extra={"PGPASSWORD": dst["password"]},
    )
    if not success:
        die("Gagal reset schema public di TARGET!")
    ok("Schema public TARGET sudah bersih")
    if public_exts:
        ok(f"Extension di schema public dibuat ulang: {', '.join(public_exts)}")

    # PENTING: CREATE SCHEMA public yang baru itu gak otomatis punya GRANT
    # ke role anon/authenticated/service_role kayak yang di-setup default sama
    # Supabase pas provisioning awal project. Kalau ini kelewat, PostgREST bakal
    # nolak SEMUA query dari app (client-side) dengan "permission denied for
    # schema public" walau data & tabelnya sendiri udah ke-restore dengan benar.
    warn("Restore GRANT default Supabase ke schema public (anon/authenticated/service_role)...")
    success = run(
        ["psql", *pg_args(dst), "-v", "ON_ERROR_STOP=1", "-c", RESTORE_SCHEMA_GRANTS_SQL],
        env_extra={"PGPASSWORD": dst["password"]},
    )
    if not success:
        die("Gagal restore GRANT default ke schema public!")
    ok("GRANT default schema public sudah dipulihkan")


def split_webhook_triggers(sql_file, out_dir):
    """
    Pisahin trigger Database Webhook (EXECUTE FUNCTION supabase_functions.http_request)
    dari dump schema. Schema supabase_functions cuma ada kalau fitur Database
    Webhooks sudah di-enable di project, jadi di TARGET baru biasanya belum ada
    -> restore gagal "schema supabase_functions does not exist".
    Selain itu URL & service_role key di trigger masih nunjuk ke project SOURCE,
    jadi di-rewrite ke TARGET pakai *_PROJECT_REF & *_SERVICE_ROLE_KEY dari .env.
    File dump asli gak diubah; hasilnya ditulis ke file terpisah.
    """
    replacements = [
        (os.environ.get("SOURCE_PROJECT_REF", ""), os.environ.get("TARGET_PROJECT_REF", "")),
        (os.environ.get("SOURCE_SERVICE_ROLE_KEY", ""), os.environ.get("TARGET_SERVICE_ROLE_KEY", "")),
    ]
    main_lines, webhook_lines = [], []
    with open(sql_file, "r", encoding="utf-8") as f:
        for line in f:
            if "supabase_functions." in line:
                for old, new in replacements:
                    if old and new:
                        line = line.replace(old, new)
                webhook_lines.append(line)
            else:
                main_lines.append(line)

    main_file = f"{out_dir}/public_schema_no_webhooks.sql"
    with open(main_file, "w", encoding="utf-8") as f:
        f.writelines(main_lines)
    webhook_file = None
    if webhook_lines:
        webhook_file = f"{out_dir}/public_webhook_triggers.sql"
        with open(webhook_file, "w", encoding="utf-8") as f:
            f.writelines(webhook_lines)
    return main_file, webhook_file, len(webhook_lines)


def restore_webhook_triggers(dst, out_dir, webhook_file, count):
    has_schema = query_values(
        dst, "SELECT 1 FROM pg_namespace WHERE nspname = 'supabase_functions';"
    )
    if not has_schema:
        warn(f"{count} trigger Database Webhook DI-SKIP: schema 'supabase_functions' belum ada di TARGET.")
        warn("      Enable dulu: Dashboard TARGET > Database > Webhooks > Enable webhooks,")
        warn(f"      lalu jalanin: psql ... -f {webhook_file}")
        return
    if not (os.environ.get("TARGET_PROJECT_REF") and os.environ.get("TARGET_SERVICE_ROLE_KEY")):
        warn("TARGET_PROJECT_REF / TARGET_SERVICE_ROLE_KEY kosong -> URL/key webhook masih nunjuk SOURCE!")
    warn(f"Restoring {count} trigger Database Webhook...")
    log_file = f"{out_dir}/log_public_webhook_triggers_restore.txt"
    success = run(
        ["psql", *pg_args(dst), "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", webhook_file],
        env_extra={"PGPASSWORD": dst["password"]},
        log_file=log_file,
    )
    if not success:
        fail(f"Gagal restore trigger webhook (struktur lain aman). Cek {log_file}")
        return
    ok("Trigger Database Webhook ter-restore")


def restore_schema(dst, out_dir):
    sql_file = require_dump_file(out_dir, "public_schema.sql")
    sql_file, webhook_file, webhook_count = split_webhook_triggers(sql_file, out_dir)
    reset_target_schema(dst)
    warn("Restoring structure ke TARGET...")
    log_file = f"{out_dir}/log_public_schema_restore.txt"
    success = run(
        ["psql", *pg_args(dst), "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", sql_file],
        env_extra={"PGPASSWORD": dst["password"]},
        log_file=log_file,
    )
    if not success:
        die(f"Gagal restore public schema! Cek {log_file}")
    ok("Struktur public ter-restore")
    if webhook_file:
        restore_webhook_triggers(dst, out_dir, webhook_file, webhook_count)


def restore_data_only(dst, out_dir, sql_filename, log_filename, label):
    sql_file = require_dump_file(out_dir, sql_filename)
    warn(f"Migrating {label}...")
    log_file = f"{out_dir}/{log_filename}"
    # NB: pakai session_replication_role=replica (bukan --disable-triggers) karena
    # tabel di schema auth/storage dimiliki role supabase_auth_admin/supabase_storage_admin,
    # bukan postgres -> ALTER TABLE DISABLE TRIGGER akan gagal (must be owner of table).
    # --single-transaction (-1) membungkus semua -c dan -f di atas jadi SATU transaksi
    # (1x BEGIN di awal, 1x COMMIT di akhir), bukan commit per-statement/per-baris.
    # Ini krusial buat kecepatan: tanpa ini, tiap baris INSERT = 1 round-trip + 1 commit
    # terpisah ke server, yang kalau server-nya jauh (misal region lain) jadi SANGAT lambat
    # untuk file dengan ribuan baris. Efek sampingnya: kalau ada 1 baris gagal, SEMUA baris
    # di file ini di-rollback (bukan partial) - ini aman & malah lebih bersih untuk di-retry.
    success = run(
        ["psql", *pg_args(dst), "-v", "ON_ERROR_STOP=1", "--single-transaction",
         "-c", "SET session_replication_role = replica;",
         "-f", sql_file,
         "-c", "SET session_replication_role = origin;"],
        env_extra={"PGPASSWORD": dst["password"]},
        log_file=log_file,
    )
    if not success:
        die(f"Gagal restore {label}! Cek {log_file}")
    ok(f"{label} ter-restore")


def restore_auth(dst, out_dir):
    clean_schema(dst, "auth")
    restore_data_only(dst, out_dir, "auth_data.sql", "log_auth_restore.txt", "AUTH data")
    warn("Catatan: password hash ikut pindah, user tetep bisa login normal.")


def restore_storage_meta(dst, out_dir):
    clean_schema(dst, "storage")
    restore_data_only(dst, out_dir, "storage_data.sql", "log_storage_restore.txt", "STORAGE metadata")
    warn("Ini cuma metadata. File fisiknya migrasi pakai 3_dump_storage.py + 4_restore_storage.py")


def restore_public_data(dst, out_dir):
    clean_schema(dst, "public")
    tables_dir = Path(out_dir) / "public_data_tables"
    if tables_dir.is_dir() and any(tables_dir.glob("*.sql")):
        restore_public_data_per_table(dst, out_dir, tables_dir)
    else:
        # Fallback: dump lama (versi sebelum per-tabel) cuma punya 1 file gede.
        restore_data_only(dst, out_dir, "public_data.sql", "log_public_data_restore.txt", "PUBLIC data")


def restore_public_data_per_table(dst, out_dir, tables_dir):
    """
    Restore public_data_tables/*.sql SATU-SATU (masing-masing --single-transaction
    sendiri), bukan satu file gede dalam satu transaksi. Alasannya: kalau ada
    1 tabel yang gagal (misal "relation ... does not exist" karena TARGET
    belum sinkron sama SOURCE), pendekatan lama bikin SEMUA tabel lain ikut
    rollback walau sebenernya gak ada masalah. Dengan per-tabel, tabel yang
    OK tetap ke-restore, dan yang gagal dilaporin jelas biar bisa dibenerin
    lalu di-retry sendiri tanpa restore ulang semuanya.
    """
    warn("Restoring PUBLIC data satu tabel per satu tabel (biar 1 tabel bermasalah gak nge-gagalin semua)...")
    sql_files = sorted(tables_dir.glob("*.sql"))
    failed = []
    for i, sql_file in enumerate(sql_files, 1):
        table = sql_file.stem
        print(f"      [{i}/{len(sql_files)}] {table}...", end=" ", flush=True)
        log_file = Path(out_dir) / f"log_public_data_restore_{table}.txt"
        success = run_with_retry(
            ["psql", *pg_args(dst), "-v", "ON_ERROR_STOP=1", "--single-transaction",
             "-c", "SET session_replication_role = replica;",
             "-f", str(sql_file),
             "-c", "SET session_replication_role = origin;"],
            env_extra={"PGPASSWORD": dst["password"]},
            log_file=str(log_file),
            quiet=True,
        )
        if success:
            print("OK")
            log_file.unlink(missing_ok=True)  # gak perlu nyimpen log kalau sukses
        else:
            print("GAGAL")
            failed.append(table)

    if failed:
        fail(f"{len(failed)} tabel GAGAL di-restore: {', '.join(failed)}")
        warn("Kalau errornya 'relation ... does not exist': schema TARGET belum sinkron")
        warn("sama data yang di-dump (misal ada tabel baru di SOURCE setelah terakhir kali")
        warn("'--step schema' dijalankan). Fix-nya:")
        warn("  1. python3 1_dump_database.py --step schema   (dump ulang struktur terbaru)")
        warn("  2. python3 2_restore_database.py --step schema (aman, ini reset+recreate public)")
        warn("  3. python3 2_restore_database.py --step data   (retry restore data)")
        warn(f"Detail error per tabel: {out_dir}/log_public_data_restore_<nama_tabel>.txt")
        die(f"Restore PUBLIC data selesai SEBAGIAN ({len(sql_files) - len(failed)}/{len(sql_files)} tabel berhasil).")

    ok(f"PUBLIC data ter-restore ({len(sql_files)} tabel)")


RESET_SEQ_SQL = """
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT sequence_schema, sequence_name,
           REPLACE(REPLACE(sequence_name,'_id_seq',''),'_seq','') AS tbl
    FROM information_schema.sequences WHERE sequence_schema='public'
  LOOP
    BEGIN
      EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(id) FROM %I.%I), 1))',
        r.sequence_schema||'.'||r.sequence_name, r.sequence_schema, r.tbl);
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
  END LOOP;
END $$;
"""


def reset_sequences(dst, out_dir):
    warn("Reset sequences biar id auto-increment gak tabrakan...")
    success = run(
        ["psql", *pg_args(dst), "-v", "ON_ERROR_STOP=1"],
        env_extra={"PGPASSWORD": dst["password"]},
        input_text=RESET_SEQ_SQL,
    )
    if not success:
        die("Gagal reset sequences!")
    ok("Sequences di-reset")


def main():
    parser = argparse.ArgumentParser(description="Restore database Supabase (TARGET only)")
    parser.add_argument(
        "--step",
        choices=["schema", "auth", "storage", "data", "sequences", "all"],
        default="all",
        help="Restore cuma satu bagian aja, misalnya kalau tahap sebelumnya gagal (default: all)",
    )
    args = parser.parse_args()

    require_binary("psql", "install: sudo apt install postgresql-client")

    load_env()
    dst = get_conn("TARGET")
    out_dir = output_dir()

    header("SUPABASE RESTORE DATABASE (file lokal -> TARGET)")

    warn("Testing connection ke TARGET...")
    test_conn(dst, "TARGET")

    steps = {
        "schema": lambda: restore_schema(dst, out_dir),
        "auth": lambda: restore_auth(dst, out_dir),
        "storage": lambda: restore_storage_meta(dst, out_dir),
        "data": lambda: restore_public_data(dst, out_dir),
        "sequences": lambda: reset_sequences(dst, out_dir),
    }

    if args.step == "all":
        # Urutan ini wajib: schema dulu (biar tabel kebentuk), lalu auth
        # (biar FK auth.users valid), baru storage & public data, terakhir sequences.
        for name in ["schema", "auth", "storage", "data", "sequences"]:
            print(f"\n{'-'*56}")
            steps[name]()
    else:
        print(f"\n{'-'*56}")
        steps[args.step]()

    header("RESTORE SELESAI!")
    print(f"Cek log_*.txt di {out_dir}/ kalau ada yang mau divalidasi")
    print("Lanjut: python3 3_dump_storage.py (migrasi file fisik di storage)")


if __name__ == "__main__":
    main()
