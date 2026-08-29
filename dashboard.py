from datetime import datetime
import json
import os
import time
import joblib
import pandas as pd
import requests
import streamlit as st

# Setup Halaman Streamlit
st.set_page_config(
    page_title="iFOOX Smartbox Dashboard", page_icon="🍱", layout="wide"
)

# ⚠️ GANTI DENGAN URL FIREBASE KAMU (TAMBAHKAN /sensor_data.json DI AKHIR)
FIREBASE_URL = "https://ifoox-smartbox-default-rtdb.asia-southeast1.firebasedatabase.app/sensor_data.json"

# Load Model AI
try:
    model = joblib.load("model/model_ifoox_rf.pkl")
except Exception:
    st.error(
        "❌ Model AI belum ditemukan! Jalankan 'python3 train_model.py' dulu."
    )

# --- INISIALISASI SESSION STATE (Mencegah KeyError) ---
if "sudah_dianalisis" not in st.session_state:
    st.session_state["sudah_dianalisis"] = False
if "last_status" not in st.session_state:
    st.session_state["last_status"] = "Belum Dianalisis"
if "last_sisa_jam" not in st.session_state:
    st.session_state["last_sisa_jam"] = 0
if "last_max_jam" not in st.session_state:
    st.session_state["last_max_jam"] = 24


# --- FUNGSI BACA DATA FIREBASE (PENGGANTI FLASK LOKAL) ---
def read_sensor_data():
    try:
        response = requests.get(FIREBASE_URL, timeout=3)
        if response.status_code == 200 and response.json():
            return response.json()
    except Exception:
        pass
    return {
        "suhu_c": 0.0,
        "kelembapan_rh": 0.0,
        "kadar_gas_ppm": 0.0,
        "slope_gas": 0.0,
        "last_update": "Belum ada data",
        "timestamp_full": "",
    }


# Fungsi Hitung Shelf Life
def hitung_shelf_life(jenis, durasi_jam, suhu, gas, slope):
    max_life_map = {
        "Nasi & Karbohidrat": 24,
        "Lauk Hewani": 36,
        "Lauk Nabati": 30,
        "Sayuran Olahan": 18,
        "Buah Potong": 48,
        "Kue & Penganan": 40,
        "Olahan Susu & Santan": 12,
    }
    max_hours = max_life_map.get(jenis, 24)

    faktor_gas = 1.0
    if gas > 580:
        faktor_gas = 1.8
    elif gas > 360:
        faktor_gas = 1.3

    faktor_slope = 1.0
    if slope > 3.0:
        faktor_slope = 1.3
    elif slope > 1.0:
        faktor_slope = 1.1

    faktor_suhu = 1.2 if suhu > 30.0 else 1.0

    jam_terpakai_efektif = durasi_jam * faktor_gas * faktor_suhu * faktor_slope
    sisa_jam = max(0, int(max_hours - jam_terpakai_efektif))

    return sisa_jam, max_hours


sensor_data = read_sensor_data()

# --- TAMPILAN DASHBOARD ---
st.title("🍱 iFOOX SMARTBOX DASHBOARD")
st.caption(
    "Teknologi Penyimpanan Makanan Berbasis AI & IoT untuk Reduksi Food Waste"
)

# SIDEBAR: Input User
st.sidebar.header("📝 Input Makanan")

opsi_makanan = [
    "Nasi & Karbohidrat",
    "Lauk Hewani",
    "Lauk Nabati",
    "Sayuran Olahan",
    "Buah Potong",
    "Kue & Penganan",
    "Olahan Susu & Santan",
]

jenis_makanan = st.sidebar.selectbox("Jenis Makanan", opsi_makanan)
massa_gram = st.sidebar.number_input(
    "Berat Makanan (Gram)", min_value=10, max_value=2000, value=150
)

# INPUT TANGGAL & DROPDOWN JAM (PERSIS SEPERTI TAMPILAN LOKAL KAMU)
tgl_masuk = st.sidebar.date_input("Tanggal Penyimpanan", value=datetime.now().date())

# Membuat daftar jam dropdown interval 15 menit (00:00, 00:15, 00:30, 00:45, dst)
list_jam = []
for h in range(24):
    for m in range(0, 60, 15):
        list_jam.append(f"{h:02d}:{m:02d}")

# Default jam menggunakan jam saat ini yang dibulatkan
now = datetime.now()
jam_default = f"{now.hour:02d}:{(now.minute // 15) * 15:02d}"
idx_default = list_jam.index(jam_default) if jam_default in list_jam else 0

jam_pilihan_str = st.sidebar.selectbox("Jam Penyimpanan", list_jam, index=idx_default)

# Parsing jam pilihan ke datetime
jam_h, jam_m = map(int, jam_pilihan_str.split(":"))
waktu_gabung = datetime.combine(tgl_masuk, datetime.now().time().replace(hour=jam_h, minute=jam_m, second=0))

# Kalkulasi Durasi Simpan
selisih = datetime.now() - waktu_gabung
waktu_simpan_jam = max(0, int(selisih.total_seconds() // 3600))
st.sidebar.info(f"⏳ Durasi Simpan: **{waktu_simpan_jam} Jam**")

# Toggle & Interval Auto Refresh
st.sidebar.divider()
auto_refresh = st.sidebar.checkbox("🔄 Auto Refresh (Real-Time)", value=True)
refresh_rate = st.sidebar.slider(
    "Interval Refresh (detik)", min_value=1, max_value=10, value=3
)

# TAMPILAN REAL-TIME METRIC CARDS
st.subheader("📡 Pemantauan Sensor iFOOX (Real-Time)")
col_s1, col_s2, col_s3, col_s4 = st.columns(4)

suhu_val = float(sensor_data.get("suhu_c", 0.0))
rh_val = float(sensor_data.get("kelembapan_rh", 0.0))
gas_val = float(sensor_data.get("kadar_gas_ppm", 0.0))
slope_val = float(sensor_data.get("slope_gas", 0.0))
last_up = sensor_data.get("last_update", "Belum ada data")

col_s1.metric(label="Suhu Ruang Box", value=f"{suhu_val:.1f} °C")
col_s2.metric(label="Kelembapan Air", value=f"{rh_val:.1f} %RH")
col_s3.metric(label="Kadar Gas Pembusukan", value=f"{gas_val:.0f} PPM")
col_s4.metric(
    label="Laju Pembusukan (Slope)",
    value=f"{slope_val:.2f} PPM/m",
    delta="Stabil" if slope_val <= 1.0 else "Meningkat",
    delta_color="off" if slope_val <= 1.0 else "inverse",
)

st.caption(f"🔄 Terakhir diperbarui dari ESP32: **{last_up}**")

st.divider()

# ANALISIS SHELF LIFE MANUAL VIA TOMBOL
st.subheader("🤖 Analisis Prediksi Kelayakan & Shelf Life (AI)")

if st.button("🔍 Hitung Prediksi Shelf Life", type="primary"):
    payload_dict = {
        "suhu_c": suhu_val,
        "kelembapan_rh": rh_val,
        "massa_gram": massa_gram,
        "kadar_gas_ppm": gas_val,
        "waktu_simpan_jam": waktu_simpan_jam,
    }

    for item in opsi_makanan:
        col_name = f"jenis_makanan_{item}"
        payload_dict[col_name] = 1 if jenis_makanan == item else 0

    df_input = pd.DataFrame([payload_dict])

    if hasattr(model, "feature_names_in_"):
        df_input = df_input[model.feature_names_in_]

    status_prediksi = model.predict(df_input)[0]

    sisa_jam, max_jam = hitung_shelf_life(
        jenis_makanan, waktu_simpan_jam, suhu_val, gas_val, slope_val
    )

    # LOGIKA PENGUNCI MONOTONIK MUTLAK (Anti-Naik)
    if st.session_state["sudah_dianalisis"]:
        last_sisa = st.session_state.get("last_sisa_jam", sisa_jam)
        if sisa_jam > last_sisa:
            sisa_jam = last_sisa

    st.session_state["last_sisa_jam"] = sisa_jam
    st.session_state["last_max_jam"] = max_jam
    st.session_state["last_status"] = status_prediksi
    st.session_state["sudah_dianalisis"] = True

# TAMPILKAN HASIL TERAKHIR
if st.session_state["sudah_dianalisis"]:
    status_prediksi = st.session_state["last_status"]
    sisa_jam = st.session_state["last_sisa_jam"]
    max_jam = st.session_state["last_max_jam"]

    col_r1, col_r2 = st.columns([2, 1])

    with col_r1:
        if status_prediksi == "Aman":
            st.success(f"### STATUS: {status_prediksi.upper()}")
            st.write("🟢 Makanan masih segar, bagus, dan sangat aman dikonsumsi.")
        elif status_prediksi == "Segera konsumsi":
            st.warning(f"### STATUS: {status_prediksi.upper()}")
            st.write(
                "⚠️ Kualitas makanan mulai menurun. Sangat disarankan untuk segera dihabiskan!"
            )
        else:
            st.error(f"### STATUS: {status_prediksi.upper()}")
            st.write(
                "🚨 Makanan terdeteksi BASI / membusuk! Tidak disarankan untuk dikonsumsi."
            )

    with col_r2:
        if status_prediksi == "Tidak disarankan":
            st.metric(
                label="Estimasi Sisa Shelf Life",
                value="0 Jam",
                delta="Kedaluwarsa",
                delta_color="inverse",
            )
        else:
            st.metric(
                label="Estimasi Sisa Shelf Life",
                value=f"{sisa_jam} Jam",
                delta=f"Maks: {max_jam} Jam",
            )

    persentase_sisa = max(0.0, min(1.0, sisa_jam / max_jam))
    if status_prediksi == "Tidak disarankan":
        persentase_sisa = 0.0

    st.write("**Indikator Sisa Umur Simpan Makanan:**")
    st.progress(persentase_sisa)
else:
    st.info(
        "💡 Klik tombol **'Hitung Prediksi Shelf Life'** di atas untuk menganalisis sisa waktu simpan makanan secara presisi."
    )

# LOOP AUTO RERUN
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
