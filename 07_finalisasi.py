import math
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher

import pandas as pd

from koneksi import get_db

# ======================================================
# PENGATURAN
# ======================================================

# Data yang dibuang
NAMA_DIBUANG = {
    "bank mandiri": "bukan tempat wisata (bank)",
    "pt pp london sumatera": "bukan tempat wisata (perusahaan)",
    "stasiun kereta api": "bukan tempat wisata (stasiun)",
    "simpang pos": "bukan tempat wisata (persimpangan)",
    "pelabuhan simanindo": "bukan tempat wisata (pelabuhan)",
    "ferry to simanindo including vehicles": "layanan transportasi",
    "volleyball and soccer field": "fasilitas olahraga umum",
    "bambu ungu resto": "restoran, bukan destinasi wisata",
    "situs arca padang nunang": "label, deskripsi, dan koordinat menunjuk Sumatera Barat",
}

# Aturan kategori dari kata kunci pada nama. URUTAN PENTING: yang atas dicek dulu.
# Kata kunci ditulis huruf kecil tanpa aksen.
ATURAN_KATEGORI = [
    ("Wisata Religi", [
        "mesjid", "masjid", "gereja", "goa maria", "getsemani",
        "temple", "pura", "vihara", "klenteng",
    ]),
    ("Wisata Alam", [
        "air terjun", "hot spring", "hot springs", "hotspring", "spring", "springs",
        "air panas", "pantai", "pulau", "goa", "gua", "cave", "bukit", "danau",
        "lakeside", "mangrove", "ekowisata", "mount", "gunung", "kubah lava",
        "rice terraces", "tanjung", "aek", "orangutan", "elephant camp",
        "alam", "sibayak",
    ]),
    ("Wisata Budaya & Sejarah", [
        "megalith", "megaliths", "batu", "stone", "grave", "kuburan", "makam",
        "rumah", "house", "houses", "huta", "village", "tradisional", "traditional",
        "bunker", "monumen", "monument", "tugu", "patung", "museum", "mansion",
        "meriam", "bolon", "kampung", "sopo", "jabu", "ompu", "execution",
    ]),
    ("Wisata Buatan & Edukasi", [
        "wahana", "kolam pancing", "air mancur", "open stage", "resto",
        "pos bloc", "taman", "monkey bridge", "viewing platform", "motocross",
    ]),
]

# Penyeragaman nama wilayah (huruf kecil -> nama baku)
ALIAS_WILAYAH = {
    "toba samosir": "Toba",   # nama lama kabupaten
}

# Wilayah yang mencurigakan (kemungkinan di luar Sumut). Hanya DITANDAI, tidak dibuang.
WILAYAH_PERLU_DICEK = {"tanggamus", "rao selatan"}

# Kandidat duplikat: nama mirip & jarak dekat
SIM_KANDIDAT = 0.70
JARAK_KANDIDAT_M = 300

FIELD_INFO = [
    "nama_en", "wilayah", "alamat", "deskripsi",
    "harga_tiket", "jam_operasional", "website",
]


# ======================================================
# FUNGSI BANTU
# ======================================================

def kunci(teks):
    """Huruf kecil, tanpa tanda baca dan aksen."""
    if not teks:
        return ""
    t = unicodedata.normalize("NFKD", str(teks)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


POLA = [
    (kategori, re.compile(r"\b(" + "|".join(re.escape(k) for k in kata) + r")\b"))
    for kategori, kata in ATURAN_KATEGORI
]


def tebak_kategori(nama):
    """Mengembalikan (kategori, kata_kunci) atau (None, None)."""
    k = kunci(nama)
    for kategori, pola in POLA:
        cocok = pola.search(k)
        if cocok:
            return kategori, cocok.group(1)
    return None, None


def rapikan_wilayah(w):
    if not w:
        return None
    w = re.sub(r"\s+", " ", w).strip()
    w = re.sub(r"^(kabupaten|kab\.|kota)\s+", "", w, flags=re.I)
    if w.islower() or w.isupper():
        w = w.title()
    return ALIAS_WILAYAH.get(w.lower(), w)


def jarak_meter(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def kemiripan(a, b):
    ka, kb = kunci(a), kunci(b)
    if not ka or not kb:
        return 0.0
    skor = SequenceMatcher(None, ka, kb).ratio()
    ta, tb = set(ka.split()), set(kb.split())
    pendek, panjang = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(pendek) >= 2 and pendek <= panjang:
        skor = max(skor, 0.9)
    return skor


def kosong(nilai):
    return nilai is None or nilai == "" or nilai == []


def kandidat_duplikat(data):
    hasil = []
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            a, b = data[i], data[j]
            d = jarak_meter(a["lat"], a["lon"], b["lat"], b["lon"])
            if d > JARAK_KANDIDAT_M:
                continue
            s = kemiripan(a["nama_wisata"], b["nama_wisata"])
            if s >= SIM_KANDIDAT:
                hasil.append((a["nama_wisata"], b["nama_wisata"], round(s, 2), round(d)))
    return sorted(hasil, key=lambda x: x[3])


# ======================================================
# PROGRAM UTAMA
# ======================================================

def main():
    db = get_db()
    print("Terhubung ke database:", db.name, "\n")

    data = list(db["wisata_final"].find({}, {"_id": 0}))
    print("Data awal (wisata_final):", len(data))

    log = []
    hasil = []
    berubah = []        # (nama, kategori_baru, kata_kunci)
    wilayah_dicek = []

    for r in data:
        # 1. Buang data yang bukan wisata
        alasan = NAMA_DIBUANG.get(kunci(r["nama_wisata"]))
        if alasan:
            log.append({
                "jenis": "dibuang",
                "nama": r["nama_wisata"],
                "alasan": alasan,
                "waktu": datetime.now(timezone.utc),
            })
            continue

        # 2. Kategori: hanya yang sekarang 'Lainnya'
        if r["kategori"] == "Lainnya":
            baru, kata = tebak_kategori(r["nama_wisata"])
            if baru:
                r["kategori_sebelumnya"] = "Lainnya"
                r["kategori"] = baru
                r["kategori_ditentukan_oleh"] = f"kata kunci '{kata}' pada nama"
                berubah.append((r["nama_wisata"], baru, kata))

        # 3. Wilayah: rapikan, simpan nilai asli
        r["wilayah_asli"] = r.get("wilayah")
        r["wilayah"] = rapikan_wilayah(r.get("wilayah"))
        if r["wilayah"] and r["wilayah"].lower() in WILAYAH_PERLU_DICEK:
            r["catatan_kualitas"] = "wilayah mencurigakan, kemungkinan di luar Sumut, perlu dicek"
            wilayah_dicek.append((r["nama_wisata"], r["wilayah"]))

        # 4. Hitung ulang kelengkapan
        terisi = sum(1 for k in FIELD_INFO if not kosong(r.get(k)))
        r["kolom_terisi"] = terisi
        r["skor_kelengkapan"] = round(terisi / len(FIELD_INFO), 2)
        r["waktu_final"] = datetime.now(timezone.utc)

        hasil.append(r)

    # 5. Ekspor CSV (dilakukan SEBELUM insert, karena insert menambah kolom _id)
    os.makedirs("output", exist_ok=True)
    df = pd.DataFrame(hasil)
    for kolom in ["nama_alternatif", "wilayah_alternatif", "sumber", "id_digabung"]:
        if kolom in df.columns:
            df[kolom] = df[kolom].apply(
                lambda x: "; ".join(map(str, x)) if isinstance(x, list) else x
            )
    df.to_csv(os.path.join("output", "wisata_sumut_final.csv"),
              index=False, encoding="utf-8-sig")

    # 6. Simpan ke MongoDB (hanya koleksi hasil)
    db["wisata_akhir"].delete_many({})
    db["wisata_akhir"].insert_many(hasil)
    db["log_finalisasi"].delete_many({})
    if log:
        db["log_finalisasi"].insert_many(log)

    # 7. Ringkasan
    print("\n" + "=" * 60)
    print("RINGKASAN FINALISASI")
    print("=" * 60)
    print("Data dibuang        :", len(log))
    for x in log:
        print(f"  - {x['nama']}: {x['alasan']}")
    print("Data akhir          :", len(hasil))

    print("\nJumlah per kategori:")
    for kat, n in Counter(r["kategori"] for r in hasil).most_common():
        print(f"  {kat}: {n}")

    print(f"\nKategori diubah dari 'Lainnya' ({len(berubah)} data):")
    for nama, kat, kata in sorted(berubah, key=lambda x: (x[1], x[0])):
        print(f"  [{kat}] {nama}   (kata kunci: {kata})")

    sisa = sorted(r["nama_wisata"] for r in hasil if r["kategori"] == "Lainnya")
    print(f"\nMasih 'Lainnya' ({len(sisa)} data):")
    for nama in sisa:
        print(f"  {nama}")

    print("\nWilayah yang ditandai perlu dicek:")
    for nama, w in wilayah_dicek:
        print(f"  {nama} ({w})")
    if not wilayah_dicek:
        print("  (tidak ada)")

    print("\nKelengkapan kolom (dari", len(hasil), "data):")
    for k in FIELD_INFO + ["lat", "lon"]:
        n = sum(1 for r in hasil if not kosong(r.get(k)))
        print(f"  {k:16}: {n} ({n / len(hasil) * 100:.0f}%)")

    kembar = kandidat_duplikat(hasil)
    print(f"\nKANDIDAT DUPLIKAT (nama mirip, jarak <= {JARAK_KANDIDAT_M} m): {len(kembar)}")
    print("Hanya ditampilkan, TIDAK digabung. Periksa dan putuskan sendiri.")
    for a, b, s, d in kembar:
        print(f"  {a}  |  {b}  | mirip {s} | {d} m")

    print("\nSELESAI. Koleksi: wisata_akhir, log_finalisasi. "
          "File: output/wisata_sumut_final.csv")


if __name__ == "__main__":
    main()