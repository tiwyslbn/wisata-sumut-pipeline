import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()
uri = os.getenv("POSTGRES_URI")

if not uri:
    raise SystemExit("GAGAL: POSTGRES_URI tidak ditemukan. Cek file .env")

# 1. Coba terhubung (maksimal menunggu 15 detik)
try:
    conn = psycopg2.connect(uri, connect_timeout=15)
except Exception as e:
    print("GAGAL terhubung:", type(e).__name__)
    print(str(e).splitlines()[0])
    raise SystemExit(1)

cur = conn.cursor()
cur.execute("select current_database(), current_user, split_part(version(), ' on ', 1)")
print("TERHUBUNG ke PostgreSQL:", cur.fetchone())

# 2. Siapkan skema proyek dan tes tulis-baca (tabel sementara dihapus lagi)
cur.execute("create schema if not exists wisata_sumut")
cur.execute("drop table if exists wisata_sumut._tes")
cur.execute("create table wisata_sumut._tes (id int primary key, catatan text)")
cur.execute("insert into wisata_sumut._tes values (1, 'tes tulis')")
cur.execute("select * from wisata_sumut._tes")
print("Tes tulis dan baca:", cur.fetchall())
cur.execute("drop table wisata_sumut._tes")

conn.commit()
print("SELESAI. Skema 'wisata_sumut' siap dipakai.")
cur.close()
conn.close()