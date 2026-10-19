#!/usr/bin/env python3
"""
DOWNLOAD STORAGE -> LOKAL: download semua file fisik Supabase Storage ke folder lokal.
Jalanin: python3 6_download_storage.py [--from SOURCE|TARGET] [--dest folder]
                                       [--only nama_bucket ...] [--dry-run]

Butuh: rclone sudah di PATH (https://rclone.org/downloads)

Beda sama 4_restore_storage.py (yang sync S3 SOURCE -> S3 TARGET langsung),
script ini cuma NARIK file ke disk lokal. Sifatnya READ-ONLY ke Supabase:
cuma list bucket + download object, gak ada upload/hapus/ubah apapun di
project. Pakai `rclone copy` (bukan sync), jadi file lokal yang udah ada
juga gak bakal dihapus.

Kredensial yang dipakai (sesuai --from, default SOURCE):
- <PREFIX>_S3_ACCESS_KEY / <PREFIX>_S3_SECRET_KEY / <PREFIX>_S3_ENDPOINT
- <PREFIX>_PROJECT_REF (opsional, cuma buat nama folder default)

Hasilnya: <dest>/<nama_bucket>/<path object>, struktur persis kayak di bucket.
Default <dest> = ./storage_backup/<project_ref>. Kalau download keputus di
tengah jalan, jalanin lagi aja - rclone otomatis skip file yang udah sama.
"""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from common import header, ok, warn, fail, die, load_env, require_binary, run


def write_rclone_config(akey, skey, endpt):
    conf = f"""[supasrc]
type = s3
provider = Other
access_key_id = {akey}
secret_access_key = {skey}
endpoint = {endpt}
force_path_style = true
region = auto
"""
    fd, path = tempfile.mkstemp(prefix="rclone_download_storage_", suffix=".conf")
    with os.fdopen(fd, "w") as f:
        f.write(conf)
    return path


def list_buckets(rclone_conf):
    """List bucket via S3 ListBuckets (read-only)."""
    result = subprocess.run(
        ["rclone", "lsjson", "supasrc:", "--dirs-only", "--config", rclone_conf],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        die(f"Gagal list bucket: {result.stderr.strip()}")
    try:
        entries = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        die(f"Gagal parse hasil list bucket. Output mentah:\n{result.stdout}")
    return sorted(e["Name"] for e in entries)


def download_bucket(name, dest_root, rclone_conf, dry_run):
    print(f"\n      --- Bucket: {name} ---")
    cmd = [
        "rclone", "copy", f"supasrc:{name}", str(dest_root / name),
        "--config", rclone_conf, "--progress", "--transfers=8", "--checkers=16",
        "--retries=5", "--low-level-retries=10",
    ]
    if dry_run:
        cmd.append("--dry-run")
    return run(cmd)


def local_summary(path):
    files, size = 0, 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            size += p.stat().st_size
    return files, size


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def main():
    parser = argparse.ArgumentParser(description="Download file Supabase Storage ke folder lokal (read-only)")
    parser.add_argument("--from", dest="prefix", default="SOURCE", choices=["SOURCE", "TARGET"],
                        help="Project mana yang di-download, pakai kredensial <PREFIX>_S3_* di .env (default SOURCE)")
    parser.add_argument("--dest", help="Folder tujuan lokal (default ./storage_backup/<project_ref>)")
    parser.add_argument("--only", nargs="+", metavar="BUCKET",
                        help="Cuma download bucket ini aja (bisa lebih dari satu)")
    parser.add_argument("--dry-run", action="store_true", help="Simulasi doang, gak beneran download")
    args = parser.parse_args()

    require_binary("rclone", "download dari https://rclone.org/downloads")

    load_env()
    p = args.prefix
    akey = os.environ.get(f"{p}_S3_ACCESS_KEY", "")
    skey = os.environ.get(f"{p}_S3_SECRET_KEY", "")
    endpt = os.environ.get(f"{p}_S3_ENDPOINT", "")
    ref = os.environ.get(f"{p}_PROJECT_REF", "") or p.lower()

    if not all([akey, skey, endpt]):
        die(f"{p}_S3_ACCESS_KEY/SECRET_KEY/ENDPOINT belum lengkap di .env")

    dest_root = Path(args.dest or f"./storage_backup/{ref}")

    header(f"SUPABASE DOWNLOAD STORAGE ({p} -> lokal: {dest_root})")
    if args.dry_run:
        warn("MODE DRY-RUN - gak ada file yang beneran ke-download, cuma simulasi.")

    rclone_conf = write_rclone_config(akey, skey, endpt)
    try:
        if args.only:
            buckets = args.only
            warn(f"Pakai --only: {', '.join(buckets)}")
        else:
            warn(f"Mengambil list bucket dari {p}...")
            buckets = list_buckets(rclone_conf)
            if not buckets:
                die(f"Gak ketemu bucket sama sekali di {p}.")
            ok(f"Ketemu {len(buckets)} bucket: {', '.join(buckets)}")

        if not args.dry_run:
            dest_root.mkdir(parents=True, exist_ok=True)

        failed = []
        for name in buckets:
            if download_bucket(name, dest_root, rclone_conf, args.dry_run):
                ok(f"'{name}' selesai download")
            else:
                fail(f"Gagal download '{name}', cek error di atas")
                failed.append(name)
    finally:
        os.remove(rclone_conf)

    print()
    header("DOWNLOAD STORAGE SELESAI!")
    if not args.dry_run:
        for name in buckets:
            bucket_dir = dest_root / name
            if bucket_dir.is_dir():
                files, size = local_summary(bucket_dir)
                print(f"      {name}: {files} file, {human_size(size)}")
    if failed:
        fail(f"Bucket yang gagal: {', '.join(failed)}")
        print(f"      Retry: python3 6_download_storage.py --from {p} --only {' '.join(failed)}")
    else:
        ok(f"Semua bucket kesimpen di {dest_root}")
    if args.dry_run:
        warn("Ini masih dry-run - jalanin ulang tanpa --dry-run buat beneran download.")


if __name__ == "__main__":
    main()
