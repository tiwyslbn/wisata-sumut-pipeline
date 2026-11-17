import subprocess
import sys
import time

LANGKAH = [
    ("01_simpan_raw.py", "Menyimpan data mentah ke MongoDB"),
    ("02_profil_raw.py", "Memeriksa kondisi data mentah"),
    ("03_cleaning.py", "Cleaning"),
    ("04_deduplikasi.py", "Deduplikasi"),
    ("05_matching.py", "Pencocokan dua sumber"),
    ("06_enrichment.py", "Penggabungan dan pengayaan"),
    ("07_finalisasi.py", "Finalisasi"),
    ("08_gabung_manual.py", "Penggabungan manual"),
    ("09_kualitas.py", "Pemeriksaan kualitas data"),
]

mulai = time.time()
for nomor, (berkas, keterangan) in enumerate(LANGKAH, start=1):
    print("\n" + "#" * 60)
    print(f"# LANGKAH {nomor} dari {len(LANGKAH)}: {keterangan}  ({berkas})")
    print("#" * 60)

    hasil = subprocess.run([sys.executable, berkas])
    if hasil.returncode != 0:
        print(f"\nBERHENTI: {berkas} gagal (kode {hasil.returncode}).")
        print("Perbaiki error di atas, lalu jalankan ulang.")
        raise SystemExit(1)

print("\n" + "=" * 60)
print(f"SEMUA LANGKAH SELESAI dalam {time.time() - mulai:.0f} detik.")
print("=" * 60)