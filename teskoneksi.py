import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
uri = os.getenv("MONGODB_URI")

if not uri:
    print("GAGAL: MONGODB_URI tidak ditemukan. Cek file .env")
    raise SystemExit

client = MongoClient(uri, serverSelectionTimeoutMS=8000)
client.admin.command("ping")
print("KONEKSI BERHASIL ke MongoDB Atlas")

try:
    print("Database yang ada:", client.list_database_names())
except Exception as e:
    print("Daftar database tidak bisa dibaca, tapi koneksi tetap berhasil.")