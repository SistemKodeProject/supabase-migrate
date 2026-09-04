#!/usr/bin/env python3
"""
STEP 2a: DUMP STORAGE - ambil daftar bucket & konfigurasinya dari project SOURCE.
Jalanin: python3 3_dump_storage.py

Butuh: psql sudah di PATH.

CATATAN: versi ini query langsung ke tabel storage.buckets lewat koneksi
Postgres (SOURCE_HOST dkk di .env), BUKAN lewat Storage REST API. Ini sengaja
biar gak kena Storage API egress quota (kalau project SOURCE lagi kena limit
"exceed_egress_quota", API call ke /storage/v1/bucket bakal ditolak HTTP 402
walau cuma nge-list doang - koneksi Postgres langsung gak masuk hitungan itu).

Hasilnya disimpan sebagai migration_output/buckets.json, format & isinya
tetap sama kayak versi API lama, jadi kompatibel sama 4_restore_storage.py.
"""

import json
import sys

from common import (
    header, ok, warn, die, load_env, get_conn, pg_args,
    output_dir, require_binary, test_conn,
)

import os
import subprocess

BUCKETS_QUERY = (
    "SELECT COALESCE(json_agg(row_to_json(b)), '[]'::json) "
    "FROM (SELECT id, name, public, file_size_limit, allowed_mime_types "
    "FROM storage.buckets ORDER BY name) b;"
)


def fetch_buckets(src):
    result = subprocess.run(
        ["psql", *pg_args(src), "-t", "-A", "-c", BUCKETS_QUERY],
        env={**os.environ, "PGPASSWORD": src["password"]},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        die(f"Gagal query storage.buckets dari SOURCE: {result.stderr.strip()}")
    raw = result.stdout.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        die(f"Gagal parse hasil query jadi JSON. Output mentah:\n{raw}")


def main():
    require_binary("psql", "install: sudo apt install postgresql-client")

    load_env()
    src = get_conn("SOURCE")
    out_dir = output_dir()

    header("SUPABASE DUMP STORAGE (list bucket dari SOURCE, via Postgres langsung)")

    test_conn(src, "SOURCE")

    warn("Mengambil list bucket dari storage.buckets (SOURCE)...")
    buckets = fetch_buckets(src)

    if not buckets:
        warn("Gak ketemu bucket sama sekali di SOURCE - cek lagi kalau ini gak sesuai ekspektasi.")
    else:
        names = ", ".join(b["name"] for b in buckets)
        ok(f"Ketemu {len(buckets)} bucket: {names}")

    out_file = f"{out_dir}/buckets.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(buckets, f, indent=2)
    ok(f"Bucket config tersimpan di {out_file}")

    header("DUMP STORAGE SELESAI!")
    print("Lanjut: python3 4_restore_storage.py")


if __name__ == "__main__":
    main()