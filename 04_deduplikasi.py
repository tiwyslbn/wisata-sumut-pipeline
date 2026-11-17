import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone

from koneksi import get_db

# ======================================================
# PENGATURAN
# ======================================================

# Dua tempat bernama sama dianggap SATU tempat kalau jaraknya tidak lebih dari ini
JARAK_MAKS_METER = 300

# Kolom yang diisi dari duplikat kalau di baris utama masih kosong
FIELD_ISI = [
    "nama_en", "alamat", "deskripsi", "harga_tiket",
    "jam_operasional", "website", "wilayah",
]


# ======================================================
# FUNGSI BANTU
# ======================================================

def kunci_nama(nama):
    """Menyeragamkan nama untuk perbandingan: huruf kecil, tanpa tanda baca dan aksen."""
    if not nama:
        return ""
    teks = unicodedata.normalize("NFKD", nama).encode("ascii", "ignore").decode()
    teks = re.sub(r"[^a-z0-9 ]", " ", teks.lower())
    return re.sub(r"\s+", " ", teks).strip()


def jarak_meter(lat1, lon1, lat2, lon2):
    """Jarak dua titik koordinat dalam meter (rumus haversine)."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def jumlah_terisi(rekaman):
    return sum(1 for k in FIELD_ISI if rekaman.get(k) not in (None, ""))


def cek_sama(a, b):
    """
    Mengembalikan (jenis, keterangan, jarak).
    jenis = None kalau dianggap BUKAN tempat yang sama.
    jarak hanya terisi kalau namanya sama (untuk dicatat sebagai 'mirip tapi jauh').
    """
    if a["id_sumber"] == b["id_sumber"]:
        return "id_sumber sama", "id sumber sama", None

    if kunci_nama(a["nama_wisata"]) != kunci_nama(b["nama_wisata"]):
        return None, None, None

    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return None, None, None

    d = jarak_meter(a["lat"], a["lon"], b["lat"], b["lon"])
    if d <= JARAK_MAKS_METER:
        return "nama sama & dekat", f"nama sama, jarak {d:.0f} m", d
    return None, None, d


def gabung(utama, duplikat):
    """Memasukkan informasi dari duplikat ke baris utama."""
    # Catat wilayah lain kalau berbeda (mis. satu tempat punya dua catatan wilayah)
    w_u, w_d = utama.get("wilayah"), duplikat.get("wilayah")
    if w_u and w_d and w_u != w_d:
        alt = utama.setdefault("wilayah_alternatif", [])
        if w_d not in alt:
            alt.append(w_d)

    # Isi kolom yang masih kosong
    for k in FIELD_ISI:
        if utama.get(k) in (None, "") and duplikat.get(k) not in (None, ""):
            utama[k] = duplikat[k]

    utama["jumlah_digabung"] = utama.get("jumlah_digabung", 1) + 1
    utama.setdefault("id_digabung", []).append(duplikat["id_sumber"])


def deduplikasi(data, sumber, log, log_mirip):
    # Baris paling lengkap diproses lebih dulu agar menjadi baris utama
    urut = sorted(
        data,
        key=lambda r: (-jumlah_terisi(r), r.get("nomor_baris_raw") or 0),
    )

    dipertahankan = []
    for r in urut:
        sudah_digabung = False
        mirip_jauh = []

        for utama in dipertahankan:
            jenis, ket, jarak = cek_sama(utama, r)
            if jenis:
                gabung(utama, r)
                log.append({
                    "sumber": sumber,
                    "nama": r["nama_wisata"],
                    "id_sumber": r["id_sumber"],
                    "nomor_baris_raw": r.get("nomor_baris_raw"),
                    "digabung_ke": utama["id_sumber"],
                    "jenis": jenis,
                    "alasan": ket,
                    "waktu": datetime.now(timezone.utc),
                })
                sudah_digabung = True
                break
            if jarak is not None:
                mirip_jauh.append((utama, jarak))

        if not sudah_digabung:
            dipertahankan.append(r)
            for utama, jarak in mirip_jauh:
                log_mirip.append({
                    "sumber": sumber,
                    "nama": r["nama_wisata"],
                    "id_1": utama["id_sumber"],
                    "id_2": r["id_sumber"],
                    "jarak_meter": round(jarak),
                    "keterangan": "nama sama tetapi jauh, dianggap tempat berbeda",
                })

    return dipertahankan


def simpan(db, nama_koleksi, data):
    db[nama_koleksi].delete_many({})   # hanya koleksi hasil, bukan data mentah/bersih
    if data:
        db[nama_koleksi].insert_many(data)


# ======================================================
# PROGRAM UTAMA
# ======================================================

def main():
    db = get_db()
    print("Terhubung ke database:", db.name, "\n")

    clean_osm = list(db["clean_osm"].find({}, {"_id": 0}))
    clean_wd = list(db["clean_wikidata"].find({}, {"_id": 0}))

    log, log_mirip = [], []
    hasil_osm = deduplikasi(clean_osm, "osm", log, log_mirip)
    hasil_wd = deduplikasi(clean_wd, "wikidata", log, log_mirip)

    simpan(db, "dedup_osm", hasil_osm)
    simpan(db, "dedup_wikidata", hasil_wd)
    simpan(db, "log_duplikat", log)
    simpan(db, "log_mirip", log_mirip)

    print("=" * 60)
    print("RINGKASAN DEDUPLIKASI")
    print("=" * 60)
    print(f"OSM      : {len(clean_osm)} -> {len(hasil_osm)} "
          f"(digabung {len(clean_osm) - len(hasil_osm)})")
    print(f"Wikidata : {len(clean_wd)} -> {len(hasil_wd)} "
          f"(digabung {len(clean_wd) - len(hasil_wd)})")

    print("\nJumlah duplikat per alasan:")
    for (sumber, jenis), n in sorted(Counter((x["sumber"], x["jenis"]) for x in log).items()):
        print(f"  [{sumber}] {jenis}: {n}")

    print("\nContoh duplikat yang digabung (maks. 15):")
    for x in log[:15]:
        print(f"  [{x['sumber']}] {x['nama']}  <-  {x['alasan']}")

    print(f"\nNama sama tetapi JAUH (tidak digabung): {len(log_mirip)}")
    for x in log_mirip[:15]:
        print(f"  [{x['sumber']}] {x['nama']}  jarak {x['jarak_meter']} m")

    print("\nSELESAI. Koleksi baru: dedup_osm, dedup_wikidata, log_duplikat, log_mirip")


if __name__ == "__main__":
    main()