# Supabase Migration (Linux / Python)

Migrasi full project Supabase (database, storage, edge functions) ke project
Supabase baru. Ini adalah port Linux/Python dari versi PowerShell, dengan
database dipecah jadi 2 script terpisah (dump & restore) supaya kalau salah
satu tahap restore gagal, tinggal jalankan ulang restore-nya aja tanpa perlu
dump ulang dari SOURCE.

---

## Prerequisites

### 1. PostgreSQL client tools (`pg_dump` & `psql`)

```bash
sudo apt update
sudo apt install postgresql-client
```

Verifikasi:
```bash
pg_dump --version
psql --version
```

### 2. Python package `requests` (dipakai untuk panggil Storage API)

```bash
pip install requests --break-system-packages
```

### 3. `rclone` (untuk migrasi Storage - file fisik)

Download dari [rclone.org/downloads](https://rclone.org/downloads), extract, lalu:

```bash
sudo cp rclone /usr/local/bin/
sudo chmod +x /usr/local/bin/rclone
```

Verifikasi:
```bash
rclone --version
```

### 4. Supabase CLI (untuk migrasi Edge Functions)

```bash
npm install -g supabase
supabase login
```

Kalau `npm install -g` tidak didukung di versi CLI terbaru, install per-project:
```bash
npm install -D supabase
npx supabase login
```
(kalau pakai `npx`, ganti semua panggilan `supabase` di script 5 jadi `npx supabase`)

Kalau project SOURCE dan TARGET ada di **akun Supabase yang beda**, `supabase login`
saja tidak cukup (token per-akun). Isi `SOURCE_ACCESS_TOKEN` dan `TARGET_ACCESS_TOKEN`
di `.env` (bikin di https://supabase.com/dashboard/account/tokens, login pakai akun
pemilik masing-masing project).

---

# Cara Penggunaan

## Step 0 — Siapkan Konfigurasi

Copy `.env.example` jadi `.env`, lalu isi semua value:

```bash
cp .env.example .env
nano .env
```

| Variabel | Ambil dari |
|---|---|
| `SOURCE_HOST` / `TARGET_HOST` | Project Settings → Database → **Connect** → tab **Session pooler** (contoh: `aws-0-ap-southeast-1.pooler.supabase.com`) |
| `SOURCE_USER` / `TARGET_USER` | Sama seperti di tab Session pooler, formatnya `postgres.<project_ref>` (**bukan** cuma `postgres`) |
| `SOURCE_PORT` / `TARGET_PORT` | Biasanya tetap `5432` (session pooler) |
| `SOURCE_PROJECT_REF` / `TARGET_PROJECT_REF` | Subdomain di URL project (`xxxxxxxx.supabase.co`) |
| `SOURCE_SERVICE_ROLE_KEY` / `TARGET_SERVICE_ROLE_KEY` | Project Settings → API |
| `SOURCE_S3_ACCESS_KEY` / `SECRET` / `ENDPOINT` | Project Settings → Storage → S3 Connection → New access key |

> **Kenapa pakai Session Pooler, bukan direct connection (`db.xxxxx.supabase.co`)?**
> Direct connection sekarang **IPv6-only**. Kalau jaringan/ISP kamu belum support IPv6
> dengan baik (umum terjadi di ISP rumahan Indonesia, WiFi kantor, dll), koneksi akan
> gagal dengan error seperti `could not translate host name`. Session Pooler (Supavisor)
> punya endpoint IPv4 sehingga jalan di jaringan mana pun.

---

## Step 1 — Migrasi Database (dump lalu restore, 2 script terpisah)

### 1a. Dump dari SOURCE

```bash
python3 1_dump_database.py
```

Script ini **hanya baca dari SOURCE**, aman dijalankan berkali-kali. Otomatis:
1. Test koneksi ke SOURCE
2. Dump struktur tabel + RLS policies (`public_schema.sql`)
3. Dump data `auth` (users, identities) → `auth_data.sql`
4. Dump metadata `storage` (bucket & object index, bukan file fisik) → `storage_data.sql`
5. Dump data `public` (isi semua tabel) → `public_data.sql`

Semua file tersimpan di `migration_output/` (path dari `OUTPUT_DIR` di `.env`).

Kalau cuma mau dump ulang satu bagian (misal dump public data doang):
```bash
python3 1_dump_database.py --step data
```
Pilihan: `schema`, `auth`, `storage`, `data`, `all` (default `all`).

### 1b. Restore ke TARGET

```bash
python3 2_restore_database.py
```

Script ini **membaca file dari `migration_output/`** (hasil step 1a) dan restore
ke TARGET. Tidak menyentuh SOURCE sama sekali. Otomatis:
1. Test koneksi ke TARGET
2. Reset schema `public` di TARGET (drop + create ulang, biar bersih)
3. Restore struktur tabel + RLS policies
4. Restore data `auth`
5. Restore metadata `storage`
6. Restore data `public`
7. Reset sequence/auto-increment

**Kalau salah satu tahap gagal** (misal restore public data gagal karena ada
constraint aneh), kamu **tidak perlu dump ulang**. Benerin dulu masalahnya,
lalu jalankan ulang cuma tahap yang gagal:

```bash
python3 2_restore_database.py --step data
```
Pilihan: `schema`, `auth`, `storage`, `data`, `sequences`, `all` (default `all`).

> Urutan `all` penting: `schema → auth → storage → data → sequences`, karena
> foreign key di `public.*` menunjuk ke `auth.users`, jadi `auth` harus
> ter-restore duluan sebelum `data` (public).

---

## Step 2 — Migrasi Storage (File Fisik, dump lalu restore, 2 script terpisah)

### 2a. Dump list bucket dari SOURCE

```bash
python3 3_dump_storage.py
```

Ambil daftar bucket & konfigurasinya (public/private, size limit, mime type)
dari SOURCE lewat Storage API, simpan ke `migration_output/buckets.json`.

### 2b. Restore bucket + sync file ke TARGET

```bash
python3 4_restore_storage.py
```

Baca `buckets.json`, lalu:
1. Recreate bucket di TARGET (skip kalau sudah ada, tidak dihapus/ditimpa)
2. Sync semua file pakai `rclone` (protokol S3), **langsung dari SOURCE ke TARGET**

> **Catatan penting**: beda dengan database, file fisik storage **tidak
> didump ke lokal** — `rclone sync` jalan real-time dari S3 SOURCE ke S3
> TARGET, jadi script restore ini tetap butuh credential S3 SOURCE *dan*
> TARGET (keduanya sudah ada di `.env`).

Kalau proses sync sempat terputus (misal koneksi putus di tengah bucket besar),
jalankan ulang saja — `rclone sync` otomatis skip file yang sudah sama:
```bash
python3 4_restore_storage.py --only nama_bucket_yang_gagal
```

Kalau cuma mau recreate bucket tanpa sync file dulu:
```bash
python3 4_restore_storage.py --skip-sync
```

> Proses sync bisa lama tergantung total ukuran file di storage.

---

## Step 3 — Migrasi Edge Functions

Pastikan folder `supabase/functions/` sudah berisi source code function kamu.
Kalau belum ada lokal, tarik dulu dari project lama:

```bash
supabase functions download <nama_fn> --project-ref <SOURCE_PROJECT_REF>
```

Jalankan:
```bash
python3 5_migrate_edge_functions.py
```

Script ini otomatis:
1. Link CLI ke project TARGET
2. Deploy semua function yang ada di `supabase/functions/`
3. Tampilkan daftar nama secrets di SOURCE (value-nya **harus diinput manual**,
   Supabase tidak pernah expose value secret lewat API)

Set ulang secrets:
```bash
supabase secrets set NAMA_SECRET=nilai --project-ref <TARGET_PROJECT_REF>
```

> Script ini **tidak dipecah** dump/restore seperti database & storage,
> karena sifatnya beda — tidak ada "dump" file lokal untuk source code
> function; CLI langsung deploy dari folder lokal yang sudah ada di
> komputer kamu ke project TARGET.

---

## Yang TIDAK Ter-cover Otomatis

Cek & set manual di dashboard project baru:
- Value dari Edge Function secrets
- Auth Provider config (Google/GitHub OAuth client ID & secret)
- Custom SMTP config
- Custom domain

---

## Struktur Project

```text
project/
├── common.py                     # helper bersama (jangan dijalankan langsung)
├── 1_dump_database.py            # dump SOURCE -> file lokal
├── 2_restore_database.py         # file lokal -> restore ke TARGET
├── 3_dump_storage.py             # list bucket SOURCE -> buckets.json
├── 4_restore_storage.py          # buckets.json -> recreate bucket + rclone sync
├── 5_migrate_edge_functions.py   # deploy edge functions ke TARGET
├── .env
├── .env.example
├── supabase/
│   └── functions/
├── migration_output/
│   ├── public_schema.sql
│   ├── auth_data.sql
│   ├── storage_data.sql
│   ├── public_data.sql
│   ├── buckets.json
│   └── log_*.txt
└── README.md
```

---

## Troubleshooting

### `pg_dump: command not found` / `psql: command not found`

```bash
sudo apt update && sudo apt install postgresql-client
```

### `rclone: command not found`

Pastikan binary hasil extract `rclone` sudah di `/usr/local/bin/` atau
folder lain yang ada di `$PATH`.

### `ModuleNotFoundError: No module named 'requests'`

```bash
pip install requests --break-system-packages
```

### Gagal Konek ke SOURCE/TARGET (`could not translate host name`)

Ini biasanya bukan salah ketik, tapi karena `.env` masih pakai direct
connection (`db.xxxxx.supabase.co`) yang sekarang IPv6-only. Cek dulu:

```bash
getent hosts db.xxxxx.supabase.co
```

Kalau host tidak resolve atau koneksi tetap gagal, ganti `SOURCE_HOST`/`TARGET_HOST`
di `.env` ke **Session pooler** endpoint (lihat Step 0 di atas), dan pastikan
`SOURCE_USER`/`TARGET_USER` juga diubah ke format `postgres.<project_ref>`.

### Restore Gagal Karena Foreign Key ke `auth.users`

Pastikan urutan tidak diacak — jalankan `2_restore_database.py` tanpa
`--step` (default `all`) supaya `auth` di-restore sebelum `data` (public).
Kalau masih gagal, cek `log_public_data_restore.txt` di `migration_output/`.

### Bucket Sudah Ada di Target Tapi File Kosong

Bucket yang sudah ada akan di-skip pembuatannya (tidak dihapus/ditimpa),
tapi `rclone sync` tetap jalan mengisi file-nya. Jalankan ulang
`4_restore_storage.py` kalau proses sync sempat terputus.

### Verifikasi Hasil Migrasi

Masuk ke database target (pakai Session pooler juga):
```bash
psql -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -d <TARGET_DB>
```

Lalu:
```sql
SELECT COUNT(*) FROM auth.users;
SELECT COUNT(*) FROM storage.objects;
\dt public.*
```

Bandingkan angkanya dengan project lama — harus sama.
