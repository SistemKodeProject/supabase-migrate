#!/usr/bin/env python3
"""
PUSH LOCAL BACKUP -> TARGET (dipakai kalau SOURCE lagi kena egress quota lock,
tapi kita punya backup manual file storage-nya lokal).

Jalanin: python3 push_local_backup.py <path_ke_folder_backup> [--dry-run]

Cuma butuh kredensial TARGET (gak nyentuh SOURCE sama sekali):
- TARGET_PROJECT_REF / TARGET_SERVICE_ROLE_KEY
- TARGET_S3_ACCESS_KEY / SECRET_KEY / ENDPOINT

MAPPING folder lokal -> bucket TARGET (hasil crosscheck manual ke storage.objects,
sesuaikan FOLDER_MAP di bawah kalau strukturnya beda):
"""

import argparse
import os
import subprocess
import sys
import tempfile

from common import header, ok, warn, fail, die, load_env, require_binary, run

# (folder_relatif_di_backup, nama_bucket_target, path_tujuan_di_dalam_bucket)
# path_tujuan "" artinya taruh persis di root bucket (bukan di subfolder)
FOLDER_MAP = [
    ("audio_set_a",        "Audio", "audio_set_a"),
    ("audio_set_b",     "Audio", "audio_set_b"),
    ("audio_set_c",       "Audio", "audio_set_c"),
    ("audio_set_d",          "Audio", "audio_set_d"),
    ("audio_set_e",          "Audio", "audio_set_e"),
    ("audio_set_f",          "Audio", "audio_set_f"),
    ("audio_set_g",          "Audio", "audio_set_g"),
    ("audio_set_h",          "Audio", "audio_set_h"),
    ("audio_set_i",         "Audio", "audio_set_i"),
    ("lesson_audio",      "images", "lesson_audio"),
    ("Lessons",         "images", "Lessons"),
    ("Quiz",            "images", "Quiz"),
    ("quiz_media",      "images", "quiz_media"),
    ("image",           "other", "image"),
    ("voice",           "other", "voice"),
]

# File lepas di ROOT backup (bukan di dalam folder) yang masuk bucket covers
ROOT_FILES_TO_COVERS = [
    "file_1.png",
    "file_2.png",
    "file_3.jpg",
    "file_4.jpg",
    "file_5.jpg",
    "file_6.jpg",
]


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

    rclone_conf = write_rclone_config(dst_akey, dst_skey, dst_endpt)
    ok(f"rclone config dibuat di {rclone_conf}")

    for local_folder, bucket, remote_path in FOLDER_MAP:
        push_folder(args.backup_root, local_folder, bucket, remote_path, rclone_conf, args.dry_run)

    push_root_files(args.backup_root, ROOT_FILES_TO_COVERS, "covers", rclone_conf, args.dry_run)

    print()
    header("SELESAI")
    ok("Semua folder di FOLDER_MAP udah diproses. Cek output di atas buat yang SKIP/FAIL.")
    if args.dry_run:
        warn("Ini masih dry-run — jalanin ulang tanpa --dry-run buat beneran push.")


if __name__ == "__main__":
    main()