#!/usr/bin/env python3
"""
STEP 3: MIGRATE EDGE FUNCTIONS
Jalanin: python3 5_migrate_edge_functions.py

Butuh: Supabase CLI sudah login (supabase login) & folder
       supabase/functions/ berisi source code function-function lu
       (kalau belum ada lokal, tarik dulu dari source project pakai:
        supabase functions download <nama_fn> --project-ref <SOURCE_PROJECT_REF>)

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


def list_source_functions(source_ref):
    """Ambil daftar nama function di SOURCE lewat CLI (format JSON)."""
    import subprocess
    result = subprocess.run(
        ["supabase", "functions", "list", "--project-ref", source_ref, "--output", "json"],
        capture_output=True, text=True,
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
        if not run(["supabase", "functions", "download", name, "--project-ref", source_ref]):
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

    warn(f"Linking CLI ke project TARGET ({target_ref})...")
    if not run(["supabase", "link", "--project-ref", target_ref]):
        die("Gagal link ke project target!")
    ok("Linked")

    warn("Deploying functions...")
    functions = [d.name for d in Path(FUNCTIONS_DIR).iterdir() if d.is_dir() and d.name != "_shared"]
    for fn in functions:
        print(f"      Deploying: {fn}...")
        if run(["supabase", "functions", "deploy", fn, "--project-ref", target_ref]):
            ok(f"{fn} deployed")
        else:
            fail(f"Gagal deploy {fn}")

    warn("Cek secrets yang perlu di-set manual...")
    warn("Supabase Management API gak pernah expose VALUE dari secrets,")
    warn("jadi ini gak bisa diotomatisasi. Nama secret di SOURCE:")
    run(["supabase", "secrets", "list", "--project-ref", source_ref])
    print(f"\n      Set ulang manual satu-satu ke TARGET pakai:")
    print(f"      supabase secrets set NAMA_SECRET=nilai --project-ref {target_ref}")

    header("EDGE FUNCTIONS MIGRATION SELESAI!")
    print("Terakhir: cek Auth Providers config & custom SMTP di dashboard TARGET manual")
    print("(ini juga gak ke-cover script).")


if __name__ == "__main__":
    main()