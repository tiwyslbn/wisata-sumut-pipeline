import argparse
import os
import subprocess
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from dotenv import load_dotenv

from koneksi import get_db

load_dotenv()

# (berkas, keterangan, argumen tambahan)
LANGKAH_EKSTRAK = ("00_ekstrak.py", "Mengambil data terbaru dari sumber", ["--timpa"])
LANGKAH = [
    ("01_simpan_raw.py", "Menyimpan data mentah ke MongoDB", []),
    ("02_profil_raw.py", "Memeriksa kondisi data mentah", []),
    ("03_cleaning.py", "Cleaning", []),
    ("04_deduplikasi.py", "Deduplikasi", []),
    ("05_matching.py", "Pencocokan dua sumber", []),
    ("06_enrichment.py", "Penggabungan dan pengayaan", []),
    ("07_finalisasi.py", "Finalisasi", []),
    ("08_gabung_manual.py", "Penggabungan manual", []),
    ("09_kualitas.py", "Pemeriksaan kualitas data", []),
    ("10_load_postgres.py", "Memuat data akhir ke PostgreSQL", []),
]


def jalankan(berkas, argumen):
    """Menjalankan satu program. Mengembalikan (kode, detik, 12 baris terakhir keluaran)."""
    mulai = time.time()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proses = subprocess.Popen(
        [sys.executable, berkas, *argumen],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env,
    )
    ekor = deque(maxlen=12)
    for baris in proses.stdout:
        print(baris, end="")
        ekor.append(baris.rstrip())
    proses.wait()
    return proses.returncode, time.time() - mulai, list(ekor)


def hitung_jumlah():
    """Jumlah data di MongoDB dan PostgreSQL, dipakai untuk pemeriksaan konsistensi."""
    hasil = {}
    try:
        db = get_db()
        hasil["mongo_raw_osm"] = db["raw_osm"].count_documents({})
        hasil["mongo_raw_wikidata"] = db["raw_wikidata"].count_documents({})
        hasil["mongo_hasil_akhir"] = db["hasil_akhir"].count_documents({})
    except Exception as e:
        hasil["mongo_error"] = type(e).__name__

    try:
        import psycopg2
        conn = psycopg2.connect(os.getenv("POSTGRES_URI"), connect_timeout=15)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM wisata_sumut.tempat_wisata")
        hasil["postgres_tempat_wisata"] = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        hasil["postgres_error"] = type(e).__name__

    hasil["konsisten"] = (
        "mongo_hasil_akhir" in hasil and "postgres_tempat_wisata" in hasil
        and hasil["mongo_hasil_akhir"] == hasil["postgres_tempat_wisata"]
    )
    return hasil


def main():
    parser = argparse.ArgumentParser(description="Pipeline ETL data wisata Sumatera Utara")
    parser.add_argument("--ekstrak", action="store_true",
                        help="ambil data terbaru dari OpenStreetMap dan Wikidata dulu")
    parser.add_argument("--pemicu", default="manual",
                        help="catatan siapa yang menjalankan: manual atau terjadwal")
    args = parser.parse_args()

    langkah = ([LANGKAH_EKSTRAK] if args.ekstrak else []) + LANGKAH

    log = get_db()["log_pipeline"]
    run = {
        "run_id": uuid.uuid4().hex[:8],
        "mulai": datetime.now(timezone.utc),
        "mode": "data_terbaru" if args.ekstrak else "data_tersimpan",
        "pemicu": args.pemicu,
        "status": "berjalan",
        "langkah": [],
    }
    _id = log.insert_one(run).inserted_id
    mulai_total = time.time()
    status, gagal_di = "berhasil", None

    try:
        for nomor, (berkas, ket, argumen) in enumerate(langkah, start=1):
            print("\n" + "#" * 60)
            print(f"# LANGKAH {nomor} dari {len(langkah)}: {ket}  ({berkas})")
            print("#" * 60)

            kode, detik, ekor = jalankan(berkas, argumen)
            catatan = {"berkas": berkas, "keterangan": ket,
                       "status": "berhasil" if kode == 0 else "gagal",
                       "detik": round(detik, 1), "kode_keluar": kode}
            if kode != 0:
                catatan["keluaran_akhir"] = ekor
            log.update_one({"_id": _id}, {"$push": {"langkah": catatan}})

            if kode != 0:
                status, gagal_di = "gagal", berkas
                print(f"\nBERHENTI: {berkas} gagal (kode {kode}).")
                break
    except KeyboardInterrupt:
        status, gagal_di = "dibatalkan", "dihentikan pengguna"
        print("\nDihentikan oleh pengguna.")

    jumlah = hitung_jumlah()
    durasi = round(time.time() - mulai_total, 1)
    log.update_one({"_id": _id}, {"$set": {
        "status": status, "gagal_di": gagal_di,
        "selesai": datetime.now(timezone.utc),
        "durasi_detik": durasi, "jumlah": jumlah,
    }})

    print("\n" + "=" * 60)
    print(f"PIPELINE {status.upper()}  |  run_id {run['run_id']}  |  {durasi:.0f} detik")
    print("=" * 60)
    for k, v in jumlah.items():
        print(f"  {k}: {v}")
    if status == "berhasil":
        print("\nKedua database KONSISTEN." if jumlah["konsisten"]
              else "\nPERINGATAN: jumlah data MongoDB dan PostgreSQL BERBEDA.")
    if status != "berhasil" or not jumlah["konsisten"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()