import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher

from koneksi import get_db

# ======================================================
# PENGATURAN
# ======================================================

# cocok_otomatis: salah satu syarat ini terpenuhi
SIM_DEKAT, JARAK_DEKAT = 0.60, 300         # nama cukup mirip & sangat dekat
SIM_MIRIP, JARAK_MIRIP = 0.85, 1500        # nama sangat mirip & agak dekat

# perlu_dicek: salah satu syarat ini terpenuhi
SIM_CEK, JARAK_CEK = 0.60, 5000
SIM_CEK_JAUH, JARAK_CEK_JAUH = 0.85, 20000


# ======================================================
# FUNGSI BANTU
# ======================================================

def kunci_nama(nama):
    """Huruf kecil, tanpa tanda baca dan aksen."""
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


def kemiripan(a, b):
    """Skor 0-1 seberapa mirip dua nama."""
    ka, kb = kunci_nama(a), kunci_nama(b)
    if not ka or not kb:
        return 0.0
    rasio = SequenceMatcher(None, ka, kb).ratio()

    # Kalau semua kata di nama yang lebih pendek ada di nama yang lebih panjang
    # (mis. 'Museum Sumatera Utara' dan 'Museum Daerah Sumatera Utara')
    ta, tb = set(ka.split()), set(kb.split())
    pendek, panjang = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    termuat = 0.9 if len(pendek) >= 2 and pendek <= panjang else 0.0

    return max(rasio, termuat)


def skor_nama_osm(osm, wd):
    """Nama OSM (Indonesia dan Inggris) dibandingkan dengan nama Wikidata."""
    daftar = [osm.get("nama_wisata"), osm.get("nama_en")]
    return max(kemiripan(n, wd.get("nama_wisata")) for n in daftar if n)


def tentukan_status(sim, jarak):
    if (sim >= SIM_DEKAT and jarak <= JARAK_DEKAT) or \
       (sim >= SIM_MIRIP and jarak <= JARAK_MIRIP):
        return "cocok_otomatis"
    if (sim >= SIM_CEK and jarak <= JARAK_CEK) or \
       (sim >= SIM_CEK_JAUH and jarak <= JARAK_CEK_JAUH):
        return "perlu_dicek"
    return None


def buat_dokumen(p, status):
    o, w = p["o"], p["w"]
    return {
        "status": status,
        "skor_nama": round(p["sim"], 2),
        "jarak_meter": round(p["jarak"]),
        "id_osm": o["id_sumber"],
        "nama_osm": o["nama_wisata"],
        "kategori_osm": o.get("kategori"),
        "id_wikidata": w["id_sumber"],
        "nama_wikidata": w["nama_wisata"],
        "kategori_wikidata": w.get("kategori"),
        "waktu": datetime.now(timezone.utc),
    }


def cetak(daftar, judul, maks):
    print(f"\n{judul} ({len(daftar)}) - menampilkan maks. {maks}:")
    for d in daftar[:maks]:
        print(f"  OSM: {d['nama_osm']}  |  WD: {d['nama_wikidata']}  "
              f"| mirip {d['skor_nama']} | {d['jarak_meter']} m")


# ======================================================
# PROGRAM UTAMA
# ======================================================

def main():
    db = get_db()
    print("Terhubung ke database:", db.name, "\n")

    osm = list(db["dedup_osm"].find({}, {"_id": 0}))
    wd = list(db["dedup_wikidata"].find({}, {"_id": 0}))
    print(f"Data OSM      : {len(osm)}")
    print(f"Data Wikidata : {len(wd)}")

    # 1. Hitung semua pasangan yang mungkin
    kandidat = []
    for o in osm:
        for w in wd:
            if None in (o.get("lat"), o.get("lon"), w.get("lat"), w.get("lon")):
                continue
            jarak = jarak_meter(o["lat"], o["lon"], w["lat"], w["lon"])
            sim = skor_nama_osm(o, w)
            status = tentukan_status(sim, jarak)
            if status:
                kandidat.append({"o": o, "w": w, "sim": sim,
                                 "jarak": jarak, "status": status})

    # 2. Urutkan: cocok_otomatis dulu, lalu nama paling mirip, lalu paling dekat
    kandidat.sort(key=lambda p: (p["status"] != "cocok_otomatis",
                                 -p["sim"], p["jarak"]))

    # 3. Pilih pasangan otomatis, satu OSM hanya untuk satu Wikidata
    pakai_o, pakai_w = set(), set()
    otomatis = []
    for p in kandidat:
        if p["status"] != "cocok_otomatis":
            continue
        if p["o"]["id_sumber"] in pakai_o or p["w"]["id_sumber"] in pakai_w:
            continue
        pakai_o.add(p["o"]["id_sumber"])
        pakai_w.add(p["w"]["id_sumber"])
        otomatis.append(buat_dokumen(p, "cocok_otomatis"))

    # 4. Sisanya: kandidat yang perlu diperiksa manual
    cek = []
    for p in kandidat:
        if p["o"]["id_sumber"] in pakai_o or p["w"]["id_sumber"] in pakai_w:
            continue
        cek.append(buat_dokumen(p, "perlu_dicek"))

    # 5. Simpan (hanya koleksi hasil matching)
    db["match_pasangan"].delete_many({})
    semua = otomatis + cek
    if semua:
        db["match_pasangan"].insert_many(semua)

    # 6. Ringkasan
    id_o_dicek = {d["id_osm"] for d in cek}
    id_w_dicek = {d["id_wikidata"] for d in cek}
    print("\n" + "=" * 60)
    print("RINGKASAN MATCHING")
    print("=" * 60)
    print(f"Cocok otomatis            : {len(otomatis)} pasangan")
    print(f"Perlu dicek manual        : {len(cek)} pasangan")
    print(f"OSM tanpa pasangan        : "
          f"{len(osm) - len(pakai_o)} (termasuk yang perlu dicek)")
    print(f"Wikidata tanpa pasangan   : "
          f"{len(wd) - len(pakai_w)} (termasuk yang perlu dicek)")

    beda_kategori = [d for d in otomatis
                     if d["kategori_osm"] != d["kategori_wikidata"]]
    print(f"Cocok otomatis tetapi kategorinya berbeda: {len(beda_kategori)}")

    cetak(otomatis, "COCOK OTOMATIS", 40)
    cetak(cek, "PERLU DICEK MANUAL", 30)

    print("\nSELESAI. Koleksi baru: match_pasangan")


if __name__ == "__main__":
    main()