from collections import Counter

from koneksi import get_db

db = get_db()
data = list(db["wisata_final"].find({}, {"_id": 0}))

# ---- 1. Isi kategori 'Lainnya' ----
lain = [d for d in data if d["kategori"] == "Lainnya"]
print(f"Jumlah kategori 'Lainnya': {len(lain)} dari {len(data)}\n")

print("Jenis asal (OSM) pada kategori 'Lainnya':")
for jenis, n in Counter(d.get("jenis_osm") for d in lain).most_common():
    print(f"  {jenis}: {n}")

print("\nNama tempat pada kategori 'Lainnya':")
for d in sorted(lain, key=lambda x: x["nama_wisata"].lower()):
    print(f"  {d['nama_wisata']}")

# ---- 2. Isi kolom wilayah ----
print("\n" + "=" * 60)
print("Nilai kolom 'wilayah' (yang terisi):")
for w, n in Counter(d["wilayah"] for d in data if d.get("wilayah")).most_common():
    print(f"  {w}: {n}")