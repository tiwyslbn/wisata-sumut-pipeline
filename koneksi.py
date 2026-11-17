import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

NAMA_DB = "wisata_sumut"


def get_db():
    """Menghubungkan Python ke MongoDB Atlas dan mengembalikan database proyek."""
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise SystemExit("GAGAL: MONGODB_URI tidak ditemukan. Cek file .env")

    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    return client[NAMA_DB]