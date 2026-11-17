import os
import re
from collections import Counter
from datetime import datetime, timezone

from koneksi import get_db

# ======================================================
# PENGATURAN
# ======================================================

KATEGORI_VALID = {
    "Wisata Alam", "Wisata Budaya & Sejarah", "Wisata Buatan & Edukasi",
    "Wisata Religi", "Lainnya",
}

# Kotak kasar sekitar Sumatera Utara. Hanya menangkap kesalahan koordinat yang
# sangat jauh, BUKAN batas provinsi yang sebenarnya.
LAT_MIN, LAT_MAX = -0.5, 4.5
LON_MIN, LON_MAX = 96.5, 100.5

FIELD_INFO = [
    "nama_en", "wilayah", "alamat", "deskripsi",
    "harga_tiket", "jam_operasional", "website",
]

# Nama dengan kata lebih banyak dari ini dicurigai berupa kalimat/komentar
MAKS_KATA_NAMA = 6
POLA_KOMENTAR = re.compile(r"\.\s+[A-Za-z]")   # contoh: 'Hot spring. So beautiful.'

ALUR = [
    ("Data mentah OSM", "raw_osm"),
    ("Data mentah Wikidata", "raw_wikidata"),
    ("Setelah cleaning OSM", "clean_osm"),
    ("Setelah cleaning Wikidata", "clean_wikidata"),
    ("Setelah deduplikasi OSM", "dedup_osm"),
    ("Setelah deduplikasi Wikidata", "dedup_wikidata"),
    ("Setelah penggabungan 2 sumber", "wisata_final"),
    ("Setelah finalisasi", "wisata_akhir"),
    ("HASIL AKHIR (setelah gabung manual)", "hasil_akhir"),
]


def kosong(nilai):
    return nilai is None or nilai == "" or nilai == []


def main():
    db = get_db()
    baris = []

    def tulis(teks=""):
        print(teks)
        baris.append(teks)

    tulis(f"LAPORAN KUALITAS DATA - dibuat {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    tulis("")

    # ---------------------------------------------------
    # A. ALUR JUMLAH DATA
    # ---------------------------------------------------
    tulis("=" * 60)
    tulis("A. ALUR JUMLAH DATA (dari mentah sampai akhir)")
    tulis("=" * 60)
    alur = {}
    for label, koleksi in ALUR:
        jumlah = db[koleksi].count_documents({})
        alur[koleksi] = jumlah
        tulis(f"  {label:40}: {jumlah}")

    data = list(db["hasil_akhir"].find({}, {"_id": 0}))
    n = len(data)
    if n == 0:
        raise SystemExit("Koleksi hasil_akhir kosong. Jalankan 08_gabung_manual.py dulu.")

    # ---------------------------------------------------
    # B. KELENGKAPAN
    # ---------------------------------------------------
    tulis("")
    tulis("=" * 60)
    tulis("B. KELENGKAPAN")
    tulis("=" * 60)
    kelengkapan = {}
    for k in FIELD_INFO + ["lat", "lon"]:
        t = sum(1 for r in data if not kosong(r.get(k)))
        kelengkapan[k] = round(t / n * 100, 1)
        tulis(f"  {k:16}: {t:4} dari {n} ({t / n * 100:.0f}%)")

    sel_total = n * len(FIELD_INFO)
    sel_isi = sum(1 for r in data for k in FIELD_INFO if not kosong(r.get(k)))
    keseluruhan = round(sel_isi / sel_total * 100, 1)
    tulis(f"\n  Kelengkapan keseluruhan ({len(FIELD_INFO)} kolom informasi): {keseluruhan}%")

    nol = sum(1 for r in data if r.get("kolom_terisi", 0) == 0)
    tulis(f"  Data yang SEMUA kolom informasinya kosong: {nol}")

    tulis("\n  Rata-rata kolom terisi menurut asal data:")
    per_status = {}
    for r in data:
        per_status.setdefault(r.get("status_pencocokan", "?"), []).append(
            r.get("kolom_terisi", 0)
        )
    rata_status = {}
    for status, daftar in sorted(per_status.items()):
        rata = sum(daftar) / len(daftar)
        rata_status[status] = round(rata, 2)
        tulis(f"    {status:16}: {len(daftar):4} data, rata-rata "
              f"{rata:.2f} dari {len(FIELD_INFO)} kolom")

    # ---------------------------------------------------
    # C. KONSISTENSI
    # ---------------------------------------------------
    tulis("")
    tulis("=" * 60)
    tulis("C. KONSISTENSI")
    tulis("=" * 60)

    # 1. Kategori
    kat_salah = [r["nama_wisata"] for r in data if r.get("kategori") not in KATEGORI_VALID]
    tulis(f"  1. Kategori di luar daftar yang valid : {len(kat_salah)}")

    # 2. Koordinat
    luar = []
    for r in data:
        lat, lon = r.get("lat"), r.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            luar.append((r["nama_wisata"], lat, lon, "bukan angka"))
        elif not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            luar.append((r["nama_wisata"], lat, lon, "di luar kotak kasar Sumut"))
    tulis(f"  2. Koordinat bermasalah               : {len(luar)}")
    for nama, lat, lon, ket in luar:
        tulis(f"       {nama} ({lat}, {lon}) - {ket}")

    # 3. Nama kembar
    hitung_nama = Counter(r["nama_wisata"].strip().lower() for r in data)
    kembar = [nm for nm, c in hitung_nama.items() if c > 1]
    tulis(f"  3. Nama yang muncul lebih dari sekali : {len(kembar)}")
    for nm in kembar:
        for r in data:
            if r["nama_wisata"].strip().lower() == nm:
                tulis(f"       {r['nama_wisata']} ({r.get('lat')}, {r.get('lon')}) "
                      f"sumber: {', '.join(r.get('sumber', []))}")

    # 4. Penulisan wilayah
    wil = [r["wilayah"] for r in data if r.get("wilayah")]
    unik_asli = len(set(wil))
    unik_kecil = len({w.lower() for w in wil})
    tulis(f"  4. Nilai wilayah unik: {unik_asli}; setelah huruf kecil seragam: "
          f"{unik_kecil} (selisih {unik_asli - unik_kecil} = beda huruf besar/kecil)")

    # 5. Nama yang mirip komentar/kalimat
    aneh = [r["nama_wisata"] for r in data
            if POLA_KOMENTAR.search(r["nama_wisata"])
            or len(r["nama_wisata"].split()) > MAKS_KATA_NAMA]
    tulis(f"  5. Nama yang mirip kalimat/komentar   : {len(aneh)}")
    for nama in aneh:
        tulis(f"       {nama}")

    # 6. Spasi berlebih
    spasi = [r["nama_wisata"] for r in data
             if r["nama_wisata"] != r["nama_wisata"].strip() or "  " in r["nama_wisata"]]
    tulis(f"  6. Nama dengan spasi berlebih         : {len(spasi)}")

    # 7. Catatan yang sudah dipasang
    ada_catatan = [r for r in data if r.get("catatan_kualitas")]
    ada_mirip = [r for r in data if r.get("kemungkinan_duplikat")]
    tulis(f"  7. Data dengan catatan kualitas       : {len(ada_catatan)}")
    for r in ada_catatan:
        tulis(f"       {r['nama_wisata']} ({r.get('wilayah_asli')})")
    tulis(f"     Data bertanda 'kemungkinan duplikat': {len(ada_mirip)}")

    # ---------------------------------------------------
    # D. KETEPATAN PENCOCOKAN
    # ---------------------------------------------------
    tulis("")
    tulis("=" * 60)
    tulis("D. KETEPATAN PENCOCOKAN DUA SUMBER")
    tulis("=" * 60)
    pasangan = list(db["match_pasangan"].find({}, {"_id": 0}))
    otomatis = [p for p in pasangan if p["status"] == "cocok_otomatis"]
    perlu = [p for p in pasangan if p["status"] == "perlu_dicek"]
    ditolak = db["log_enrichment"].count_documents({"jenis": "pasangan_ditolak"})

    tulis(f"  Pasangan 'cocok otomatis' diusulkan program : {len(otomatis)}")
    tulis(f"  Ditolak setelah pemeriksaan manual          : {ditolak}")
    persen_tahan = None
    if otomatis:
        dipertahankan = len(otomatis) - ditolak
        persen_tahan = round(dipertahankan / len(otomatis) * 100, 1)
        tulis(f"  Dipertahankan                               : {dipertahankan} "
              f"({persen_tahan}% dari usulan)")
        rata_skor = sum(p["skor_nama"] for p in otomatis) / len(otomatis)
        rata_jarak = sum(p["jarak_meter"] for p in otomatis) / len(otomatis)
        tulis(f"  Rata-rata kemiripan nama / jarak (semua usulan): "
              f"{rata_skor:.2f} / {rata_jarak:.0f} m")
    tulis(f"  Pasangan 'perlu dicek' (tidak digabung)     : {len(perlu)}")

    cocok = sum(1 for r in data if r.get("status_pencocokan") == "cocok")
    n_wd = alur.get("dedup_wikidata", 0)
    if n_wd:
        tulis(f"  Tempat yang ada di kedua sumber             : {cocok} "
              f"({cocok / n_wd * 100:.0f}% dari data Wikidata)")

    tulis("\n  CATATAN: angka ini hasil pemeriksaan manual sebatas nama, jarak, dan peta")
    tulis("  untuk beberapa pasangan. Ini BUKAN akurasi terhadap data acuan lengkap.")
    tulis("  Di laporan tulis sebagai 'hasil pemeriksaan manual'.")

    # ---------------------------------------------------
    # SIMPAN
    # ---------------------------------------------------
    os.makedirs("output", exist_ok=True)
    with open(os.path.join("output", "laporan_kualitas_data.txt"),
              "w", encoding="utf-8") as f:
        f.write("\n".join(baris))

    ringkasan = {
        "waktu": datetime.now(timezone.utc),
        "total_data": n,
        "alur": alur,
        "kelengkapan_persen": kelengkapan,
        "kelengkapan_keseluruhan_persen": keseluruhan,
        "rata_kolom_terisi_per_status": rata_status,
        "konsistensi": {
            "kategori_tidak_valid": len(kat_salah),
            "koordinat_bermasalah": len(luar),
            "nama_muncul_lebih_dari_sekali": len(kembar),
            "nama_mirip_komentar": len(aneh),
            "nama_spasi_berlebih": len(spasi),
            "catatan_kualitas": len(ada_catatan),
        },
        "pencocokan": {
            "diusulkan_otomatis": len(otomatis),
            "ditolak_manual": ditolak,
            "dipertahankan_persen": persen_tahan,
            "perlu_dicek": len(perlu),
            "ada_di_kedua_sumber": cocok,
        },
    }
    db["laporan_kualitas"].delete_many({})
    db["laporan_kualitas"].insert_one(ringkasan)

    tulis("")
    tulis("SELESAI. File: output/laporan_kualitas_data.txt | Koleksi: laporan_kualitas")


if __name__ == "__main__":
    main()