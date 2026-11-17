from koneksi import get_db

db = get_db()

data = db["raw_wikidata"].find(
    {"tipeLabel": {"$in": ["masjid", "gereja"]}},
    {"_id": 0, "itemLabel": 1, "tipeLabel": 1, "lokasiLabel": 1},
)

sudah = set()
for d in sorted(data, key=lambda x: x["itemLabel"]):
    if d["itemLabel"] in sudah:
        continue
    sudah.add(d["itemLabel"])
    print(f"{d['tipeLabel']:8} | {d['itemLabel']}  ({d['lokasiLabel'] or '-'})")

print("\nJumlah nama unik:", len(sudah))