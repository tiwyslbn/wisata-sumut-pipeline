import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg2
import streamlit as st
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# ======================================================
# PENGATURAN
# ======================================================
WIB = timezone(timedelta(hours=7))
NAMA_DB = "wisata_sumut"
SEGAR_DETIK = 30      # dashboard menyegarkan diri tiap sekian detik
TTL = 20              # hasil kueri disimpan sementara sekian detik

ALUR = [  # (label diawali angka agar urutan grafik benar, koleksi MongoDB)
    ("1 Mentah OSM", "raw_osm"), ("2 Mentah Wikidata", "raw_wikidata"),
    ("3 Cleaning OSM", "clean_osm"), ("4 Cleaning Wikidata", "clean_wikidata"),
    ("5 Dedup OSM", "dedup_osm"), ("6 Dedup Wikidata", "dedup_wikidata"),
    ("7 Gabungan 2 sumber", "wisata_final"), ("8 Finalisasi", "wisata_akhir"),
    ("9 Hasil akhir", "hasil_akhir"),
]
KOLOM_INFO = {
    "Nama Inggris": "nama_en", "Wilayah": "wilayah", "Alamat": "alamat",
    "Deskripsi": "deskripsi", "Harga tiket": "harga_tiket",
    "Jam operasional": "jam_operasional", "Website": "website",
}
LABEL_STATUS = {
    "cocok": "Ada di 2 sumber",
    "hanya_osm": "Hanya OpenStreetMap",
    "hanya_wikidata": "Hanya Wikidata",
}
LABEL_KONSISTENSI = {
    "kategori_tidak_valid": "Kategori tidak valid",
    "koordinat_bermasalah": "Koordinat bermasalah",
    "nama_muncul_lebih_dari_sekali": "Nama muncul lebih dari sekali",
    "nama_mirip_komentar": "Nama mirip kalimat/komentar",
    "nama_spasi_berlebih": "Nama dengan spasi berlebih",
    "catatan_kualitas": "Data bercatatan kualitas",
}
LABEL_PENCOCOKAN = {
    "diusulkan_otomatis": "Pasangan diusulkan program",
    "ditolak_manual": "Ditolak setelah pemeriksaan manual",
    "perlu_dicek": "Perlu dicek (tidak digabung)",
    "ada_di_kedua_sumber": "Tempat yang ada di kedua sumber",
}

SQL_TEMPAT = """
SELECT t.id, t.nama_wisata, t.nama_en, k.nama AS kategori, t.wilayah, t.alamat,
       t.deskripsi, t.harga_tiket, t.jam_operasional, t.website, t.lat, t.lon,
       t.status_pencocokan, array_to_string(t.sumber, ', ') AS sumber,
       t.kolom_terisi, t.dimuat_pada
FROM wisata_sumut.tempat_wisata t
JOIN wisata_sumut.kategori k ON k.id = t.kategori_id
ORDER BY t.nama_wisata
"""

st.set_page_config(page_title="Dashboard Wisata Sumatera Utara",
                   page_icon="🗺️", layout="wide")


# ======================================================
# KONEKSI DAN PENGAMBILAN DATA
# ======================================================
def secret(nama):
    """Kata sandi dari st.secrets (saat deploy) atau dari .env (saat lokal)."""
    try:
        if nama in st.secrets:
            return st.secrets[nama]
    except Exception:
        pass
    return os.getenv(nama)


@st.cache_data(ttl=TTL, show_spinner=False)
def pg_query(sql):
    uri = secret("POSTGRES_URI")
    if not uri:
        raise ValueError("POSTGRES_URI belum diatur")
    conn = psycopg2.connect(uri, connect_timeout=15)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            kolom = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=kolom)
    finally:
        conn.close()


@st.cache_resource
def mongo_db():
    uri = secret("MONGODB_URI")
    if not uri:
        raise ValueError("MONGODB_URI belum diatur")
    return MongoClient(uri, serverSelectionTimeoutMS=8000)[NAMA_DB]


@st.cache_data(ttl=TTL, show_spinner=False)
def mongo_runs(n=10):
    return list(mongo_db()["log_pipeline"].find({}, {"_id": 0}).sort("mulai", -1).limit(n))


@st.cache_data(ttl=TTL, show_spinner=False)
def mongo_alur():
    db = mongo_db()
    return {label: db[koleksi].count_documents({}) for label, koleksi in ALUR}


@st.cache_data(ttl=TTL, show_spinner=False)
def mongo_kualitas():
    return mongo_db()["laporan_kualitas"].find_one({}, {"_id": 0})


@st.cache_data(ttl=TTL, show_spinner=False)
def mongo_ekstrak(n=6):
    return list(mongo_db()["log_ekstrak"].find({}, {"_id": 0}).sort("waktu", -1).limit(n))


# ======================================================
# BANTUAN TAMPILAN
# ======================================================
def ke_wib(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(WIB)


def fmt(dt):
    d = ke_wib(dt)
    return d.strftime("%d/%m/%Y %H:%M:%S") if d else "-"


def lalu(dt):
    d = ke_wib(dt)
    if not d:
        return "-"
    detik = int((datetime.now(WIB) - d).total_seconds())
    if detik < 60:
        return f"{detik} detik lalu"
    if detik < 3600:
        return f"{detik // 60} menit lalu"
    if detik < 86400:
        return f"{detik // 3600} jam lalu"
    return f"{detik // 86400} hari lalu"


def tabel_runs(runs):
    baris = []
    for r in runs:
        j = r.get("jumlah") or {}
        baris.append({
            "Mulai (WIB)": fmt(r.get("mulai")),
            "Mode": r.get("mode"),
            "Pemicu": r.get("pemicu"),
            "Status": r.get("status"),
            "Durasi (detik)": r.get("durasi_detik"),
            "Data MongoDB": j.get("mongo_hasil_akhir"),
            "Data PostgreSQL": j.get("postgres_tempat_wisata"),
            "Konsisten": j.get("konsisten"),
            "Run ID": r.get("run_id"),
        })
    return pd.DataFrame(baris)


# ======================================================
# HALAMAN UTAMA (menyegarkan diri otomatis)
# ======================================================
@st.fragment(run_every=f"{SEGAR_DETIK}s")
def dashboard():
    atas_kiri, atas_kanan = st.columns([4, 1])
    atas_kiri.caption(
        f"Terakhir diperbarui: {datetime.now(WIB).strftime('%H:%M:%S')} WIB  |  "
        f"menyegarkan otomatis tiap {SEGAR_DETIK} detik"
    )
    if atas_kanan.button("Segarkan sekarang"):
        st.cache_data.clear()

    # ---- Ambil data dari dua database ----
    df, runs, kual = None, [], None
    try:
        df = pg_query(SQL_TEMPAT)
    except Exception as e:
        st.error(f"PostgreSQL tidak dapat diakses ({type(e).__name__}).")
    try:
        runs = mongo_runs()
        kual = mongo_kualitas()
    except Exception as e:
        st.error(f"MongoDB tidak dapat diakses ({type(e).__name__}).")

    # ---- Angka utama ----
    k1, k2, k3, k4 = st.columns(4)
    if df is not None:
        k1.metric("Total tempat wisata", len(df))
        k2.metric("Jumlah kategori", df["kategori"].nunique())
    if kual:
        k3.metric("Kelengkapan informasi",
                  f"{kual.get('kelengkapan_keseluruhan_persen', 0)}%")
    if runs:
        k4.metric("Pipeline terakhir", str(runs[0].get("status", "-")).upper())
        k4.caption(f"{lalu(runs[0].get('mulai'))}  |  "
                   f"{runs[0].get('durasi_detik') or 0:.0f} detik")
    if df is not None and len(df):
        st.caption(f"Data di PostgreSQL terakhir dimuat: {fmt(df['dimuat_pada'].max())} WIB")

    tampilan = st.radio("Tampilan", ["Ringkasan", "Peta dan Data", "Pipeline", "Kualitas Data"],
                        horizontal=True, key="tampilan", label_visibility="collapsed")

    # ================= RINGKASAN =================
    if tampilan == "Ringkasan" and df is not None:
        a, b = st.columns(2)
        with a:
            st.subheader("Jumlah tempat wisata per kategori")
            st.bar_chart(df["kategori"].value_counts())
        with b:
            st.subheader("Asal data tempat wisata")
            st.bar_chart(df["status_pencocokan"].map(LABEL_STATUS).value_counts())

        c, d = st.columns(2)
        with c:
            st.subheader("10 wilayah dengan tempat wisata terbanyak")
            wil = df["wilayah"].dropna().value_counts().head(10)
            st.bar_chart(wil)
            st.caption(f"Kolom wilayah hanya terisi pada {df['wilayah'].notna().sum()} "
                       f"dari {len(df)} data karena keterbatasan sumber.")
        with d:
            st.subheader("Alur jumlah data (MongoDB)")
            try:
                st.bar_chart(pd.Series(mongo_alur()))
                st.caption("Dari data mentah hingga hasil akhir tiap tahap pipeline.")
            except Exception as e:
                st.error(f"MongoDB tidak dapat diakses ({type(e).__name__}).")

    # ================= PETA DAN DATA =================
    elif tampilan == "Peta dan Data" and df is not None:
        semua_kat = sorted(df["kategori"].unique())
        semua_status = list(LABEL_STATUS.values())
        f1, f2, f3 = st.columns(3)
        pilih_kat = f1.multiselect("Kategori", semua_kat, default=semua_kat, key="f_kat")
        pilih_status = f2.multiselect("Asal data", semua_status, default=semua_status, key="f_status")
        cari = f3.text_input("Cari nama tempat", key="f_cari")

        d = df[df["kategori"].isin(pilih_kat)]
        d = d[d["status_pencocokan"].map(LABEL_STATUS).isin(pilih_status)]
        if cari:
            d = d[d["nama_wisata"].str.contains(cari, case=False, na=False, regex=False)]

        st.write(f"Menampilkan **{len(d)}** dari {len(df)} tempat wisata")
        if len(d):
            st.map(d[["lat", "lon"]])
            tampil = d[["nama_wisata", "kategori", "wilayah", "deskripsi",
                        "jam_operasional", "website", "sumber"]].rename(columns={
                "nama_wisata": "Nama", "kategori": "Kategori", "wilayah": "Wilayah",
                "deskripsi": "Deskripsi", "jam_operasional": "Jam operasional",
                "website": "Website", "sumber": "Sumber"})
            st.dataframe(tampil, hide_index=True)
        else:
            st.info("Tidak ada data yang cocok dengan filter.")

    # ================= PIPELINE =================
    elif tampilan == "Pipeline":
        if not runs:
            st.info("Belum ada catatan eksekusi pipeline. Jalankan python pipeline.py.")
        else:
            st.subheader("Riwayat eksekusi pipeline (MongoDB)")
            st.dataframe(tabel_runs(runs), hide_index=True)

            terakhir = runs[0]
            st.subheader(f"Langkah eksekusi terakhir (run {terakhir.get('run_id')}, "
                         f"status {terakhir.get('status')})")
            langkah = terakhir.get("langkah") or []
            if langkah:
                dl = pd.DataFrame(langkah)[["berkas", "keterangan", "status", "detik"]]
                dl.columns = ["Berkas", "Keterangan", "Status", "Detik"]
                st.dataframe(dl, hide_index=True)
                st.bar_chart(dl.set_index("Berkas")["Detik"])
            if terakhir.get("gagal_di"):
                st.warning(f"Berhenti di: {terakhir['gagal_di']}")

        try:
            eks = mongo_ekstrak()
            if eks:
                st.subheader("Pengambilan data terakhir dari sumber (log_ekstrak)")
                de = pd.DataFrame([{
                    "Waktu (WIB)": fmt(e.get("waktu")), "Sumber": e.get("sumber"),
                    "Status": e.get("status"), "Baris baru": e.get("jumlah_baru"),
                    "Muncul baru": e.get("muncul_baru"), "Hilang": e.get("hilang"),
                    "Data diganti": e.get("diganti"),
                } for e in eks])
                st.dataframe(de, hide_index=True)
        except Exception:
            pass

    # ================= KUALITAS DATA =================
    elif tampilan == "Kualitas Data":
        if df is not None:
            st.subheader("Kelengkapan per kolom (dihitung dari PostgreSQL)")
            lengkap = pd.Series({
                label: round(df[kol].notna().mean() * 100, 1)
                for label, kol in KOLOM_INFO.items()
            })
            st.bar_chart(lengkap)
            st.caption("Persentase data yang kolomnya terisi. Alamat, harga tiket, dan jam "
                       "operasional rendah karena sumber tidak mencatatnya.")
        if kual:
            st.subheader("Laporan kualitas data (MongoDB)")
            st.caption(f"Dibuat: {fmt(kual.get('waktu'))} WIB")
            x, y = st.columns(2)
            with x:
                st.markdown("**Konsistensi**")
                kons = kual.get("konsistensi", {})
                st.dataframe(pd.DataFrame(
                    [(LABEL_KONSISTENSI.get(k, k), v) for k, v in kons.items()],
                    columns=["Pemeriksaan", "Jumlah"]), hide_index=True)
            with y:
                st.markdown("**Pencocokan dua sumber**")
                cocok = kual.get("pencocokan", {})
                st.dataframe(pd.DataFrame(
                    [(LABEL_PENCOCOKAN[k], cocok.get(k)) for k in LABEL_PENCOCOKAN],
                    columns=["Pemeriksaan", "Jumlah"]), hide_index=True)
            st.caption("Hasil pencocokan berdasarkan pemeriksaan manual, bukan akurasi "
                       "terhadap data acuan lengkap.")

    st.divider()
    st.caption("Sumber data: OpenStreetMap dan Wikidata. Data tempat wisata disimpan di "
               "PostgreSQL (Supabase). Data mentah, log pipeline, dan laporan kualitas "
               "disimpan di MongoDB Atlas.")


st.title("Dashboard Data Tempat Wisata Sumatera Utara")
st.caption("Proyek MSBD: arsitektur database hybrid (MongoDB + PostgreSQL) dengan pipeline ETL otomatis")
dashboard()