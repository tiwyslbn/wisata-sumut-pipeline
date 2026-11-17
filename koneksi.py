import os

from dotenv import load_dotenv
from pymongo import MongoClient

# Baca isi file .env (saat dijalankan di laptop)
load_dotenv()

# Nama database khusus proyek ini (terpisah dari database lain)
NAMA_DB = "wisata_sumut"


def bersihkan_uri(nilai, nama):
    """Merapikan kesalahan tempel yang umum: spasi, tanda kutip, dan awalan 'NAMA='."""
    if not nilai:
        return None
    v = nilai.strip()
    if v.upper().startswith(nama.upper() + "="):
        v = v.split("=", 1)[1].strip()
    return v.strip('"').strip("'").strip()


def baca_uri(nama):
    """Mengambil alamat koneksi dari variabel lingkungan dan merapikannya."""
    return bersihkan_uri(os.getenv(nama), nama)


def get_db():
    """Menghubungkan Python ke MongoDB Atlas dan mengembalikan database proyek."""
    uri = baca_uri("MONGODB_URI")
    if not uri:
        raise SystemExit("GAGAL: MONGODB_URI tidak ditemukan. Cek file .env atau rahasia di GitHub")

    if not uri.startswith(("mongodb://", "mongodb+srv://")):
        mentah = os.getenv("MONGODB_URI") or ""
        awal = mentah[:1]
        kutip = awal in ('"', "'")
        spasi = awal.isspace()
        ada_nama = "MONGODB_URI=" in mentah.upper()
        ada_postgres = "postgres" in mentah.lower()
        ada_skema = "://" in mentah
        raise SystemExit(
            "GAGAL: MONGODB_URI tidak berbentuk alamat MongoDB. Petunjuk (isinya tidak ditampilkan):\n"
            f"  panjang isi            : {len(mentah)} karakter\n"
            f"  diawali tanda kutip    : {kutip}\n"
            f"  diawali spasi/baris    : {spasi}\n"
            f"  memuat 'MONGODB_URI='  : {ada_nama}\n"
            f"  memuat kata 'postgres' : {ada_postgres}\n"
            f"  memuat '://'           : {ada_skema}"
        )

    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")  # tes koneksi
    return client[NAMA_DB]