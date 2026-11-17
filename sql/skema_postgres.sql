CREATE SCHEMA IF NOT EXISTS wisata_sumut;

CREATE TABLE IF NOT EXISTS wisata_sumut.kategori (
    id    SERIAL PRIMARY KEY,
    nama  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS wisata_sumut.tempat_wisata (
    id                        SERIAL PRIMARY KEY,
    nama_wisata               TEXT NOT NULL,
    nama_en                   TEXT,
    nama_alternatif           TEXT[] NOT NULL DEFAULT '{}',
    kategori_id               INTEGER NOT NULL REFERENCES wisata_sumut.kategori(id),
    jenis_osm                 TEXT,
    jenis_wikidata            TEXT,
    wilayah                   TEXT,
    wilayah_alternatif        TEXT[] NOT NULL DEFAULT '{}',
    wilayah_asli              TEXT,
    alamat                    TEXT,
    deskripsi                 TEXT,
    harga_tiket               TEXT,
    jam_operasional           TEXT,
    website                   TEXT,
    lat                       DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon                       DOUBLE PRECISION NOT NULL CHECK (lon BETWEEN -180 AND 180),
    sumber                    TEXT[] NOT NULL DEFAULT '{}',
    id_osm                    TEXT UNIQUE,
    id_wikidata               TEXT UNIQUE,
    status_pencocokan         TEXT NOT NULL
        CHECK (status_pencocokan IN ('cocok', 'hanya_osm', 'hanya_wikidata')),
    skor_nama_pencocokan      NUMERIC(3,2),
    jarak_pencocokan_m        INTEGER,
    skor_kelengkapan          NUMERIC(3,2),
    kolom_terisi              INTEGER,
    jumlah_digabung           INTEGER NOT NULL DEFAULT 1,
    catatan_kualitas          TEXT,
    kemungkinan_duplikat      TEXT[] NOT NULL DEFAULT '{}',
    kategori_ditentukan_oleh  TEXT,
    dimuat_pada               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tempat_kategori ON wisata_sumut.tempat_wisata (kategori_id);
CREATE INDEX IF NOT EXISTS idx_tempat_wilayah  ON wisata_sumut.tempat_wisata (wilayah);