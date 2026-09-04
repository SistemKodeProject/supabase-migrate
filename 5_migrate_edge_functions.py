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

import os
import sys
from pathlib import Path

from common import header, ok, warn, fail, die, load_env, require_binary, run

FUNCTIONS_DIR = "supabase/functions"


def main():
    require_binary("supabase", "install: https://supabase.com/docs/guides/cli")

    load_env()
    target_ref = os.environ.get("TARGET_PROJECT_REF", "")
    source_ref = os.environ.get("SOURCE_PROJECT_REF", "")

    header("SUPABASE MIGRATE EDGE FUNCTIONS")

    if not Path(FUNCTIONS_DIR).is_dir():
        fail(f"Folder {FUNCTIONS_DIR} gak ketemu.")
        warn("Kalau belum ada source-nya lokal, tarik dulu per fungsi dari SOURCE:")
        print(f"      supabase functions download <nama_fn> --project-ref {source_ref}")
        sys.exit(1)

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
