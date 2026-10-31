#!/usr/bin/env python3
"""
PUSH LOCAL BACKUP -> TARGET (dipakai kalau SOURCE lagi kena egress quota lock,
tapi kita punya backup manual file storage-nya lokal).

Jalanin: python3 push_local_backup.py <path_ke_folder_backup> [--dry-run]

Cuma butuh kredensial TARGET (gak nyentuh SOURCE sama sekali):
- TARGET_PROJECT_REF / TARGET_SERVICE_ROLE_KEY
- TARGET_S3_ACCESS_KEY / SECRET_KEY / ENDPOINT

The local folder -> bucket mapping is read from folder_map.json (see
folder_map.example.json). Nothing about your project layout is hardcoded.
"""

import argparse
import json
import os
import tempfile

from common import header, ok, warn, fail, die, load_env, require_binary, run

FOLDER_MAP_FILE = "folder_map.json"


def load_folder_map(path=FOLDER_MAP_FILE):
    """
    Load the local-folder -> bucket mapping from a JSON file.

    Every project lays out its storage differently, so the mapping is NOT
    hardcoded. Copy folder_map.example.json to folder_map.json and edit it.

    Format:
    {
      "folders": [
        {"local": "audio",  "bucket": "Audio",  "path": "audio"},
        {"local": "covers", "bucket": "images", "path": ""}
      ],
      "root_files": {"bucket": "misc", "files": ["logo.png"]}
    }

    "path" is the destination prefix inside the bucket ("" = bucket root).
    "root_files" is optional: loose files in the backup root that belong in
    one bucket.
    """
    if not os.path.isfile(path):
        die(f"{path} not found. Copy folder_map.example.json to {path} and edit it for your project.")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    folders = []
    for item in data.get("folders", []):
        try:
            folders.append((item["local"], item["bucket"], item.get("path", "")))
        except (KeyError, TypeError):
            die(f"Invalid entry in {path}: {item!r} (need 'local' and 'bucket')")

    root = data.get("root_files") or {}
    root_bucket = root.get("bucket")
    root_files = root.get("files", [])
    if root_files and not root_bucket:
        die(f"'root_files' in {path} lists files but no 'bucket'")
    return folders, root_bucket, root_files


def write_rclone_config(akey, skey, endpt):
    conf = f"""[supadst]
type = s3
provider = Other
access_key_id = {akey}
secret_access_key = {skey}
endpoint = {endpt}
force_path_style = true
region = auto
"""
    fd, path = tempfile.mkstemp(prefix="rclone_push_backup_", suffix=".conf")
    with os.fdopen(fd, "w") as f:
        f.write(conf)
    return path


def push_folder(backup_root, local_folder, bucket, remote_path, rclone_conf, dry_run):
    src = os.path.join(backup_root, local_folder)
    if not os.path.isdir(src):
        warn(f"SKIP - folder gak ketemu di lokal: {src}")
        return
    dst = f"supadst:{bucket}/{remote_path}" if remote_path else f"supadst:{bucket}"
    print(f"\n      --- {local_folder}  ->  bucket '{bucket}' / '{remote_path}' ---")
    cmd = ["rclone", "copy", src, dst, "--config", rclone_conf, "--progress", "--transfers=8", "--checkers=16"]
    if dry_run:
        cmd.append("--dry-run")
    success = run(cmd)
    if success:
        ok(f"'{local_folder}' selesai push ke {bucket}")
    else:
        fail(f"Gagal push '{local_folder}', cek error di atas")


def push_root_files(backup_root, filenames, bucket, rclone_conf, dry_run):
    print(f"\n      --- File lepas di root backup -> bucket '{bucket}' ---")
    for fname in filenames:
        src = os.path.join(backup_root, fname)
        if not os.path.isfile(src):
            warn(f"SKIP - file gak ketemu di lokal: {src}")
            continue
        dst = f"supadst:{bucket}/{fname}"
        cmd = ["rclone", "copyto", src, dst, "--config", rclone_conf, "--progress"]
        if dry_run:
            cmd.append("--dry-run")
        success = run(cmd)
        if success:
            ok(f"'{fname}' selesai push ke {bucket}")
        else:
            fail(f"Gagal push '{fname}'")


def main():
    parser = argparse.ArgumentParser(description="Push backup lokal storage -> TARGET (bypass SOURCE)")
    parser.add_argument("backup_root", help="Path folder root hasil backup lokal")
    parser.add_argument("--dry-run", action="store_true", help="Simulasi doang, gak beneran upload")
    parser.add_argument("--map", default=FOLDER_MAP_FILE, help=f"Path to the folder mapping JSON (default {FOLDER_MAP_FILE})")
    args = parser.parse_args()

    require_binary("rclone", "download dari https://rclone.org/downloads")

    load_env()
    dst_akey = os.environ.get("TARGET_S3_ACCESS_KEY", "")
    dst_skey = os.environ.get("TARGET_S3_SECRET_KEY", "")
    dst_endpt = os.environ.get("TARGET_S3_ENDPOINT", "")

    if not all([dst_akey, dst_skey, dst_endpt]):
        die("TARGET_S3_ACCESS_KEY/SECRET_KEY/ENDPOINT belum lengkap di .env")

    if not os.path.isdir(args.backup_root):
        die(f"Folder backup gak ketemu: {args.backup_root}")

    header("PUSH LOCAL BACKUP -> TARGET (bypass SOURCE, gak kena quota apapun)")
    if args.dry_run:
        warn("MODE DRY-RUN - gak ada file yang beneran ke-upload, cuma simulasi.")

    folder_map, root_bucket, root_files = load_folder_map(args.map)
    ok(f"Loaded {len(folder_map)} folder mapping(s) from {args.map}")

    rclone_conf = write_rclone_config(dst_akey, dst_skey, dst_endpt)
    ok(f"rclone config dibuat di {rclone_conf}")

    for local_folder, bucket, remote_path in folder_map:
        push_folder(args.backup_root, local_folder, bucket, remote_path, rclone_conf, args.dry_run)

    if root_files:
        push_root_files(args.backup_root, root_files, root_bucket, rclone_conf, args.dry_run)

    print()
    header("SELESAI")
    ok("Semua folder di folder_map.json udah diproses. Cek output di atas buat yang SKIP/FAIL.")
    if args.dry_run:
        warn("Ini masih dry-run — jalanin ulang tanpa --dry-run buat beneran push.")


if __name__ == "__main__":
    main()
