from koneksi import get_db

db = get_db()

osm = {d["id_sumber"]: d for d in db["dedup_osm"].find({}, {"_id": 0})}
wd = {d["id_sumber"]: d for d in db["dedup_wikidata"].find({}, {"_id": 0})}

pasangan = list(
    db["match_pasangan"]
    .find({}, {"_id": 0})
    .sort([("status", 1), ("skor_nama", -1)])
)


def peta(d):
    return f"https://www.google.com/maps?q={d['lat']},{d['lon']}"


for i, p in enumerate(pasangan, start=1):
    o = osm[p["id_osm"]]
    w = wd[p["id_wikidata"]]
    print(f"[{i}] {p['status']} | mirip {p['skor_nama']} | {p['jarak_meter']} m")
    print(f"    OSM : {p['nama_osm']} ({o.get('jenis_asal')})")
    print(f"          {peta(o)}")
    print(f"    WD  : {p['nama_wikidata']} ({w.get('jenis_asal')})")
    print(f"          {peta(w)}")
    print(f"          deskripsi WD: {w.get('deskripsi')}")
    print()