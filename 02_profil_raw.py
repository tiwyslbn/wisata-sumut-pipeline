import pandas as pd

from koneksi import get_db


def muat(db, nama_koleksi):
    """Mengambil data dari MongoDB menjadi tabel pandas (tanpa _id dan _meta)."""
    data = list(db[nama_koleksi].find({}, {"_id": 0, "_meta": 0}))
    return pd.DataFrame(data)


def hitung_kosong(df):
    """Menghitung jumlah sel kosong (teks kosong atau hanya spasi) di tiap kolom."""
    teks = df.astype(str).apply(lambda kolom: kolom.str.strip())
    return (teks == "").sum()


def tampilkan_umum(df, judul):
    print("=" * 60)
    print(judul)
    print("=" * 60)
    print("Jumlah baris  :", len(df))
    print("Nama kolom    :", list(df.columns))
    print("Baris kembar persis (semua kolom sama):", df.duplicated().sum())
    print("\nJumlah sel kosong per kolom:")
    print(hitung_kosong(df).to_string())


def profil_osm(df):
    tampilkan_umum(df, "RAW OSM (OpenStreetMap)")

    if "@id" in df.columns:
        print("\nJumlah @id unik:", df["@id"].nunique())

    if "tourism" in df.columns:
        print("\nJenis wisata (kolom tourism):")
        print(df["tourism"].value_counts().to_string())

    if "name" in df.columns:
        nama = df["name"].astype(str).str.strip()
        nama_isi = nama[nama != ""]
        print("\nBaris yang punya nama :", len(nama_isi))
        print("Baris tanpa nama      :", len(nama) - len(nama_isi))
        kembar = nama_isi.str.lower().duplicated().sum()
        print("Nama kembar (abaikan huruf besar/kecil):", kembar)
        print("\nContoh 10 nama pertama:")
        print(nama_isi.head(10).to_string(index=False))


def profil_wikidata(df):
    tampilkan_umum(df, "RAW WIKIDATA")

    if "item" in df.columns:
        print("\nJumlah item unik (tempat berbeda):", df["item"].nunique())
        print("Artinya ada", len(df) - df["item"].nunique(),
              "baris pengulangan.")

    if "tipeLabel" in df.columns:
        print("\nJenis tempat (kolom tipeLabel):")
        print(df["tipeLabel"].value_counts().head(15).to_string())

    if "lokasiLabel" in df.columns:
        print("\n15 nilai terbanyak di kolom lokasiLabel:")
        print(df["lokasiLabel"].value_counts().head(15).to_string())

        luar = df["lokasiLabel"].astype(str).str.contains(
            "Aceh|Riau|Sumatera Barat|Jambi", case=False, regex=True
        )
        print("\nBaris yang lokasinya menyebut Aceh/Riau/Sumbar/Jambi:",
              int(luar.sum()))


def main():
    db = get_db()
    print("Terhubung ke database:", db.name, "\n")

    profil_osm(muat(db, "raw_osm"))
    print("\n")
    profil_wikidata(muat(db, "raw_wikidata"))



if __name__ == "__main__":
    main()