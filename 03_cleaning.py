import re
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

from koneksi import get_db

# ======================================================
# PENGATURAN 
# ======================================================

# Jenis Wikidata yang dibuang (gunung = fitur geografi, bukan destinasi)
JENIS_WIKIDATA_DIBUANG = {"gunung"}

# Kalau lokasi Wikidata menyebut salah satu ini, dianggap di luar Sumut
PROVINSI_LAIN = [
    "Aceh", "Sumatera Barat", "Riau", "Kepulauan Riau",
    "Jambi", "Bengkulu", "Sumatera Selatan",
]

# Jenis Wikidata yang dibuang (gunung = fitur geografi; masjid/gereja = tempat ibadah umum)
JENIS_WIKIDATA_DIBUANG = {"gunung", "masjid", "gereja"}

# Pengecualian: tempat yang jenisnya dibuang tetapi tetap dipertahankan karena
# dinilai destinasi wisata. Tulis nama persis seperti di Wikidata, HURUF KECIL.
# Contoh pengisian: {"nama tempat satu", "nama tempat dua"}
PENGECUALIAN_NAMA = set()

# Lokasi yang terlalu umum, tidak dianggap sebagai kabupaten/kota
LOKASI_UMUM = {"sumatera utara", "indonesia"}

# Nama yang bukan nama tempat sebenarnya (pakai huruf kecil)
NAMA_TERLALU_UMUM = {"view", "viewpoint", "puncak"}

# Pemetaan jenis tempat -> kategori seragam
KATEGORI = {
    # dari OpenStreetMap
    "viewpoint": "Wisata Alam",
    "attraction": "Lainnya",
    "museum": "Wisata Budaya & Sejarah",
    "zoo": "Wisata Buatan & Edukasi",
    "theme_park": "Wisata Buatan & Edukasi",
    "gallery": "Wisata Budaya & Sejarah",
    # dari Wikidata
    "danau": "Wisata Alam",
    "air terjun": "Wisata Alam",
    "pantai": "Wisata Alam",
    "gunung": "Wisata Alam",
    "masjid": "Wisata Religi",
    "gereja": "Wisata Religi",
    "situs arkeologi": "Wisata Budaya & Sejarah",
    "monumen": "Wisata Budaya & Sejarah",
    "taman": "Wisata Buatan & Edukasi",
    "kebun binatang": "Wisata Buatan & Edukasi",
    "objek wisata": "Lainnya",
}


# ======================================================
# FUNGSI BANTU
# ======================================================

def bersihkan_teks(nilai):
    """Menghapus spasi berlebih. Teks kosong menjadi None."""
    if nilai is None:
        return None
    teks = re.sub(r"\s+", " ", str(nilai)).strip()
    return teks if teks else None


def rapikan_huruf(teks):
    """Kalau seluruhnya huruf kecil atau seluruhnya kapital, ubah jadi Huruf Awal Kapital."""
    if teks is None:
        return None
    if teks.islower() or teks.isupper():
        return teks.title()
    return teks


def ke_angka(nilai):
    """Mengubah teks jadi angka desimal. Gagal -> None."""
    teks = bersihkan_teks(nilai)
    if teks is None:
        return None
    try:
        return float(teks.replace(",", "."))
    except ValueError:
        return None


def baca_koordinat_wikidata(teks):
    """Mengubah 'Point(98.67 2.54)' menjadi (lat, lon) = (2.54, 98.67)."""
    teks = bersihkan_teks(teks)
    if teks is None:
        return None, None
    cocok = re.match(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", teks)
    if not cocok:
        return None, None
    lon, lat = float(cocok.group(1)), float(cocok.group(2))
    return lat, lon


def catat(sumber, rekaman, alasan):
    """Membuat satu catatan untuk data yang dibuang."""
    return {
        "sumber": sumber,
        "nama": rekaman.get("name") or rekaman.get("itemLabel"),
        "id_sumber": rekaman.get("@id") or rekaman.get("item"),
        "nomor_baris": rekaman.get("_meta", {}).get("nomor_baris"),
        "alasan": alasan,
        "waktu": datetime.now(timezone.utc),
    }


# ======================================================
# CLEANING OSM
# ======================================================

def bersihkan_osm(data_mentah, log):
    hasil = []
    for r in data_mentah:
        nama = rapikan_huruf(bersihkan_teks(r.get("name")))

        if nama is None:
            log.append(catat("osm", r, "tidak punya nama"))
            continue
        if nama.lower() in NAMA_TERLALU_UMUM:
            log.append(catat("osm", r, "nama terlalu umum"))
            continue

        jenis = bersihkan_teks(r.get("tourism"))
        jenis_kunci = jenis.lower() if jenis else ""

        # fee = ya/tidak berbayar, charge = nominal. Pakai charge dulu kalau ada.
        harga = bersihkan_teks(r.get("charge")) or bersihkan_teks(r.get("fee"))

        hasil.append({
            "sumber": "osm",
            "id_sumber": f"{bersihkan_teks(r.get('@type'))}/{bersihkan_teks(r.get('@id'))}",
            "nama_wisata": nama,
            "nama_en": bersihkan_teks(r.get("name:en")),
            "jenis_asal": jenis,
            "kategori": KATEGORI.get(jenis_kunci, "Lainnya"),
            "wilayah": bersihkan_teks(r.get("addr:city")),
            "alamat": bersihkan_teks(r.get("addr:full")),
            "deskripsi": bersihkan_teks(r.get("description")),
            "harga_tiket": harga,
            "jam_operasional": bersihkan_teks(r.get("opening_hours")),
            "website": bersihkan_teks(r.get("website")),
            "lat": ke_angka(r.get("@lat")),
            "lon": ke_angka(r.get("@lon")),
            "nomor_baris_raw": r.get("_meta", {}).get("nomor_baris"),
        })
    return hasil


# ======================================================
# CLEANING WIKIDATA
# ======================================================

def bersihkan_wikidata(data_mentah, log):
    hasil = []
    for r in data_mentah:
        nama = rapikan_huruf(bersihkan_teks(r.get("itemLabel")))
        jenis = bersihkan_teks(r.get("tipeLabel"))
        jenis_kunci = jenis.lower() if jenis else ""
        lokasi = bersihkan_teks(r.get("lokasiLabel"))

        # Kalau tidak punya label, Wikidata mengisi dengan kode seperti Q12345
        if nama is None or re.fullmatch(r"Q\d+", nama):
            log.append(catat("wikidata", r, "tidak punya nama (hanya kode Q)"))
            continue
        if jenis_kunci in JENIS_WIKIDATA_DIBUANG and nama.lower() not in PENGECUALIAN_NAMA:
            log.append(catat("wikidata", r, f"jenis '{jenis_kunci}' dibuang"))
            continue
        if lokasi and any(p.lower() in lokasi.lower() for p in PROVINSI_LAIN):
            log.append(catat("wikidata", r, "lokasi tercatat di provinsi lain"))
            continue

        # Lokasi umum (mis. 'Sumatera Utara') tidak berguna sebagai kabupaten/kota
        wilayah = None if (lokasi is None or lokasi.lower() in LOKASI_UMUM) else lokasi

        lat, lon = baca_koordinat_wikidata(r.get("coord"))
        item = bersihkan_teks(r.get("item")) or ""

        hasil.append({
            "sumber": "wikidata",
            "id_sumber": item.split("/")[-1],
            "nama_wisata": nama,
            "nama_en": None,
            "jenis_asal": jenis,
            "kategori": KATEGORI.get(jenis_kunci, "Lainnya"),
            "wilayah": wilayah,
            "alamat": None,
            "deskripsi": bersihkan_teks(r.get("itemDescription")),
            "harga_tiket": None,
            "jam_operasional": None,
            "website": None,
            "lat": lat,
            "lon": lon,
            "nomor_baris_raw": r.get("_meta", {}).get("nomor_baris"),
        })
    return hasil


# ======================================================
# PENYIMPANAN & RINGKASAN
# ======================================================

def simpan(db, nama_koleksi, data):
    db[nama_koleksi].delete_many({})   # hanya koleksi hasil, bukan data mentah
    if data:
        db[nama_koleksi].insert_many(data)


def ringkas(data, judul):
    print("=" * 60)
    print(judul, "->", len(data), "baris")
    print("=" * 60)
    if not data:
        return
    df = pd.DataFrame(data)
    print("Kategori:")
    print(df["kategori"].value_counts().to_string())
    print("\nJumlah sel TERISI per kolom:")
    print(df.notna().sum().to_string())
    print()


def main():
    db = get_db()
    print("Terhubung ke database:", db.name, "\n")

    mentah_osm = list(db["raw_osm"].find({}, {"_id": 0}))
    mentah_wd = list(db["raw_wikidata"].find({}, {"_id": 0}))
    print("Data mentah OSM      :", len(mentah_osm))
    print("Data mentah Wikidata :", len(mentah_wd), "\n")

    log = []
    bersih_osm = bersihkan_osm(mentah_osm, log)
    bersih_wd = bersihkan_wikidata(mentah_wd, log)

    simpan(db, "clean_osm", bersih_osm)
    simpan(db, "clean_wikidata", bersih_wd)
    simpan(db, "log_dibuang", log)

    ringkas(bersih_osm, "CLEAN OSM")
    ringkas(bersih_wd, "CLEAN WIKIDATA")

    print("=" * 60)
    print("DATA YANG DIBUANG (sumber, alasan: jumlah)")
    print("=" * 60)
    hitung = Counter((x["sumber"], x["alasan"]) for x in log)
    for (sumber, alasan), jumlah in sorted(hitung.items()):
        print(f"  [{sumber}] {alasan}: {jumlah}")

    print("\nSELESAI. Koleksi baru: clean_osm, clean_wikidata, log_dibuang")


if __name__ == "__main__":
    main()