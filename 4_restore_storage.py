#!/usr/bin/env python3
"""
STEP 2b: RESTORE STORAGE - recreate bucket di TARGET & sync file fisik pakai rclone.
Jalanin: python3 4_restore_storage.py [--only nama_bucket] [--skip-sync]

Butuh: rclone sudah di PATH (https://rclone.org/downloads), requests
Butuh file migration_output/buckets.json dari 3_dump_storage.py.

CATATAN PENTING (beda dengan database):
File fisik TIDAK didump ke lokal - rclone sync langsung dari S3 SOURCE ke
S3 TARGET secara real-time. Jadi script ini tetap butuh credential S3
SOURCE *dan* TARGET, bukan cuma baca file lokal. Kalau proses sync
terputus di tengah jalan, tinggal jalanin lagi script ini (rclone sync
otomatis skip file yang sudah sama).

Cara ambil credential:
- TARGET_PROJECT_REF      : subdomain di URL project baru
- TARGET_SERVICE_ROLE_KEY : Project Settings > API > service_role key
- SOURCE/TARGET_S3_ACCESS_KEY/SECRET/ENDPOINT: Project Settings > Storage > S3 Connection > New access key
"""

import argparse
import json
import os
import sys
import tempfile

from common import header, ok, warn, fail, die, load_env, output_dir, require_binary, run

try:
    import requests
except ImportError:
    print("[!] Module 'requests' belum terinstall.")
    print("    Jalankan: pip install requests --break-system-packages")
    sys.exit(1)


def load_buckets(out_dir):
    path = f"{out_dir}/buckets.json"
    if not os.path.exists(path):
        die(f"File {path} tidak ditemukan. Jalankan dulu: python3 3_dump_storage.py")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_rclone_config(src_akey, src_skey, src_endpt, dst_akey, dst_skey, dst_endpt):
    conf = f"""[supasrc]
type = s3
provider = Other
access_key_id = {src_akey}
secret_access_key = {src_skey}
endpoint = {src_endpt}
force_path_style = true
region = auto

[supadst]
type = s3
provider = Other
access_key_id = {dst_akey}
secret_access_key = {dst_skey}
endpoint = {dst_endpt}
force_path_style = true
region = auto
"""
    fd, path = tempfile.mkstemp(prefix="rclone_supabase_migrate_", suffix=".conf")
    with os.fdopen(fd, "w") as f:
        f.write(conf)
    return path


def recreate_buckets(buckets, dst_ref, dst_srk):
    warn("Membuat ulang bucket di TARGET...")
    headers = {"Authorization": f"Bearer {dst_srk}", "apikey": dst_srk, "Content-Type": "application/json"}

    for b in buckets:
        check = requests.get(
            f"https://{dst_ref}.supabase.co/storage/v1/bucket/{b['name']}", headers=headers
        )
        if check.status_code == 200:
            warn(f"SKIP - bucket '{b['name']}' udah ada di target")
            continue

        body = {
            "id": b["name"],
            "name": b["name"],
            "public": b.get("public", False),
            "file_size_limit": b.get("file_size_limit"),
            "allowed_mime_types": b.get("allowed_mime_types"),
        }
        resp = requests.post(
            f"https://{dst_ref}.supabase.co/storage/v1/bucket", headers=headers, json=body
        )
        if resp.status_code in (200, 201):
            ok(f"Bucket '{b['name']}' dibuat (public={body['public']})")
        else:
            fail(f"Gagal bikin bucket '{b['name']}': HTTP {resp.status_code} - {resp.text}")


def sync_buckets(buckets, rclone_conf, only_bucket=None):
    warn("Sync file fisik per bucket (bisa lama tergantung ukuran)...")
    for b in buckets:
        name = b["name"]
        if only_bucket and name != only_bucket:
            continue
        print(f"\n      --- Bucket: {name} ---")
        success = run(
            [
                "rclone", "sync", f"supasrc:{name}", f"supadst:{name}",
                "--config", rclone_conf, "--progress", "--transfers=8", "--checkers=16",
            ]
        )
        if success:
            ok(f"'{name}' selesai sync")
        else:
            fail(f"Gagal sync '{name}', cek error di atas")


def main():
    parser = argparse.ArgumentParser(description="Restore storage Supabase (bucket + file fisik)")
    parser.add_argument("--only", help="Cuma proses satu bucket ini aja (misal kalau sync sebelumnya gagal di tengah)")
    parser.add_argument("--skip-sync", action="store_true", help="Cuma recreate bucket, skip rclone sync")
    args = parser.parse_args()

    require_binary("rclone", "download dari https://rclone.org/downloads")

    load_env()
    out_dir = output_dir()
    buckets = load_buckets(out_dir)

    dst_ref = os.environ.get("TARGET_PROJECT_REF", "")
    dst_srk = os.environ.get("TARGET_SERVICE_ROLE_KEY", "")
    src_akey = os.environ.get("SOURCE_S3_ACCESS_KEY", "")
    src_skey = os.environ.get("SOURCE_S3_SECRET_KEY", "")
    src_endpt = os.environ.get("SOURCE_S3_ENDPOINT", "")
    dst_akey = os.environ.get("TARGET_S3_ACCESS_KEY", "")
    dst_skey = os.environ.get("TARGET_S3_SECRET_KEY", "")
    dst_endpt = os.environ.get("TARGET_S3_ENDPOINT", "")

    if not dst_ref or not dst_srk:
        die("TARGET_PROJECT_REF / TARGET_SERVICE_ROLE_KEY belum diisi di .env")

    header("SUPABASE RESTORE STORAGE (bucket + file fisik -> TARGET)")

    recreate_buckets(buckets, dst_ref, dst_srk)

    if args.skip_sync:
        warn("--skip-sync dipakai, lewati rclone sync.")
    else:
        if not all([src_akey, src_skey, src_endpt, dst_akey, dst_skey, dst_endpt]):
            die("S3 credentials (SOURCE/TARGET) belum lengkap di .env, tidak bisa rclone sync.")
        rclone_conf = write_rclone_config(src_akey, src_skey, src_endpt, dst_akey, dst_skey, dst_endpt)
        ok(f"rclone config dibuat di {rclone_conf}")
        sync_buckets(buckets, rclone_conf, only_bucket=args.only)

    header("RESTORE STORAGE SELESAI!")
    print("Cek storage.objects count di kedua project harus match")
    print("Lanjut: python3 5_migrate_edge_functions.py")


if __name__ == "__main__":
    main()
