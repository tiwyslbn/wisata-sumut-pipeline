import html
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
URL_REPO = "https://github.com/tiwyslbn/wisata-sumut-pipeline"

WARNA_KATEGORI = {
    "Wisata Alam": "#16A34A",
    "Wisata Budaya & Sejarah": "#D97706",
    "Wisata Buatan & Edukasi": "#2563EB",
    "Wisata Religi": "#7C3AED",
    "Lainnya": "#94A3B8",
}
LABEL_STATUS = {
    "cocok": "Ada di 2 sumber",
    "hanya_osm": "Hanya OpenStreetMap",
    "hanya_wikidata": "Hanya Wikidata",
}
WARNA_ASAL = {
    "Ada di 2 sumber": "#0F766E",
    "Hanya OpenStreetMap": "#3B82F6",
    "Hanya Wikidata": "#F59E0B",
}
WARNA_SUMBER = {"OpenStreetMap": "#3B82F6", "Wikidata": "#F59E0B", "Gabungan": "#0F766E"}
WARNA_STATUS = {"berhasil": "#16A34A", "gagal": "#DC2626", "berjalan": "#F59E0B",
                "dibatalkan": "#64748B"}

ALUR = [  # (label, koleksi MongoDB)
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
TAMPILAN = ["📊 Ringkasan", "🗺️ Peta dan Data", "⚙️ Pipeline", "✅ Kualitas Data"]

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
                   page_icon="🗺️", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1280px;}
footer {visibility: hidden;}
.hero {
  background: linear-gradient(135deg, #0F766E 0%, #15803D 55%, #4D7C0F 100%);
  border-radius: 20px; padding: 28px 32px; margin-bottom: 18px; color: #fff;
  box-shadow: 0 8px 24px rgba(15, 118, 110, .25);
}
.hero-atas {font-size: .78rem; letter-spacing: .14em; opacity: .85; font-weight: 600;}
.hero-judul {font-size: 2.3rem; font-weight: 800; line-height: 1.15; margin: 6px 0 8px 0;}
.hero-sub {font-size: 1rem; opacity: .92; max-width: 760px;}
.chip {
  display: inline-block; background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.35);
  border-radius: 999px; padding: 5px 14px; margin: 14px 8px 0 0; font-size: .82rem; font-weight: 600;
}
.kpi {
  background: #fff; border: 1px solid #E2E8F0; border-top: 5px solid var(--warna);
  border-radius: 16px; padding: 16px 18px; box-shadow: 0 1px 3px rgba(15,23,42,.06); height: 100%;
}
.kpi-judul {font-size: .74rem; color: #64748B; text-transform: uppercase; letter-spacing: .06em; font-weight: 700;}
.kpi-nilai {font-size: 2.2rem; font-weight: 800; color: #0F172A; line-height: 1.15; margin-top: 4px;}
.kpi-ket {font-size: .82rem; color: #64748B; margin-top: 2px;}
.catatan {font-size: .82rem; color: #64748B;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


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


def bersihkan_uri(nilai, nama):
    """Merapikan kesalahan tempel yang umum: spasi, tanda kutip, dan awalan 'NAMA='."""
    if not nilai:
        return None
    v = str(nilai).strip()
    if v.upper().startswith(nama.upper() + "="):
        v = v.split("=", 1)[1].strip()
    return v.strip('"').strip("'").strip()


@st.cache_data(ttl=TTL, show_spinner=False)
def pg_query(sql):
    uri = bersihkan_uri(secret("POSTGRES_URI"), "POSTGRES_URI")
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
    uri = bersihkan_uri(secret("MONGODB_URI"), "MONGODB_URI")
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
        return f"{max(detik, 0)} detik lalu"
    if detik < 3600:
        return f"{detik // 60} menit lalu"
    if detik < 86400:
        return f"{detik // 3600} jam lalu"
    return f"{detik // 86400} hari lalu"


def kartu(ikon, judul, nilai, ket, warna):
    return (f'<div class="kpi" style="--warna:{warna}">'
            f'<div class="kpi-judul">{ikon} {html.escape(judul)}</div>'
            f'<div class="kpi-nilai">{html.escape(str(nilai))}</div>'
            f'<div class="kpi-ket">{html.escape(ket)}</div></div>')


def tampil_plotly(fig, tinggi=None):
    """Menampilkan grafik Plotly dengan gaya seragam (tahan beda versi Streamlit)."""
    fig.update_layout(
        template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Segoe UI, Inter, sans-serif", size=13, color="#0F172A"),
        margin=dict(l=8, r=8, t=8, b=8),
    )
    if tinggi:
        fig.update_layout(height=tinggi)
    try:
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    except Exception:
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def tampil_tabel(df, **kw):
    try:
        st.dataframe(df, hide_index=True, width="stretch", **kw)
    except Exception:
        st.dataframe(df, hide_index=True, use_container_width=True, **kw)


def bingkai():
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def pilih_tampilan():
    if hasattr(st, "segmented_control"):
        pilihan = st.segmented_control("Tampilan", TAMPILAN, default=TAMPILAN[0],
                                       key="tampilan", label_visibility="collapsed")
    else:
        pilihan = st.radio("Tampilan", TAMPILAN, horizontal=True, key="tampilan",
                           label_visibility="collapsed")
    return pilihan or TAMPILAN[0]


def tombol_segarkan():
    try:
        return st.button("🔄 Segarkan", width="stretch")
    except Exception:
        return st.button("🔄 Segarkan")


def bar_horizontal(label, nilai, warna, teks=None, rentang_x=None):
    fig = go.Figure(go.Bar(
        x=list(nilai), y=list(label), orientation="h",
        marker=dict(color=warna), text=teks or list(nilai), textposition="outside",
        cliponaxis=False, hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=True, gridcolor="#E2E8F0", zeroline=False)
    if rentang_x:
        fig.update_xaxes(range=rentang_x)
    return fig


# ======================================================
# HALAMAN UTAMA (menyegarkan diri otomatis)
# ======================================================
@st.fragment(run_every=f"{SEGAR_DETIK}s")
def dashboard():
    # ---- Ambil data dari dua database ----
    df, runs, kual = None, [], None
    galat = []
    try:
        df = pg_query(SQL_TEMPAT)
    except Exception as e:
        galat.append(f"PostgreSQL tidak dapat diakses ({type(e).__name__}).")
    try:
        runs = mongo_runs()
        kual = mongo_kualitas()
    except Exception as e:
        galat.append(f"MongoDB tidak dapat diakses ({type(e).__name__}).")

    terakhir = runs[0] if runs else None
    status = str(terakhir.get("status", "-")) if terakhir else "-"
    warna_status = WARNA_STATUS.get(status, "#64748B")

    # ---- Spanduk judul ----
    chip_pipeline = (f'<span class="chip">⚙️ Pipeline: {html.escape(status.upper())}'
                     f' · {html.escape(lalu(terakhir.get("mulai")))}</span>') if terakhir else ""
    st.markdown(
        '<div class="hero">'
        '<div class="hero-atas">PROYEK MSBD · DATA PIPELINE · MONGODB + POSTGRESQL</div>'
        '<div class="hero-judul">🗺️ Wisata Sumatera Utara</div>'
        '<div class="hero-sub">Data tempat wisata dari OpenStreetMap dan Wikidata yang '
        'dibersihkan, dicocokkan, dan digabung oleh pipeline ETL otomatis.</div>'
        f'<span class="chip">🕒 Diperbarui {datetime.now(WIB).strftime("%H:%M:%S")} WIB</span>'
        f'<span class="chip">🔄 Segar otomatis tiap {SEGAR_DETIK} detik</span>'
        f'{chip_pipeline}</div>',
        unsafe_allow_html=True,
    )
    for pesan in galat:
        st.error(pesan)

    # ---- Kartu angka utama ----
    total = len(df) if df is not None else "-"
    n_kat = df["kategori"].nunique() if df is not None else "-"
    n_cocok = int((df["status_pencocokan"] == "cocok").sum()) if df is not None else "-"
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kartu("📍", "Tempat wisata", total, f"{n_kat} kategori", "#0F766E"),
                unsafe_allow_html=True)
    k2.markdown(kartu("🔗", "Ada di dua sumber", n_cocok,
                      "tergabung dari OSM dan Wikidata", "#3B82F6"), unsafe_allow_html=True)
    lengkap = f"{kual.get('kelengkapan_keseluruhan_persen', 0)}%" if kual else "-"
    k3.markdown(kartu("🧩", "Kelengkapan informasi", lengkap,
                      "rata-rata tujuh kolom informasi", "#F59E0B"), unsafe_allow_html=True)
    if terakhir:
        ket = f"{lalu(terakhir.get('mulai'))} · {terakhir.get('durasi_detik') or 0:.0f} detik"
        k4.markdown(kartu("⚙️", "Pipeline terakhir", status.upper(), ket, warna_status),
                    unsafe_allow_html=True)
    else:
        k4.markdown(kartu("⚙️", "Pipeline terakhir", "-", "belum ada catatan", "#64748B"),
                    unsafe_allow_html=True)

    st.write("")
    kiri, kanan = st.columns([5, 1])
    with kiri:
        tampilan = pilih_tampilan()
    with kanan:
        if tombol_segarkan():
            st.cache_data.clear()

    # ================= RINGKASAN =================
    if tampilan == TAMPILAN[0] and df is not None:
        a, b = st.columns(2)
        with a, bingkai():
            st.subheader("Komposisi kategori")
            hitung = df["kategori"].value_counts()
            urut = [k for k in WARNA_KATEGORI if k in hitung.index] + \
                   [k for k in hitung.index if k not in WARNA_KATEGORI]
            fig = go.Figure(go.Pie(
                labels=urut, values=[int(hitung[k]) for k in urut], hole=0.62, sort=False,
                marker=dict(colors=[WARNA_KATEGORI.get(k, "#94A3B8") for k in urut],
                            line=dict(color="#fff", width=2)),
                textinfo="value", hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
            ))
            fig.add_annotation(text=f"<b>{len(df)}</b><br>tempat", showarrow=False,
                               font=dict(size=22))
            fig.update_layout(legend=dict(orientation="v", y=0.5))
            tampil_plotly(fig, 340)
        with b, bingkai():
            st.subheader("Asal data tempat wisata")
            asal = df["status_pencocokan"].map(LABEL_STATUS).value_counts()
            fig = bar_horizontal(asal.index, asal.values,
                                 [WARNA_ASAL.get(k, "#94A3B8") for k in asal.index])
            tampil_plotly(fig, 340)

        c, d = st.columns(2)
        with c, bingkai():
            st.subheader("10 wilayah dengan tempat wisata terbanyak")
            wil = df["wilayah"].dropna().value_counts().head(10)
            if len(wil):
                tampil_plotly(bar_horizontal(wil.index, wil.values, "#0F766E"), 380)
            st.markdown(f'<div class="catatan">Kolom wilayah hanya terisi pada '
                        f'{int(df["wilayah"].notna().sum())} dari {len(df)} data karena '
                        f'keterbatasan sumber.</div>', unsafe_allow_html=True)
        with d, bingkai():
            st.subheader("Alur jumlah data (MongoDB)")
            try:
                alur = mongo_alur()
                dfa = pd.DataFrame({"Tahap": list(alur), "Jumlah": list(alur.values())})
                dfa["Sumber"] = dfa["Tahap"].map(
                    lambda t: "OpenStreetMap" if "OSM" in t
                    else "Wikidata" if "Wikidata" in t and "2 sumber" not in t else "Gabungan")
                fig = bar_horizontal(dfa["Tahap"], dfa["Jumlah"],
                                     [WARNA_SUMBER[s] for s in dfa["Sumber"]])
                tampil_plotly(fig, 380)
                st.markdown('<div class="catatan">Biru: OpenStreetMap · Kuning: Wikidata · '
                            'Hijau: hasil gabungan. Dari data mentah hingga hasil akhir.</div>',
                            unsafe_allow_html=True)
            except Exception as e:
                st.error(f"MongoDB tidak dapat diakses ({type(e).__name__}).")

    # ================= PETA DAN DATA =================
    elif tampilan == TAMPILAN[1] and df is not None:
        semua_kat = [k for k in WARNA_KATEGORI if k in set(df["kategori"])] + \
                    sorted(set(df["kategori"]) - set(WARNA_KATEGORI))
        semua_status = list(LABEL_STATUS.values())
        with bingkai():
            f1, f2, f3 = st.columns(3)
            pilih_kat = f1.multiselect("Kategori", semua_kat, default=semua_kat, key="f_kat")
            pilih_status = f2.multiselect("Asal data", semua_status, default=semua_status,
                                          key="f_status")
            cari = f3.text_input("Cari nama tempat", key="f_cari", placeholder="mis. museum")

        d = df[df["kategori"].isin(pilih_kat)].copy()
        d["asal_data"] = d["status_pencocokan"].map(LABEL_STATUS)
        d = d[d["asal_data"].isin(pilih_status)]
        if cari:
            d = d[d["nama_wisata"].str.contains(cari, case=False, na=False, regex=False)]

        st.markdown(f"Menampilkan **{len(d)}** dari {len(df)} tempat wisata")
        if len(d):
            d["wilayah_tampil"] = d["wilayah"].fillna("-")
            kwargs = dict(
                lat="lat", lon="lon", color="kategori", color_discrete_map=WARNA_KATEGORI,
                hover_name="nama_wisata",
                hover_data={"kategori": True, "wilayah_tampil": True, "asal_data": True,
                            "lat": False, "lon": False},
                labels={"wilayah_tampil": "Wilayah", "asal_data": "Asal data", "kategori": "Kategori"},
                zoom=6, center={"lat": 2.1, "lon": 99.0}, height=560,
            )
            try:
                fig = px.scatter_map(d, map_style="carto-positron", **kwargs)
            except AttributeError:
                fig = px.scatter_mapbox(d, mapbox_style="carto-positron", **kwargs)
            fig.update_traces(marker=dict(size=11, opacity=0.88))
            fig.update_layout(legend=dict(orientation="h", y=1.03, x=0, title_text=""))
            with bingkai():
                tampil_plotly(fig)

            tabel_d = d.copy()
            tabel_d["kolom_terisi"] = pd.to_numeric(tabel_d["kolom_terisi"], errors="coerce").fillna(0)
            kolom = ["nama_wisata", "kategori", "wilayah", "deskripsi", "jam_operasional",
                     "website", "asal_data", "kolom_terisi"]
            konfig = {
                "nama_wisata": st.column_config.TextColumn("Nama", width="medium"),
                "kategori": "Kategori", "wilayah": "Wilayah",
                "deskripsi": st.column_config.TextColumn("Deskripsi", width="large"),
                "jam_operasional": "Jam operasional",
                "website": st.column_config.LinkColumn("Website"),
                "asal_data": "Asal data",
                "kolom_terisi": st.column_config.ProgressColumn(
                    "Kelengkapan", min_value=0, max_value=7, format="%d/7"),
            }
            tampil_tabel(tabel_d, column_order=kolom, column_config=konfig)
            st.download_button("⬇️ Unduh data yang tampil (CSV)",
                               d.drop(columns=["wilayah_tampil"]).to_csv(index=False).encode("utf-8-sig"),
                               "wisata_sumut_terpilih.csv", "text/csv")
        else:
            st.info("Tidak ada data yang cocok dengan filter.")

    # ================= PIPELINE =================
    elif tampilan == TAMPILAN[2]:
        if not runs:
            st.info("Belum ada catatan eksekusi pipeline. Jalankan python pipeline.py.")
        else:
            j = terakhir.get("jumlah") or {}
            teks = (f"Eksekusi terakhir: **{status.upper()}** · run `{terakhir.get('run_id')}` · "
                    f"mulai {fmt(terakhir.get('mulai'))} WIB · pemicu **{terakhir.get('pemicu')}** · "
                    f"mode {terakhir.get('mode')}")
            if status == "berhasil":
                st.success(teks)
            elif status == "gagal":
                st.error(teks + f" · berhenti di {terakhir.get('gagal_di')}")
            else:
                st.info(teks)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Durasi", f"{terakhir.get('durasi_detik') or 0:.0f} detik")
            m2.metric("Data di MongoDB", j.get("mongo_hasil_akhir", "-"))
            m3.metric("Data di PostgreSQL", j.get("postgres_tempat_wisata", "-"))
            m4.metric("Dua database", "Konsisten ✅" if j.get("konsisten") else "Periksa ⚠️")

            langkah = terakhir.get("langkah") or []
            a, b = st.columns([3, 2])
            with a, bingkai():
                st.subheader("Lama tiap langkah")
                if langkah:
                    dl = pd.DataFrame(langkah)[["berkas", "keterangan", "status", "detik"]]
                    fig = bar_horizontal(dl["berkas"], dl["detik"],
                                         [WARNA_STATUS.get(s, "#64748B") for s in dl["status"]],
                                         teks=[f"{x:.0f} dtk" for x in dl["detik"]])
                    tampil_plotly(fig, 420)
                else:
                    st.caption("Belum ada langkah tercatat.")
            with b, bingkai():
                st.subheader("Riwayat eksekusi")
                riwayat = pd.DataFrame([{
                    "Mulai (WIB)": fmt(r.get("mulai")),
                    "Pemicu": r.get("pemicu"),
                    "Status": r.get("status"),
                    "Detik": round(r.get("durasi_detik") or 0),
                } for r in runs])
                tampil_tabel(riwayat)

        try:
            eks = mongo_ekstrak()
            if eks:
                with bingkai():
                    st.subheader("Pengambilan data dari sumber")
                    tampil_tabel(pd.DataFrame([{
                        "Waktu (WIB)": fmt(e.get("waktu")), "Sumber": e.get("sumber"),
                        "Status": e.get("status"), "Baris baru": e.get("jumlah_baru"),
                        "Muncul baru": e.get("muncul_baru"), "Hilang": e.get("hilang"),
                        "Data diganti": "ya" if e.get("diganti") else "tidak",
                    } for e in eks]))
        except Exception:
            pass

    # ================= KUALITAS DATA =================
    elif tampilan == TAMPILAN[3]:
        a, b = st.columns([3, 2])
        with a, bingkai():
            st.subheader("Kelengkapan per kolom")
            if df is not None:
                persen = {label: round(float(df[kol].notna().mean() * 100), 1)
                          for label, kol in KOLOM_INFO.items()}
                persen["Koordinat (lat, lon)"] = round(float(df[["lat", "lon"]].notna().all(axis=1).mean() * 100), 1)
                urut = sorted(persen.items(), key=lambda x: -x[1])
                warna = ["#16A34A" if v >= 80 else "#F59E0B" if v >= 30 else "#EF4444" for _, v in urut]
                fig = bar_horizontal([k for k, _ in urut], [v for _, v in urut], warna,
                                     teks=[f"{v}%" for _, v in urut], rentang_x=[0, 112])
                tampil_plotly(fig, 400)
                st.markdown('<div class="catatan">Hijau: ≥ 80% · Kuning: 30–79% · Merah: &lt; 30%. '
                            'Alamat, harga tiket, dan jam operasional rendah karena sumber '
                            'tidak mencatatnya.</div>', unsafe_allow_html=True)
        with b, bingkai():
            st.subheader("Konsistensi data")
            if kual:
                kons = kual.get("konsistensi", {})
                tampil_tabel(pd.DataFrame([{
                    "Pemeriksaan": LABEL_KONSISTENSI.get(k, k), "Jumlah": v,
                    "Status": "✅ baik" if v == 0 else "⚠️ perlu dicek",
                } for k, v in kons.items()]))
                st.caption(f"Laporan dibuat {fmt(kual.get('waktu'))} WIB")
            else:
                st.caption("Belum ada laporan kualitas.")

        if kual:
            with bingkai():
                st.subheader("Pencocokan dua sumber")
                cocok = kual.get("pencocokan", {})
                cols = st.columns(len(LABEL_PENCOCOKAN))
                for kol, (kunci, label) in zip(cols, LABEL_PENCOCOKAN.items()):
                    kol.metric(label, cocok.get(kunci, "-"))
                st.caption("Hasil pencocokan berdasarkan pemeriksaan manual, bukan akurasi "
                           "terhadap data acuan yang lengkap.")

    # ---- Kaki halaman ----
    st.divider()
    waktu_muat = fmt(df["dimuat_pada"].max()) + " WIB" if df is not None and len(df) else "-"
    st.markdown(
        f'<div class="catatan">Data tempat wisata terakhir dimuat ke PostgreSQL: {waktu_muat}. '
        'Sumber: © OpenStreetMap contributors (ODbL) dan Wikidata (CC0). '
        'Data tempat wisata disimpan di PostgreSQL (Supabase); data mentah, log pipeline, dan '
        f'laporan kualitas di MongoDB Atlas. · <a href="{URL_REPO}" target="_blank">Kode di GitHub</a>'
        '</div>', unsafe_allow_html=True)


dashboard()