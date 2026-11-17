import os
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

from koneksi import get_db

# ======================================================
# PENGATURAN (hasil pemeriksaan manual di peta)
# ======================================================

# Pasangan yang DIGABUNG (nama persis seperti di data)
GABUNG = [
    ("Museum Simalungun", "Simalungun"),                              # nomor 2
    ("Museum Huta Bolon Simanindo", "Bolon Simanindo"),               # nomor 3
    ("Alam Sibayak Hot Spring", "Alam Sibayak"),                      # nomor 4
    ("Museum Zoologi", "Museum Zoologi Pematang Siantar"),            # nomor 8
    ("Tumöri Tourist Village",
     "Tumöri Tourist Village with several traditional North Nias houses"),  # nomor 9
]

# Pasangan yang RAGU: tidak digabung, hanya diberi catatan
RAGU = [
    ("Pariban Hotspring", "Daunparis Hot Spring"),                    # nomor 5
    ("Hot Spring", "Anugrah Sibayak Hot Spring"),                     # nomor 6
    ("Alam Sibayak Hot Spring", "Anugrah Sibayak Hot Spring"),        # nomor 7
    ("Hot Spring", "Alam Sibayak Hot Spring"),                        # nomor 10
]

FIELD_INFO = [
    "nama_en", "wilayah", "alamat", "deskripsi",
    "harga_tiket", "jam_operasional", "website",
]


# ======================================================
# FUNGSI BANTU
# ======================================================

def kosong(nilai):
    return nilai is None or nilai == "" or nilai == []


def cari(data, nama):
    """Mencari data berdasarkan nama persis (termasuk nama alternatif)."""
    return [
        d for d in data
        if d["nama_wisata"] == nama or nama in (d.get("nama_alternatif") or [])
    ]


def pilih_utama(a, b):
    """Baris yang lebih lengkap jadi data utama. Seri: yang sudah 'cocok', lalu nama lebih panjang."""
    def skor(r):
        return (r.get("kolom_terisi", 0),
                r.get("status_pencocokan") == "cocok",
                len(r["nama_wisata"]))
    return (a, b) if skor(a) >= skor(b) else (b, a)


def gabung(utama, dup):
    """Memasukkan informasi dari 'dup' ke 'utama'."""
    for k in FIELD_INFO:
        if kosong(utama.get(k)) and not kosong(dup.get(k)):
            utama[k] = dup[k]

    # Nama lain (termasuk nama alternatif milik duplikat)
    alt = list(utama.get("nama_alternatif") or [])
    for nama in [dup["nama_wisata"]] + list(dup.get("nama_alternatif") or []):
        if nama != utama["nama_wisata"] and nama not in alt:
            alt.append(nama)
    utama["nama_alternatif"] = alt

    # Wilayah lain kalau berbeda
    w_a = list(utama.get("wilayah_alternatif") or [])
    for w in [dup.get("wilayah")] + list(dup.get("wilayah_alternatif") or []):
        if w and w != utama.get("wilayah") and w not in w_a:
            w_a.append(w)
    utama["wilayah_alternatif"] = w_a

    # Sumber dan ID
    sumber = list(utama.get("sumber") or [])
    for s in dup.get("sumber") or []:
        if s not in sumber:
            sumber.append(s)
    utama["sumber"] = sumber
    for k in ("id_osm", "id_wikidata"):
        if kosong(utama.get(k)) and not kosong(dup.get(k)):
            utama[k] = dup[k]

    # Kategori: pakai milik duplikat kalau milik utama masih 'Lainnya'
    if utama.get("kategori") == "Lainnya" and dup.get("kategori") not in (None, "Lainnya"):
        utama["kategori"] = dup["kategori"]

    utama["jumlah_digabung"] = utama.get("jumlah_digabung", 1) + 1
    utama.setdefault("id_digabung", []).append(
        dup.get("id_osm") or dup.get("id_wikidata")
    )


def hitung_kelengkapan(r):
    terisi = sum(1 for k in FIELD_INFO if not kosong(r.get(k)))
    r["kolom_terisi"] = terisi
    r["skor_kelengkapan"] = round(terisi / len(FIELD_INFO), 2)


# ======================================================
# PROGRAM UTAMA
# ======================================================

def main():
    db = get_db()
    print("Terhubung ke database:", db.name, "\n")

    data = list(db["wisata_akhir"].find({}, {"_id": 0}))
    awal = len(data)
    print("Data awal (wisata_akhir):", awal)

    log = []

    # 1. Penggabungan manual
    for nama_a, nama_b in GABUNG:
        a, b = cari(data, nama_a), cari(data, nama_b)
        if len(a) != 1 or len(b) != 1:
            print(f"PERINGATAN: '{nama_a}' / '{nama_b}' tidak ditemukan atau ganda "
                  f"({len(a)} dan {len(b)} hasil), dilewati.")
            continue
        utama, dup = pilih_utama(a[0], b[0])
        gabung(utama, dup)
        data.remove(dup)
        hitung_kelengkapan(utama)
        log.append({
            "jenis": "gabung_manual",
            "dipertahankan": utama["nama_wisata"],
            "digabung": dup["nama_wisata"],
            "alasan": "hasil pemeriksaan manual di peta: tempat yang sama",
            "waktu": datetime.now(timezone.utc),
        })

    # 2. Pasangan ragu: hanya diberi catatan
    for nama_a, nama_b in RAGU:
        a, b = cari(data, nama_a), cari(data, nama_b)
        if len(a) != 1 or len(b) != 1:
            print(f"PERINGATAN: pasangan ragu '{nama_a}' / '{nama_b}' tidak ditemukan "
                  f"atau ganda, dilewati.")
            continue
        for r, lawan in ((a[0], nama_b), (b[0], nama_a)):
            r.setdefault("kemungkinan_duplikat", [])
            if lawan not in r["kemungkinan_duplikat"]:
                r["kemungkinan_duplikat"].append(lawan)
        log.append({
            "jenis": "ragu_tidak_digabung",
            "dipertahankan": nama_a,
            "digabung": nama_b,
            "alasan": "belum bisa dipastikan, dibiarkan terpisah",
            "waktu": datetime.now(timezone.utc),
        })

    # 3. Ekspor CSV (sebelum insert, karena insert menambah kolom _id)
    os.makedirs("output", exist_ok=True)
    df = pd.DataFrame(data)
    for kolom in ["nama_alternatif", "wilayah_alternatif", "sumber",
                  "id_digabung", "kemungkinan_duplikat"]:
        if kolom in df.columns:
            df[kolom] = df[kolom].apply(
                lambda x: "; ".join(map(str, x)) if isinstance(x, list) else x
            )
    df.to_csv(os.path.join("output", "wisata_sumut_final.csv"),
              index=False, encoding="utf-8-sig")

    # 4. Simpan ke MongoDB (hanya koleksi hasil)
    db["hasil_akhir"].delete_many({})
    db["hasil_akhir"].insert_many(data)
    db["log_gabung_manual"].delete_many({})
    if log:
        db["log_gabung_manual"].insert_many(log)

    # 5. Ringkasan
    print("\n" + "=" * 60)
    print("RINGKASAN PENGGABUNGAN MANUAL")
    print("=" * 60)
    print("Data awal  :", awal)
    print("Data akhir :", len(data), f"(berkurang {awal - len(data)})")

    print("\nPasangan yang DIGABUNG:")
    for x in log:
        if x["jenis"] == "gabung_manual":
            print(f"  '{x['digabung']}'  ->  digabung ke  '{x['dipertahankan']}'")

    print("\nPasangan RAGU (tidak digabung, diberi catatan):")
    for x in log:
        if x["jenis"] == "ragu_tidak_digabung":
            print(f"  '{x['dipertahankan']}'  |  '{x['digabung']}'")

    print("\nJumlah per kategori:")
    for kat, n in Counter(r["kategori"] for r in data).most_common():
        print(f"  {kat}: {n}")

    print("\nKelengkapan kolom (dari", len(data), "data):")
    for k in FIELD_INFO + ["lat", "lon"]:
        n = sum(1 for r in data if not kosong(r.get(k)))
        print(f"  {k:16}: {n} ({n / len(data) * 100:.0f}%)")

    ditandai = [r for r in data if r.get("catatan_kualitas")]
    print(f"\nData dengan catatan kualitas (wilayah mencurigakan): {len(ditandai)}")
    for r in ditandai:
        print(f"  {r['nama_wisata']}  ({r.get('wilayah_asli')})")

    print("\nSELESAI. Koleksi: hasil_akhir, log_gabung_manual. "
          "File: output/wisata_sumut_final.csv (diperbarui)")


if __name__ == "__main__":
    main()