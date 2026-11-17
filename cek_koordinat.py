from koneksi import get_db

db = get_db()

print("15 baris pertama dari raw_osm (nama, @lat, @lon):\n")
data = db["raw_osm"].find({}, {"_id": 0, "name": 1, "@lat": 1, "@lon": 1}).limit(15)

for d in data:
    print(repr(d.get("name")), "|", repr(d.get("@lat")), "|", repr(d.get("@lon")))