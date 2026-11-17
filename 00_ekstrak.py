import argparse
import csv
import io
import os
import shutil
import time
from datetime import datetime, timezone

import requests

from koneksi import get_db

# ======================================================
# PENGATURAN
# ======================================================

FOLDER_RAW = os.path.join("data", "raw")
FOLDER_BARU = os.path.join(FOLDER_RAW, "baru")
FOLDER_ARSIP = os.path.join(FOLDER_RAW, "arsip")

# email 
USER_AGENT = ("WisataSumutPipeline/1.0 (tugas kuliah MSBD, D3 Teknik Informatika USU; "
              "kontak: tiwyslbn@contoh.com)")

URL_OVERPASS = "https://overpass-api.de/api/interpreter"
URL_WIKIDATA = "https://query.wikidata.org/sparql"

OSM_QUERY = '''[out:csv(::id, ::type, name, "name:en", tourism, "addr:city", "addr:full", opening_hours, fee, charge, website, description, ::lat, ::lon; true; ",")][timeout:180];
area["name"="Sumatera Utara"]["admin_level"="4"]->.sumut;
nwr["tourism"~"attraction|museum|viewpoint|theme_park|zoo|gallery"](area.sumut);
out center;'''

WD_QUERY = '''SELECT DISTINCT ?item ?itemLabel ?itemDescription ?tipeLabel ?lokasiLabel ?coord WHERE {
  SERVICE wikibase:box {
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point(97.0 0.5)"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point(100.5 4.4)"^^geo:wktLiteral .
  }
  ?item wdt:P31 ?tipe .
  VALUES ?tipe {
    wd:Q570116 wd:Q33506 wd:Q43501 wd:Q34038 wd:Q23397
    wd:Q40080 wd:Q8502 wd:Q22698 wd:Q46169 wd:Q177380
    wd:Q839954 wd:Q4989906 wd:Q16970 wd:Q32815
  }
  OPTIONAL { ?item wdt:P131 ?lokasi . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "id,en". }
}'''

SUMBER = {
    "osm": {
        "nama": "OpenStreetMap (Overpass API)",
        "file": "osm_wisata_sumut.csv",
        "kolom": ["@id", "@type", "name", "name:en", "tourism", "addr:city", "addr:full",
                  "opening_hours", "fee", "charge", "website", "description", "@lat", "@lon"],
        "minimal": 100,   # kurang dari ini dianggap gagal
        "kunci": lambda r: f"{r['@type']}/{r['@id']}",
        "kolom_nama": "name",
    },
    "wikidata": {
        "nama": "Wikidata (SPARQL)",
        "file": "wikidata_wisata_sumut.csv",
        "kolom": ["item", "itemLabel", "itemDescription", "tipeLabel", "lokasiLabel", "coord"],
        "minimal": 500,
        "kunci": lambda r: r["item"].split("/")[-1],
        "kolom_nama": "itemLabel",
    },
}


# ======================================================
# PENGAMBILAN DATA
# ======================================================

def kirim(buat_permintaan, nama):
    """Mengirim permintaan, mengulang maksimal 3 kali kalau server sibuk."""
    jeda = [0, 20, 60]
    terakhir = "tidak diketahui"
    for ke, tunggu in enumerate(jeda, start=1):
        if tunggu:
            print(f"  menunggu {tunggu} detik sebelum mencoba lagi...")
            time.sleep(tunggu)
        try:
            r = buat_permintaan()
            if r.status_code == 200:
                return r.content
            terakhir = f"status HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except requests.RequestException as e:
            terakhir = type(e).__name__
        print(f"  percobaan {ke} gagal ({terakhir})")
    raise SystemExit(f"GAGAL mengambil data {nama}: {terakhir}")


def unduh_osm():
    return requests.post(URL_OVERPASS, data={"data": OSM_QUERY},
                         headers={"User-Agent": USER_AGENT}, timeout=240)


def unduh_wikidata():
    return requests.post(URL_WIKIDATA, data={"query": WD_QUERY},
                         headers={"User-Agent": USER_AGENT, "Accept": "text/csv"},
                         timeout=120)


# ======================================================
# PEMERIKSAAN DAN PEMBANDINGAN
# ======================================================

def baca_csv(isi):
    """Mengembalikan (daftar nama kolom, daftar baris) dari isi CSV (bytes)."""
    teks = isi.decode("utf-8-sig")
    pembaca = csv.DictReader(io.StringIO(teks, newline=""))
    return pembaca.fieldnames, list(pembaca)


def baca_lama(kode):
    path = os.path.join(FOLDER_RAW, SUMBER[kode]["file"])
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            kolom, baris = baca_csv(f.read())
        if kolom != SUMBER[kode]["kolom"]:
            return None
        return baris
    except Exception:
        return None


def periksa(kode, isi, lama):
    """Mengembalikan (baris, alasan_gagal). alasan_gagal = None kalau lolos."""
    info = SUMBER[kode]
    try:
        kolom, baris = baca_csv(isi)
    except Exception as e:
        return None, f"isi tidak bisa dibaca sebagai CSV ({type(e).__name__})"

    if kolom != info["kolom"]:
        return None, f"nama kolom tidak sesuai. Diterima: {kolom}"

    minimal = info["minimal"]
    if lama:
        minimal = max(minimal, int(len(lama) * 0.5))
    if len(baris) < minimal:
        return None, f"jumlah baris terlalu sedikit ({len(baris)} < {minimal})"

    return baris, None


def bandingkan(kode, baru, lama):
    info = SUMBER[kode]
    kunci, kolom_nama = info["kunci"], info["kolom_nama"]
    kb = {kunci(r): r.get(kolom_nama) for r in baru}
    kl = {kunci(r): r.get(kolom_nama) for r in lama}
    tambah = [(k, kb[k]) for k in kb if k not in kl]
    hilang = [(k, kl[k]) for k in kl if k not in kb]
    return tambah, hilang


# ======================================================
# PROGRAM UTAMA
# ======================================================

def main():
    parser = argparse.ArgumentParser(description="Mengambil data wisata dari OpenStreetMap dan Wikidata")
    parser.add_argument("--timpa", action="store_true",
                        help="setelah lolos pemeriksaan, arsipkan data lama lalu ganti dengan data baru")
    args = parser.parse_args()

    if "EMAIL-ANDA" in USER_AGENT:
        print("PERINGATAN: ganti EMAIL-ANDA pada USER_AGENT dengan email Anda.\n")

    os.makedirs(FOLDER_BARU, exist_ok=True)
    waktu = datetime.now(timezone.utc)

    # 1. Unduh
    isi = {}
    print("Mengunduh data OpenStreetMap (bisa 10 sampai 60 detik)...")
    isi["osm"] = kirim(unduh_osm, SUMBER["osm"]["nama"])
    time.sleep(3)
    print("Mengunduh data Wikidata (bisa 10 sampai 60 detik)...")
    isi["wikidata"] = kirim(unduh_wikidata, SUMBER["wikidata"]["nama"])

    # 2. Simpan salinan ke folder 'baru', periksa, dan bandingkan
    semua_lolos = True
    log = []
    for kode, info in SUMBER.items():
        with open(os.path.join(FOLDER_BARU, info["file"]), "wb") as f:
            f.write(isi[kode])

        lama = baca_lama(kode)
        baris, gagal = periksa(kode, isi[kode], lama)

        print("\n" + "=" * 60)
        print(info["nama"])
        print("=" * 60)

        dokumen = {"waktu": waktu, "sumber": kode, "diganti": False}
        if gagal:
            semua_lolos = False
            print("GAGAL PEMERIKSAAN:", gagal)
            dokumen.update(status="gagal", alasan=gagal)
            log.append(dokumen)
            continue

        print(f"Baris data baru : {len(baris)}")
        dokumen.update(status="lolos", jumlah_baru=len(baris))

        if lama is None:
            print("Data lama       : (tidak ada atau formatnya berbeda)")
        else:
            tambah, hilang = bandingkan(kode, baris, lama)
            print(f"Baris data lama : {len(lama)}")
            print(f"Muncul baru     : {len(tambah)}")
            print(f"Hilang          : {len(hilang)}")
            for judul, daftar in (("Contoh yang muncul baru", tambah), ("Contoh yang hilang", hilang)):
                if daftar:
                    print(f"  {judul}:")
                    for k, nama in daftar[:8]:
                        print(f"    {k}  {nama or '(tanpa nama)'}")
            dokumen.update(jumlah_lama=len(lama), muncul_baru=len(tambah), hilang=len(hilang))
        log.append(dokumen)

    # 3. Ganti data lama (hanya kalau diminta dan semuanya lolos)
    print("\n" + "=" * 60)
    if args.timpa and semua_lolos:
        os.makedirs(FOLDER_ARSIP, exist_ok=True)
        stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        for kode, info in SUMBER.items():
            tujuan = os.path.join(FOLDER_RAW, info["file"])
            if os.path.exists(tujuan):
                nama_arsip = f"{os.path.splitext(info['file'])[0]}_{stempel}.csv"
                shutil.copy2(tujuan, os.path.join(FOLDER_ARSIP, nama_arsip))
            shutil.copy2(os.path.join(FOLDER_BARU, info["file"]), tujuan)
        for d in log:
            d["diganti"] = True
        print("Data lama diarsipkan ke data/raw/arsip/ dan diganti dengan data baru.")
    elif args.timpa:
        print("TIDAK diganti karena ada sumber yang gagal pemeriksaan. Data lama tetap aman.")
    else:
        print("Mode pratinjau: data lama TIDAK diubah. Salinan baru ada di data/raw/baru/.")
        print("Untuk menggantinya, jalankan:  python 00_ekstrak.py --timpa")

    # 4. Catat ke MongoDB (kegagalan pencatatan tidak menghentikan program)
    try:
        get_db()["log_ekstrak"].insert_many(log)
        print("Tercatat di MongoDB: koleksi log_ekstrak")
    except Exception as e:
        print("Catatan ke MongoDB gagal:", type(e).__name__)

    if not semua_lolos:
        raise SystemExit(1)


if __name__ == "__main__":
    main()