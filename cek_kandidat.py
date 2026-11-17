from koneksi import get_db

db = get_db()
data = list(db["wisata_akhir"].find({}, {"_id": 0}))

by_name = {}
for d in data:
    by_name.setdefault(d["nama_wisata"], []).append(d)


def link(d):
    return f"https://www.google.com/maps?q={d['lat']},{d['lon']}"


PASANGAN = [
    ("Museum Uang Sumatra", "Museum Juang 45 Sumatera Utara"),
    ("Museum Simalungun", "Simalungun"),
    ("Museum Huta Bolon Simanindo", "Bolon Simanindo"),
    ("Alam Sibayak Hot Spring", "Alam Sibayak"),
    ("Pariban Hotspring", "Daunparis Hot Spring"),
    ("Hot Spring", "Anugrah Sibayak Hot Spring"),
    ("Alam Sibayak Hot Spring", "Anugrah Sibayak Hot Spring"),
    ("Museum Zoologi", "Museum Zoologi Pematang Siantar"),
    ("Tumöri Tourist Village",
     "Tumöri Tourist Village with several traditional North Nias houses"),
    ("Hot Spring", "Alam Sibayak Hot Spring"),
]

print("KANDIDAT DUPLIKAT\n")
for i, (a, b) in enumerate(PASANGAN, start=1):
    print(f"[{i}]")
    for nama in (a, b):
        if nama not in by_name:
            print(f"   (nama '{nama}' tidak ditemukan)")
            continue
        for d in by_name[nama]:
            jenis = d.get("jenis_osm") or d.get("jenis_wikidata")
            print(f"   {nama}")
            print(f"      sumber: {', '.join(d.get('sumber', []))} | jenis: {jenis}")
            print(f"      {link(d)}")
    print()

print("=" * 60)
print("WILAYAH MENCURIGAKAN\n")
for d in data:
    if d.get("catatan_kualitas"):
        print(f"   {d['nama_wisata']}")
        print(f"      wilayah di Wikidata: {d.get('wilayah_asli')}")
        print(f"      deskripsi: {d.get('deskripsi')}")
        print(f"      koordinat: {d['lat']}, {d['lon']}")
        print(f"      {link(d)}\n")