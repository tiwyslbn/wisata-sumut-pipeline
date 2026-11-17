# Perancangan Data Pipeline Untuk Integrasi Dan Pembersihan Data Tempat Wisata di Sumatera Utara Menggunakan Python Dan MongoDB

# Kelompok 1

- 241712001 Tiwy Lamberkat Silaban
- 241712003 Sultan Tri Ananda
- 241712018 Dimas Surya Darma
- 241712024 Adeptri Sagala
- 241712031 Visela Benedicta Simarmata

## Deskripsi

Pipeline data yang mengumpulkan data tempat wisata Sumatera Utara dari dua
sumber terbuka (OpenStreetMap dan Wikidata), membersihkan, mencocokkan, dan
menggabungkannya, lalu menyimpannya ke MongoDB Atlas.

## Sumber data

| Sumber        | Alat                                       | Berkas                             |
| ------------- | ------------------------------------------ | ---------------------------------- |
| OpenStreetMap | Overpass Turbo (https://overpass-turbo.eu) | data/raw/osm_wisata_sumut.csv      |
| Wikidata      | Query Service (https://query.wikidata.org) | data/raw/wikidata_wisata_sumut.csv |

## Teknologi

Python, pandas, PyMongo, python-dotenv, MongoDB Atlas, MongoDB Compass.

## Cara menjalankan

1. Pasang library: `pip install -r requirements.txt`
2. Buat berkas `.env` berisi: `MONGODB_URI=<alamat koneksi MongoDB Atlas>`
3. Jalankan: `python jalankan_semua.py`

## Alur

| Berkas              | Fungsi                                      |
| ------------------- | ------------------------------------------- |
| koneksi.py          | Koneksi ke MongoDB                          |
| 01_simpan_raw.py    | Menyimpan data mentah                       |
| 02_profil_raw.py    | Memeriksa kondisi data mentah               |
| 03_cleaning.py      | Cleaning dan penyeragaman                   |
| 04_deduplikasi.py   | Menggabungkan data kembar dalam satu sumber |
| 05_matching.py      | Mencocokkan tempat yang sama antar sumber   |
| 06_enrichment.py    | Menggabungkan informasi dua sumber          |
| 07_finalisasi.py    | Membuang non-wisata, menentukan kategori    |
| 08_gabung_manual.py | Penggabungan hasil pemeriksaan manual       |
| 09_kualitas.py      | Laporan kualitas data                       |

## Hasil

2.061 data mentah menjadi 246 tempat wisata. Hasil ada di koleksi
`hasil_akhir` dan berkas `output/wisata_sumut_final.csv`.

## Keterbatasan

- Alamat, harga tiket, dan jam operasional hampir kosong karena sumber
  tidak mencatatnya.
- Kategori sebagian ditentukan dari kata kunci pada nama.
- Wilayah belum seragam (campuran kabupaten, kota, dan kecamatan).
- Pencocokan diperiksa manual, bukan terhadap data acuan lengkap.

## Atribusi data

Data tempat wisata bersumber dari OpenStreetMap (c) OpenStreetMap contributors, lisensi ODbL,
dan dari Wikidata (lisensi CC0). Data diambil pada 12 November 2026.
