from collections import Counter
from datetime import datetime, timezone

from koneksi import get_db

# ======================================================
# PENGATURAN (keputusan hasil pemeriksaan manual)
# ======================================================

# Pasangan "cocok otomatis" yang ternyata BUKAN tempat yang sama
# (nama OSM, nama Wikidata) persis seperti di hasil cek_pasangan.py
PASANGAN_DITOLAK = {
    ("Aek Natonang", "Danau Aek Natonang"),                # nomor 16
    ("Taman Tjong Yong Hian", "Galeri Tjong Yong Hian"),   # nomor 17
}

# Duplikat di OSM yang lolos dari deduplikasi (nama beda, lokasi sama).
# Format: (nama yang dipertahankan, nama yang digabungkan ke dalamnya)
# Hapus baris ini kalau hasil cek peta menunjukkan keduanya tempat berbeda.
GABUNG_OSM_MANUAL = [
    ("Museum Negeri Sumatera Utara", "Museum Daerah Sumatera Utara"),
]

# Kolom informasi yang dihitung untuk kelengkapan
FIELD_INFO = [
    "nama_en", "wilayah", "alamat", "deskripsi",
    "harga_tiket", "jam_operasional", "website",
]


# ======================================================
# FUNGSI BANTU
# ======================================================

def kosong(nilai):
    return nilai is None or nilai == "" or nilai == []


def isi_kosong(target, sumber):
    """Mengisi kolom yang masih kosong di target dari sumber."""
    for k in FIELD_INFO:
        if kosong(target.get(k)) and not kosong(sumber.get(k)):
            target[k] = sumber[k]


def gabung_osm_manual(osm_list, log):
    """Menggabungkan duplikat OSM yang ditentukan manual."""
    for nama_utama, nama_dup in GABUNG_OSM_MANUAL:
        utama = next((r for r in osm_list if r["nama_wisata"] == nama_utama), None)
        dup = next((r for r in osm_list if r["nama_wisata"] == nama_dup), None)

        if utama is None or dup is None:
            print(f"PERINGATAN: pasangan manual '{nama_utama}' / '{nama_dup}' "
                  f"tidak ditemukan, dilewati.")
            continue

        isi_kosong(utama, dup)
        utama.setdefault("id_digabung", []).append(dup["id_sumber"])
        utama["jumlah_digabung"] = utama.get("jumlah_digabung", 1) + 1
        osm_list.remove(dup)

        log.append({
            "jenis": "gabung_osm_manual",
            "nama": dup["nama_wisata"],
            "digabung_ke": utama["nama_wisata"],
            "alasan": "keputusan manual: lokasi sama, nama berbeda",
            "waktu": datetime.now(timezone.utc),
        })


def gabung_wilayah_alt(*daftar):
    """Menggabungkan semua nilai wilayah_alternatif tanpa duplikat."""
    hasil = []
    for d in daftar:
        for x in (d or []):
            if x not in hasil:
                hasil.append(x)
    return hasil


def hitung_kelengkapan(rekaman):
    terisi = sum(1 for k in FIELD_INFO if not kosong(rekaman.get(k)))
    return terisi, round(terisi / len(FIELD_INFO), 2)


def buat_final(o, w, pasangan):
    """Membuat satu data akhir. o = data OSM atau None, w = data Wikidata atau None."""
    if o and w:
        nama = w["nama_wisata"]
        alt = [o["nama_wisata"]] if o["nama_wisata"] != nama else []
        kategori = w["kategori"] if w.get("kategori") != "Lainnya" else o["kategori"]
        status = "cocok"
    elif o:
        nama, alt, kategori, status = o["nama_wisata"], [], o["kategori"], "hanya_osm"
    else:
        nama, alt, kategori, status = w["nama_wisata"], [], w["kategori"], "hanya_wikidata"

    sumber_utama = o or w   # data yang menyediakan koordinat

    rekaman = {
        "nama_wisata": nama,
        "nama_alternatif": alt,
        "nama_en": (o or {}).get("nama_en"),
        "kategori": kategori,
        "jenis_osm": (o or {}).get("jenis_asal"),
        "jenis_wikidata": (w or {}).get("jenis_asal"),
        "wilayah": (w or {}).get("wilayah") or (o or {}).get("wilayah"),
        "wilayah_alternatif": gabung_wilayah_alt(
            (o or {}).get("wilayah_alternatif"), (w or {}).get("wilayah_alternatif")
        ),
        "alamat": (o or {}).get("alamat"),
        "deskripsi": (w or {}).get("deskripsi") or (o or {}).get("deskripsi"),
        "harga_tiket": (o or {}).get("harga_tiket"),
        "jam_operasional": (o or {}).get("jam_operasional"),
        "website": (o or {}).get("website"),
        "lat": sumber_utama["lat"],      # koordinat OSM dipakai kalau ada
        "lon": sumber_utama["lon"],
        "sumber": [s for s, d in (("osm", o), ("wikidata", w)) if d],
        "id_osm": (o or {}).get("id_sumber"),
        "id_wikidata": (w or {}).get("id_sumber"),
        "status_pencocokan": status,
        "skor_nama_pencocokan": pasangan["skor_nama"] if pasangan else None,
        "jarak_pencocokan_m": pasangan["jarak_meter"] if pasangan else None,
        "waktu_dibuat": datetime.now(timezone.utc),
    }
    terisi, skor = hitung_kelengkapan(rekaman)
    rekaman["kolom_terisi"] = terisi
    rekaman["skor_kelengkapan"] = skor
    return rekaman


# ======================================================
# PROGRAM UTAMA
# ======================================================

def main():
    db = get_db()
    print("Terhubung ke database:", db.name, "\n")

    osm = list(db["dedup_osm"].find({}, {"_id": 0}))
    wd = list(db["dedup_wikidata"].find({}, {"_id": 0}))
    pasangan_semua = list(db["match_pasangan"].find({}, {"_id": 0}))
    print(f"OSM (hasil deduplikasi)      : {len(osm)}")
    print(f"Wikidata (hasil deduplikasi) : {len(wd)}")

    log = []

    # 1. Gabungkan duplikat OSM yang ditentukan manual
    gabung_osm_manual(osm, log)
    print(f"OSM setelah penggabungan manual : {len(osm)}")

    # 2. Pilih pasangan yang dipakai: cocok otomatis, bukan yang ditolak
    osm_by_id = {r["id_sumber"]: r for r in osm}
    wd_by_id = {r["id_sumber"]: r for r in wd}

    dipakai = []
    for p in pasangan_semua:
        if p["status"] != "cocok_otomatis":
            continue   # 'perlu_dicek' tidak digabung
        if (p["nama_osm"], p["nama_wikidata"]) in PASANGAN_DITOLAK:
            log.append({
                "jenis": "pasangan_ditolak",
                "nama": f"{p['nama_osm']} | {p['nama_wikidata']}",
                "alasan": "hasil pemeriksaan manual: bukan tempat yang sama",
                "waktu": datetime.now(timezone.utc),
            })
            continue
        if p["id_osm"] in osm_by_id and p["id_wikidata"] in wd_by_id:
            dipakai.append(p)

    print(f"Pasangan yang digabung          : {len(dipakai)}\n")

    # 3. Buat data akhir
    final = []
    id_osm_terpakai, id_wd_terpakai = set(), set()
    dilengkapi = Counter()

    for p in dipakai:
        o, w = osm_by_id[p["id_osm"]], wd_by_id[p["id_wikidata"]]
        final.append(buat_final(o, w, p))
        id_osm_terpakai.add(p["id_osm"])
        id_wd_terpakai.add(p["id_wikidata"])
        for k in FIELD_INFO:
            if kosong(o.get(k)) != kosong(w.get(k)):
                dilengkapi[k] += 1   # satu sumber kosong, yang lain terisi

    for o in osm:
        if o["id_sumber"] not in id_osm_terpakai:
            final.append(buat_final(o, None, None))
    for w in wd:
        if w["id_sumber"] not in id_wd_terpakai:
            final.append(buat_final(None, w, None))

    # 4. Simpan (hanya koleksi hasil)
    db["wisata_final"].delete_many({})
    db["wisata_final"].insert_many(final)
    db["log_enrichment"].delete_many({})
    if log:
        db["log_enrichment"].insert_many(log)

    # 5. Ringkasan
    print("=" * 60)
    print("RINGKASAN DATA AKHIR")
    print("=" * 60)
    print("Total tempat wisata unik :", len(final))
    for status, n in Counter(r["status_pencocokan"] for r in final).items():
        print(f"  {status}: {n}")

    print("\nJumlah per kategori:")
    for kat, n in Counter(r["kategori"] for r in final).most_common():
        print(f"  {kat}: {n}")

    print("\nJumlah sel TERISI per kolom (dari", len(final), "data):")
    for k in FIELD_INFO + ["lat", "lon"]:
        n = sum(1 for r in final if not kosong(r.get(k)))
        print(f"  {k:16}: {n} ({n / len(final) * 100:.0f}%)")

    print(f"\nKolom yang DILENGKAPI lewat penggabungan "
          f"(satu sumber kosong, sumber lain terisi), dari {len(dipakai)} pasangan:")
    for k in FIELD_INFO:
        print(f"  {k:16}: {dilengkapi[k]}")

    print("\nContoh data akhir hasil penggabungan (maks. 5):")
    for r in [x for x in final if x["status_pencocokan"] == "cocok"][:5]:
        print(f"  {r['nama_wisata']} | {r['kategori']} | {r['wilayah']} "
              f"| terisi {r['kolom_terisi']}/{len(FIELD_INFO)}")

    print("\nSELESAI. Koleksi baru: wisata_final, log_enrichment")


if __name__ == "__main__":
    main()