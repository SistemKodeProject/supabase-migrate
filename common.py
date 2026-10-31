"""
common.py
Helper bersama untuk semua script migrasi Supabase (Linux/Python version).
Tidak perlu diimpor manual - dipakai otomatis oleh script 1-5.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ---------- Warna terminal ----------
class C:
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def ok(msg):
    print(f"{C.GREEN}      OK - {msg}{C.RESET}")


def fail(msg):
    print(f"{C.RED}      GAGAL - {msg}{C.RESET}")


def warn(msg):
    print(f"{C.YELLOW}      {msg}{C.RESET}")


def info(msg):
    print(f"{C.YELLOW}{msg}{C.RESET}")


def header(title):
    line = "=" * 56
    print(f"\n{C.CYAN}{line}\n  {title}\n{line}{C.RESET}")


def die(msg):
    fail(msg)
    sys.exit(1)


# ---------- Load .env ----------
def load_env(env_path=".env"):
    """Parse file .env sederhana (KEY=VALUE) dan masukkan ke os.environ."""
    path = Path(env_path)
    if not path.exists():
        die(f"File {env_path} tidak ditemukan. Copy dari .env.example dulu.")

    pattern = re.compile(r"^\s*([^#][^=]*)=(.*)$")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = pattern.match(line.rstrip("\n"))
            if not m:
                continue
            key = m.group(1).strip()
            val = m.group(2).strip()
            os.environ[key] = val


def get_conn(prefix):
    """Ambil dict koneksi (host/port/db/user/password) dari env berdasar prefix SOURCE_/TARGET_."""
    return {
        "host": os.environ.get(f"{prefix}_HOST", ""),
        "port": os.environ.get(f"{prefix}_PORT", "5432"),
        "db": os.environ.get(f"{prefix}_DB", "postgres"),
        "user": os.environ.get(f"{prefix}_USER", ""),
        "password": os.environ.get(f"{prefix}_PASSWORD", ""),
    }


def pg_args(conn):
    return ["-h", conn["host"], "-p", str(conn["port"]), "-U", conn["user"], "-d", conn["db"]]


def output_dir():
    d = os.environ.get("OUTPUT_DIR", "./migration_output")
    Path(d).mkdir(parents=True, exist_ok=True)
    return d


# ---------- Cek binary tersedia ----------
def require_binary(name, hint=""):
    if shutil.which(name) is None:
        extra = f" ({hint})" if hint else ""
        die(f"'{name}' tidak ditemukan di PATH{extra}.")


# ---------- Jalankan command, tampilkan live output, opsional tee ke log file ----------
def run(cmd, env_extra=None, log_file=None, input_text=None, quiet=False):
    """
    Jalankan subprocess, print output secara live (kecuali quiet=True), dan
    (opsional) simpan ke log_file.
    Return True kalau exit code 0, False kalau gagal.

    Selalu nyetel PGCONNECT_TIMEOUT & PGOPTIONS (kalau belum di-set di env)
    biar koneksi ke Session Pooler lebih tahan banting - beberapa project
    Supabase punya statement_timeout pendek yang bikin dump tabel gede
    keputus ("SSL connection has been closed unexpectedly").
    """
    env = os.environ.copy()
    env.setdefault("PGCONNECT_TIMEOUT", "30")
    env.setdefault("PGOPTIONS", "-c statement_timeout=0 -c idle_in_transaction_session_timeout=0")
    if env_extra:
        env.update(env_extra)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1,
    )

    lines = []
    if input_text is not None:
        proc.stdin.write(input_text)
        proc.stdin.close()

    for line in proc.stdout:
        if not quiet:
            print(line, end="")
        lines.append(line)

    proc.wait()

    if log_file:
        with open(log_file, "w", encoding="utf-8") as f:
            f.writelines(lines)

    if quiet and proc.returncode != 0:
        # Kalau quiet tapi gagal, tetep tampilin output-nya biar keliatan errornya.
        sys.stdout.write("".join(lines))

    return proc.returncode == 0


# ---------- Jalankan command dengan auto-retry (buat koneksi pooler yang suka putus) ----------
def run_with_retry(cmd, env_extra=None, log_file=None, input_text=None, quiet=False,
                    retries=None, backoff=None):
    """
    Sama kayak run(), tapi retry otomatis kalau gagal (misal SSL connection
    closed di tengah dump tabel gede). Jumlah retry & jeda antar-retry bisa
    di-override lewat env DUMP_RETRIES / DUMP_RETRY_BACKOFF, default 3x
    dengan jeda 5 detik (bertambah tiap percobaan).
    """
    if retries is None:
        retries = int(os.environ.get("DUMP_RETRIES", "3"))
    if backoff is None:
        backoff = int(os.environ.get("DUMP_RETRY_BACKOFF", "5"))

    attempt = 0
    while True:
        attempt += 1
        success = run(cmd, env_extra=env_extra, log_file=log_file,
                       input_text=input_text, quiet=quiet)
        if success:
            return True
        if attempt >= retries:
            return False
        wait_s = backoff * attempt
        warn(f"Gagal (percobaan {attempt}/{retries}), retry dalam {wait_s}s...")
        time.sleep(wait_s)


def test_conn(conn, label):
    warn(f"Testing connection ke {label}...")
    ok_flag = run(
        ["psql", *pg_args(conn), "-c", "SELECT 1;"],
        env_extra={"PGPASSWORD": conn["password"]},
    )
    if not ok_flag:
        die(f"Tidak bisa konek ke {label}!")
    ok(f"Terkoneksi ke {label}")


def strip_create_schema_public(sql_path):
    """Hapus baris 'CREATE SCHEMA public;' dari hasil pg_dump (schema itu udah otomatis ada di Supabase)."""
    with open(sql_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    with open(sql_path, "w", encoding="utf-8") as f:
        for line in lines:
            if line.strip() != "CREATE SCHEMA public;":
                f.write(line)

def query_values(conn, sql):
    """
    Jalanin query yang hasilnya 1 kolom, return list of string (baris kosong dibuang).
    Dipakai buat query "diam-diam" (gak nge-print live output kayak run()),
    misalnya buat ambil daftar nama tabel yang dipakai internal oleh script.
    """
    result = subprocess.run(
        ["psql", *pg_args(conn), "-t", "-A", "-c", sql],
        env={**os.environ, "PGPASSWORD": conn["password"]},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        die(f"Query gagal: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


UNWRITABLE_TABLES_SQL = """
SELECT tablename FROM pg_tables
WHERE schemaname = '{schema}'
  AND NOT (
    has_table_privilege(format('%I.%I', schemaname, tablename)::regclass, 'INSERT')
    AND has_table_privilege(format('%I.%I', schemaname, tablename)::regclass, 'DELETE')
  );
"""


def get_public_tables(conn, schema="public"):
    """
    Ambil daftar nama base table (bukan view) di suatu schema, terurut nama.
    Dipakai buat dump data satu-satu per tabel (bukan sekali pg_dump raksasa),
    supaya kalau satu tabel gede/koneksi putus di tengah, tabel lain tetap
    kesimpen dan yang gagal gampang di-retry sendiri.

    Tabel milik extension (misal spatial_ref_sys punya postgis) di-skip: isinya
    udah otomatis dibikin sama CREATE EXTENSION di TARGET, dan owner-nya
    supabase_admin jadi gak bisa di-insert ulang.
    """
    sql = f"""
    SELECT c.relname FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = '{schema}' AND c.relkind IN ('r', 'p')
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend d
        WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'
      )
    ORDER BY c.relname;
    """
    return query_values(conn, sql)


def get_unwritable_tables(conn, schema):
    """
    Cari tabel di suatu schema yang role koneksi ini TIDAK punya izin INSERT/DELETE
    (biasanya tabel internal service Supabase kayak auth.schema_migrations,
    storage.buckets_vectors, storage.vector_indexes, dll - daftar ini beda-beda
    tergantung versi GoTrue/Storage tiap project, makanya dicek dinamis, bukan
    hardcode nama, biar gak whack-a-mole tiap ada tabel internal baru).
    """
    return query_values(conn, UNWRITABLE_TABLES_SQL.format(schema=schema))
