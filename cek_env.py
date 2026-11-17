from dotenv import dotenv_values, find_dotenv

path = find_dotenv(usecwd=True)
print("Berkas .env yang dibaca:", path or "(tidak ditemukan)")

nilai = dotenv_values(path) if path else {}
print("Nama variabel di dalamnya:", list(nilai.keys()))

for nama in ("MONGODB_URI", "POSTGRES_URI"):
    v = nilai.get(nama)
    print(f"{nama}: " + (f"TERISI ({len(v)} karakter)" if v else "KOSONG atau TIDAK ADA"))