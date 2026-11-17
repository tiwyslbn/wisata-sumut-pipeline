import argparse
import json
import math
import os
import zipfile
from datetime import datetime, timezone
from decimal import Decimal

from bson import json_util

FOLDER_BACKUP = "backup"
FILE_SKEMA = os.path.join("sql", "skema_postgres.sql")
SKEMA_PG = "wisata_sumut"
TABEL_PG = [  # urutan penting: kategori dulu karena direferensikan tabel lain
    ("kategori", "id"),
    ("tempat_wisata", "id"),
]


# ======================================================
# PEMBUAT SQL (tanpa koneksi, sehingga bisa diuji sendiri)
# ======================================================
def sql_literal(v):
    """Mengubah satu nilai Python menjadi tulisan SQL yang aman."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return "NULL" if (math.isnan(v) or math.isinf(v)) else repr(v)
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return "'" + v.isoformat() + "'"
    if isinstance(v, (list, tuple)):
        if not v:
            return "ARRAY[]::text[]"
        return "ARRAY[" + ", ".join(sql_literal(x) for x in v) + "]::text[]"
    return "'" + str(v).replace("'", "''") + "'"


def buat_dump_sql(skema_sql, tabel, schema, waktu):
    """
    skema_sql : isi berkas skema (CREATE SCHEMA/TABLE ...) dengan nama skema aslinya
    tabel     : daftar (nama_tabel, kolom_kunci, daftar_kolom, daftar_baris)
    schema    : nama skema tujuan
    """
    baris = [
        f"-- Dump data PostgreSQL proyek wisata Sumatera Utara",
        f"-- Dibuat: {waktu.isoformat()}",
        "-- Pulihkan ke database KOSONG (atau skema yang belum ada).",
        "SET client_encoding = 'UTF8';",
        "SET standard_conforming_strings = on;",
        "",
        skema_sql.replace(SKEMA_PG, schema).strip(),
        "",
    ]
    for nama, kunci, kolom, data in tabel:
        baris.append(f"-- Data tabel {schema}.{nama} ({len(data)} baris)")
        daftar = ", ".join(kolom)
        for r in data:
            nilai = ", ".join(sql_literal(x) for x in r)
            baris.append(f"INSERT INTO {schema}.{nama} ({daftar}) VALUES ({nilai});")
        baris.append(
            f"SELECT setval(pg_get_serial_sequence('{schema}.{nama}', '{kunci}'), "
            f"COALESCE((SELECT MAX({kunci}) FROM {schema}.{nama}), 1));"
        )
        baris.append("")
    return "\n".join(baris)


def petunjuk_pulihkan():
    return """CARA MEMULIHKAN DATABASE DARI BACKUP INI
========================================

A. MongoDB (folder mongodb/)
   Setiap koleksi disimpan sebagai satu berkas JSON (format extended JSON).
   Cara 1 (paling mudah): MongoDB Compass -> pilih database dan koleksi ->
           Add Data -> Import JSON or CSV file -> pilih berkas .json -> Import.
   Cara 2 (baris perintah, butuh MongoDB Database Tools):
           mongoimport --uri "<ALAMAT-KONEKSI>" --db wisata_sumut ^
                       --collection hasil_akhir --jsonArray --file mongodb/hasil_akhir.json
   Daftar koleksi dan jumlah dokumennya ada di mongodb/_ringkasan.json.

B. PostgreSQL (folder postgresql/)
   Berkas wisata_sumut_dump.sql berisi pembuatan skema, tabel, dan seluruh data.
   Pulihkan ke database KOSONG atau skema yang belum ada.
   Cara 1: dashboard Supabase -> SQL Editor -> tempel isi berkas -> Run.
   Cara 2: psql "<ALAMAT-KONEKSI>" -f postgresql/wisata_sumut_dump.sql
   Jika skema wisata_sumut sudah ada dan berisi data, hapus dulu:
           DROP SCHEMA wisata_sumut CASCADE;

Catatan: berkas ini tidak memuat kata sandi atau alamat koneksi.
"""


def bangun_zip(path_zip, mongo, pg_tabel, skema_sql, waktu):
    """mongo = {nama_koleksi: [dokumen,...]}, pg_tabel = lihat buat_dump_sql."""
    ringkasan_mongo = {k: len(v) for k, v in mongo.items()}
    ringkasan_pg = {nama: len(data) for nama, _, _, data in pg_tabel}
    info = {
        "dibuat": waktu.isoformat(),
        "mongodb": {"database": "wisata_sumut", "jumlah_dokumen": ringkasan_mongo},
        "postgresql": {"skema": SKEMA_PG, "jumlah_baris": ringkasan_pg},
    }
    with zipfile.ZipFile(path_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for nama, dokumen in mongo.items():
            isi = json_util.dumps(dokumen, indent=2, ensure_ascii=False)
            z.writestr(f"mongodb/{nama}.json", isi.encode("utf-8"))
        z.writestr("mongodb/_ringkasan.json",
                   json.dumps(ringkasan_mongo, indent=2, ensure_ascii=False).encode("utf-8"))
        dump = buat_dump_sql(skema_sql, pg_tabel, SKEMA_PG, waktu)
        z.writestr("postgresql/wisata_sumut_dump.sql", dump.encode("utf-8"))
        z.writestr("INFO_BACKUP.json", json.dumps(info, indent=2, ensure_ascii=False).encode("utf-8"))
        z.writestr("CARA_PULIHKAN.txt", petunjuk_pulihkan().encode("utf-8"))
    return info


# ======================================================
# BAGIAN YANG BERHUBUNGAN DENGAN DATABASE
# ======================================================
def ambil_mongo():
    from koneksi import get_db
    db = get_db()
    hasil = {}
    for nama in sorted(db.list_collection_names()):
        hasil[nama] = list(db[nama].find({}).sort("_id", 1))
    return hasil


def ambil_pg(conn):
    tabel = []
    with conn.cursor() as cur:
        for nama, kunci in TABEL_PG:
            cur.execute(f"SELECT * FROM {SKEMA_PG}.{nama} ORDER BY {kunci}")
            kolom = [d[0] for d in cur.description]
            tabel.append((nama, kunci, kolom, cur.fetchall()))
    return tabel


def uji_pulihkan(conn, skema_sql, pg_tabel, waktu):
    """Memulihkan dump ke skema SEMENTARA, membandingkan isinya, lalu menghapusnya."""
    uji = "wisata_sumut_uji"
    dump = buat_dump_sql(skema_sql, pg_tabel, uji, waktu)
    cek = ("SELECT count(*), md5(string_agg(nama_wisata || '|' || COALESCE(deskripsi, '') || '|' || "
           "lat::text || '|' || lon::text, ';' ORDER BY id)) FROM {s}.tempat_wisata")
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {uji} CASCADE")
            cur.execute(dump)
            cur.execute(cek.format(s=uji))
            hasil_uji = cur.fetchone()
            cur.execute(cek.format(s=SKEMA_PG))
            hasil_asli = cur.fetchone()
            cur.execute(f"DROP SCHEMA {uji} CASCADE")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return hasil_asli, hasil_uji


def main():
    parser = argparse.ArgumentParser(description="Backup MongoDB dan PostgreSQL ke satu berkas ZIP")
    parser.add_argument("--uji-pulihkan", action="store_true",
                        help="uji bahwa dump SQL dapat dipulihkan (memakai skema sementara)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    import psycopg2
    from koneksi import baca_uri
    load_dotenv()

    waktu = datetime.now(timezone.utc)
    os.makedirs(FOLDER_BACKUP, exist_ok=True)

    print("Membaca data MongoDB...")
    mongo = ambil_mongo()
    for k, v in mongo.items():
        print(f"  {k:20} {len(v):5} dokumen")

    print("Membaca data PostgreSQL...")
    uri = baca_uri("POSTGRES_URI")
    if not uri:
        raise SystemExit("GAGAL: POSTGRES_URI tidak ditemukan.")
    conn = psycopg2.connect(uri, connect_timeout=15)
    try:
        pg_tabel = ambil_pg(conn)
        for nama, _, _, data in pg_tabel:
            print(f"  {nama:20} {len(data):5} baris")

        with open(FILE_SKEMA, encoding="utf-8") as f:
            skema_sql = f.read()

        nama_zip = os.path.join(FOLDER_BACKUP, f"backup_wisata_sumut_{waktu.astimezone().strftime('%Y%m%d_%H%M%S')}.zip")
        bangun_zip(nama_zip, mongo, pg_tabel, skema_sql, waktu)
        print(f"\nZIP dibuat: {nama_zip}  ({os.path.getsize(nama_zip) / 1024:.0f} KB)")

        if args.uji_pulihkan:
            print("\nMenguji pemulihan dump SQL ke skema sementara...")
            asli, uji = uji_pulihkan(conn, skema_sql, pg_tabel, waktu)
            print(f"  Data asli      : {asli[0]} baris, sidik {asli[1]}")
            print(f"  Hasil pemulihan: {uji[0]} baris, sidik {uji[1]}")
            if asli == uji:
                print("  HASIL: dump SQL BERHASIL dipulihkan dan isinya IDENTIK.")
            else:
                print("  HASIL: BERBEDA. Jangan dikumpulkan, kirim hasil ini ke mentor.")
                raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()