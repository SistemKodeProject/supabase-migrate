#!/usr/bin/env python3
"""
STEP 2a: DUMP STORAGE - ambil daftar bucket & konfigurasinya dari project SOURCE.
Jalanin: python3 3_dump_storage.py

Butuh: requests (pip install requests --break-system-packages)

Script ini HANYA baca dari SOURCE lewat Storage API, hasilnya disimpan sebagai
migration_output/buckets.json. Dipakai oleh 4_restore_storage.py.

Cara ambil credential:
- SOURCE_PROJECT_REF     : subdomain di URL project, contoh xxxxxxxx.supabase.co -> "xxxxxxxx"
- SOURCE_SERVICE_ROLE_KEY: Project Settings > API > service_role key
"""

import json
import sys

from common import header, ok, warn, die, load_env, output_dir

try:
    import requests
except ImportError:
    print("[!] Module 'requests' belum terinstall.")
    print("    Jalankan: pip install requests --break-system-packages")
    sys.exit(1)


def main():
    load_env()
    out_dir = output_dir()

    import os
    src_ref = os.environ.get("SOURCE_PROJECT_REF", "")
    src_srk = os.environ.get("SOURCE_SERVICE_ROLE_KEY", "")

    if not src_ref or not src_srk:
        die("SOURCE_PROJECT_REF / SOURCE_SERVICE_ROLE_KEY belum diisi di .env")

    header("SUPABASE DUMP STORAGE (list bucket dari SOURCE)")

    warn("Mengambil list bucket dari SOURCE...")
    headers = {"Authorization": f"Bearer {src_srk}", "apikey": src_srk}
    resp = requests.get(f"https://{src_ref}.supabase.co/storage/v1/bucket", headers=headers)

    if resp.status_code != 200:
        die(f"Gagal ambil list bucket dari SOURCE: HTTP {resp.status_code} - {resp.text}")

    buckets = resp.json()
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
