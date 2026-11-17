import os
from collections import Counter

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

from koneksi import get_db

load_dotenv()

FILE_SKEMA = os.path.join("sql", "skema_postgres.sql")

# Urutan kolom harus sama dengan urutan nilai pada fungsi baris_dari_dokumen
KOLOM = [
    "nama_wisata", "nama_en", "nama_alternatif", "kategori_id",
    "jenis_osm", "jenis_wikidata", "wilayah", "wilayah_alternatif", "wilayah_asli",
    "alamat", "deskripsi", "harga_tiket", "jam_operasional", "website",
    "lat", "lon", "sumber", "id_osm", "id_wikidata",
    "status_pencocokan", "skor_nama_pencocokan", "jarak_pencocokan_m",
    "skor_kelengkapan", "kolom_terisi", "jumlah_digabung",
    "catatan_kualitas", "kemungkinan_duplikat", "kategori_ditentukan_oleh",
]


def ke_teks(nilai):
    """Teks kosong menjadi NULL."""
    if nilai is None or str(nilai).strip() == "":
        return None
    return str(nilai).strip()


def ke_daftar(nilai):
    """Mengubah nilai menjadi daftar teks (untuk kolom array)."""
    if nilai is None:
        return []
    if isinstance(nilai, list):
        return [str(x) for x in nilai if x not in (None, "")]
    return [str(nilai)]


def baris_dari_dokumen(d, id_kategori):
    return (
        d["nama_wisata"], ke_teks(d.get("nama_en")), ke_daftar(d.get("nama_alternatif")),
        id_kategori[d["kategori"]],
        ke_teks(d.get("jenis_osm")), ke_teks(d.get("jenis_wikidata")),
        ke_teks(d.get("wilayah")), ke_daftar(d.get("wilayah_alternatif")),
        ke_teks(d.get("wilayah_asli")),
        ke_teks(d.get("alamat")), ke_teks(d.get("deskripsi")), ke_teks(d.get("harga_tiket")),
        ke_teks(d.get("jam_operasional")), ke_teks(d.get("website")),
        d["lat"], d["lon"], ke_daftar(d.get("sumber")),
        ke_teks(d.get("id_osm")), ke_teks(d.get("id_wikidata")),
        d["status_pencocokan"], d.get("skor_nama_pencocokan"), d.get("jarak_pencocokan_m"),
        d.get("skor_kelengkapan"), d.get("kolom_terisi"), d.get("jumlah_digabung", 1),
        ke_teks(d.get("catatan_kualitas")), ke_daftar(d.get("kemungkinan_duplikat")),
        ke_teks(d.get("kategori_ditentukan_oleh")),
    )


def main():
    # 1. Baca data akhir dari MongoDB
    db = get_db()
    dokumen = list(db["hasil_akhir"].find({}, {"_id": 0}))
    if not dokumen:
        raise SystemExit("Koleksi hasil_akhir kosong. Jalankan 08_gabung_manual.py dulu.")
    print("Data di MongoDB (hasil_akhir):", len(dokumen))

    # 2. Terhubung ke PostgreSQL
    uri = os.getenv("POSTGRES_URI")
    if not uri:
        raise SystemExit("GAGAL: POSTGRES_URI tidak ditemukan. Cek file .env")
    conn = psycopg2.connect(uri, connect_timeout=15)
    cur = conn.cursor()

    try:
        # 3. Buat skema dan tabel (aman dijalankan berulang)
        with open(FILE_SKEMA, encoding="utf-8") as f:
            cur.execute(f.read())

        # 4. Isi tabel kategori, lalu ambil pemetaan nama -> id
        nama_kategori = sorted({d["kategori"] for d in dokumen})
        execute_values(
            cur,
            "INSERT INTO wisata_sumut.kategori (nama) VALUES %s ON CONFLICT (nama) DO NOTHING",
            [(n,) for n in nama_kategori],
        )
        cur.execute("SELECT nama, id FROM wisata_sumut.kategori")
        id_kategori = dict(cur.fetchall())

        # 5. Kosongkan tabel tempat_wisata lalu isi ulang (dalam satu transaksi,
        #    jadi kalau gagal di tengah jalan, data lama tidak rusak)
        cur.execute("TRUNCATE wisata_sumut.tempat_wisata RESTART IDENTITY")
        baris = [baris_dari_dokumen(d, id_kategori) for d in dokumen]
        execute_values(
            cur,
            f"INSERT INTO wisata_sumut.tempat_wisata ({', '.join(KOLOM)}) VALUES %s",
            baris,
        )

        conn.commit()
    except Exception as e:
        conn.rollback()
        print("GAGAL memuat data, perubahan dibatalkan.")
        print(type(e).__name__, ":", str(e).splitlines()[0])
        raise SystemExit(1)

    # 6. Pemeriksaan hasil: bandingkan dengan MongoDB
    cur.execute("SELECT count(*) FROM wisata_sumut.tempat_wisata")
    jumlah_pg = cur.fetchone()[0]
    print("Data di PostgreSQL (tempat_wisata):", jumlah_pg)
    print("Jumlah SAMA dengan MongoDB" if jumlah_pg == len(dokumen)
          else "PERINGATAN: jumlah BERBEDA dengan MongoDB")

    cur.execute("""
        SELECT k.nama, count(*)
        FROM wisata_sumut.tempat_wisata t
        JOIN wisata_sumut.kategori k ON k.id = t.kategori_id
        GROUP BY k.nama ORDER BY count(*) DESC
    """)
    pg = dict(cur.fetchall())
    mongo = Counter(d["kategori"] for d in dokumen)

    print("\nJumlah per kategori (PostgreSQL | MongoDB):")
    for nama, n in pg.items():
        tanda = "sama" if mongo.get(nama) == n else "BEDA"
        print(f"  {nama:28} {n:4} | {mongo.get(nama, 0):4}  {tanda}")

    cur.execute("""
        SELECT nama_wisata, status_pencocokan, kolom_terisi
        FROM wisata_sumut.tempat_wisata
        ORDER BY kolom_terisi DESC NULLS LAST, nama_wisata LIMIT 5
    """)
    print("\n5 data dengan informasi terlengkap:")
    for r in cur.fetchall():
        print("  ", r)

    cur.close()
    conn.close()
    print("\nSELESAI. Tabel: wisata_sumut.kategori dan wisata_sumut.tempat_wisata")


if __name__ == "__main__":
    main()