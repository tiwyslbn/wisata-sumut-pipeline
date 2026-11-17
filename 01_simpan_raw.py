import os
from datetime import datetime, timezone

import pandas as pd

from koneksi import get_db

FOLDER_RAW = os.path.join("data", "raw")

DAFTAR_SUMBER = {
    "raw_osm": {
        "file": "osm_wisata_sumut.csv",
        "sumber": "OpenStreetMap (Overpass API)",
        "pemisah": ",",
    },
    "raw_wikidata": {
        "file": "wikidata_wisata_sumut.csv",
        "sumber": "Wikidata (SPARQL)",
        "pemisah": ",",
    },
}


def baca_csv(nama_file, pemisah):
    """Membaca CSV apa adanya. Semua kolom dibaca sebagai teks supaya tidak ada yang berubah."""
    path = os.path.join(FOLDER_RAW, nama_file)

    if not os.path.exists(path):
        print(f"GAGAL: file '{path}' tidak ditemukan.")
        print("File yang ada di folder data/raw:", os.listdir(FOLDER_RAW))
        raise SystemExit

    return pd.read_csv(
        path,
        sep=pemisah,
        dtype=str,              # semua kolom jadi teks
        keep_default_na=False,  # sel kosong tetap kosong (tidak diubah jadi NaN)
        encoding="utf-8-sig",   # aman untuk file dari Notepad/Excel
        on_bad_lines="warn",    # baris rusak diberi peringatan, bukan dihentikan
    )


def simpan_ke_mongodb(db, nama_koleksi, df, sumber, nama_file):
    """Memasukkan setiap baris CSV menjadi satu dokumen di MongoDB."""
    waktu_ambil = datetime.now(timezone.utc)

    dokumen = []
    for nomor, baris in enumerate(df.to_dict("records"), start=1):
        baris["_meta"] = {
            "sumber": sumber,
            "file_asal": nama_file,
            "nomor_baris": nomor,
            "waktu_simpan": waktu_ambil,
        }
        dokumen.append(baris)

    db[nama_koleksi].delete_many({})
    db[nama_koleksi].insert_many(dokumen)
    return len(dokumen)


def main():
    db = get_db()
    print("Terhubung ke database:", db.name)
    print("-" * 50)

    for nama_koleksi, info in DAFTAR_SUMBER.items():
        df = baca_csv(info["file"], info["pemisah"])

        print(f"File      : {info['file']}")
        print(f"Baris     : {len(df)}")
        print(f"Kolom     : {list(df.columns)}")

        jumlah = simpan_ke_mongodb(
            db, nama_koleksi, df, info["sumber"], info["file"]
        )
        print(f"Tersimpan : {jumlah} dokumen ke koleksi '{nama_koleksi}'")
        print("-" * 50)

    print("SELESAI. Cek hasilnya di MongoDB Compass.")


if __name__ == "__main__":
    main()