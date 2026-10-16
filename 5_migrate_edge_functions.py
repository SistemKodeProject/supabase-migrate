#!/usr/bin/env python3
"""
STEP 3: MIGRATE EDGE FUNCTIONS
Jalanin: python3 5_migrate_edge_functions.py

Butuh: Supabase CLI + access token (https://supabase.com/dashboard/account/tokens)
       di .env: SOURCE_ACCESS_TOKEN (akun pemilik project SOURCE) dan
       TARGET_ACCESS_TOKEN (akun pemilik project TARGET). Kalau source & target
       ada di akun yang sama, cukup isi SUPABASE_ACCESS_TOKEN aja (atau
       'supabase login'), dipakai sebagai fallback buat dua-duanya.
       Kalau folder supabase/functions/ belum ada, function otomatis
       di-download dulu dari SOURCE.

CATATAN: script ini tidak dipisah dump/restore karena sifatnya beda dari
database & storage - tidak ada "dump" file lokal untuk source code function,
CLI langsung deploy dari folder supabase/functions/ yang sudah ada di
komputer lo ke project TARGET.
"""

import json
import os
import sys
from pathlib import Path

from common import header, ok, warn, fail, die, load_env, require_binary, run

FUNCTIONS_DIR = "supabase/functions"


def cli_env(prefix):
    """
    Env buat Supabase CLI pakai access token milik SOURCE/TARGET. Token itu
    per-AKUN, bukan per-project, jadi kalau source & target beda akun,
    satu token gak bisa dipakai buat dua-duanya (error project_admin_read).
    Fallback ke SUPABASE_ACCESS_TOKEN / hasil 'supabase login' kalau kosong.
    """
    token = os.environ.get(f"{prefix}_ACCESS_TOKEN") or os.environ.get("SUPABASE_ACCESS_TOKEN")
    return {"SUPABASE_ACCESS_TOKEN": token} if token else None


def list_source_functions(source_ref):
    """Ambil daftar nama function di SOURCE lewat CLI (format JSON)."""
    import subprocess
    result = subprocess.run(
        ["supabase", "functions", "list", "--project-ref", source_ref, "--output", "json"],
        capture_output=True, text=True,
        env={**os.environ, **(cli_env("SOURCE") or {})},
    )
    if result.returncode != 0:
        die(f"Gagal list functions dari SOURCE: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        die(f"Gagal parse output 'supabase functions list' jadi JSON:\n{result.stdout}")
    # CLI biasanya pakai key "slug", fallback ke "name" kalau beda versi
    return [fn.get("slug") or fn.get("name") for fn in data]


def download_all_functions(source_ref):
    """Download semua function dari SOURCE ke folder lokal sekali jalan (loop di balik layar)."""
    warn(f"Folder {FUNCTIONS_DIR} belum ada - ambil daftar function dari SOURCE dulu...")
    names = list_source_functions(source_ref)
    if not names:
        die(f"Gak ketemu function apapun di project SOURCE ({source_ref}).")
    ok(f"Ketemu {len(names)} function: {', '.join(names)}")

    Path(FUNCTIONS_DIR).mkdir(parents=True, exist_ok=True)
    for name in names:
        print(f"      Downloading: {name}...")
        if not run(["supabase", "functions", "download", name, "--project-ref", source_ref],
                   env_extra=cli_env("SOURCE")):
            die(f"Gagal download function '{name}' dari SOURCE!")
        ok(f"{name} ter-download")


def main():
    require_binary("supabase", "install: https://supabase.com/docs/guides/cli")

    load_env()
    target_ref = os.environ.get("TARGET_PROJECT_REF", "")
    source_ref = os.environ.get("SOURCE_PROJECT_REF", "")

    header("SUPABASE MIGRATE EDGE FUNCTIONS")

    if not Path(FUNCTIONS_DIR).is_dir():
        download_all_functions(source_ref)

    # NB: sengaja GAK pakai 'supabase link'. Deploy di bawah sudah pakai
    # --project-ref, jadi link gak dibutuhkan. Link juga butuh permission
    # 'project_admin_read' (owner/admin), yang sering gak dimiliki token
    # dengan role Developer -> gagal padahal deploy sendiri bisa jalan.
    warn(f"Deploying functions ke project TARGET ({target_ref})...")
    functions = [d.name for d in Path(FUNCTIONS_DIR).iterdir() if d.is_dir() and d.name != "_shared"]
    for fn in functions:
        print(f"      Deploying: {fn}...")
        if run(["supabase", "functions", "deploy", fn, "--project-ref", target_ref],
               env_extra=cli_env("TARGET")):
            ok(f"{fn} deployed")
        else:
            fail(f"Gagal deploy {fn}")

    warn("Cek secrets yang perlu di-set manual...")
    warn("Supabase Management API gak pernah expose VALUE dari secrets,")
    warn("jadi ini gak bisa diotomatisasi. Nama secret di SOURCE:")
    run(["supabase", "secrets", "list", "--project-ref", source_ref], env_extra=cli_env("SOURCE"))
    print(f"\n      Set ulang manual satu-satu ke TARGET pakai:")
    print(f"      supabase secrets set NAMA_SECRET=nilai --project-ref {target_ref}")

    header("EDGE FUNCTIONS MIGRATION SELESAI!")
    print("Terakhir: cek Auth Providers config & custom SMTP di dashboard TARGET manual")
    print("(ini juga gak ke-cover script).")


if __name__ == "__main__":
    main()