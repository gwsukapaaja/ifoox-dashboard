from datetime import datetime
import json
import os
import time
import joblib
import pandas as pd
import pytz
import requests
import streamlit as st

# Setup Halaman Streamlit
st.set_page_config(
    page_title="iFOOX Smartbox Multi-Device Dashboard",
    page_icon="🍱",
    layout="wide",
)

# Set Zona Waktu WIB (Asia/Jakarta)
wib_tz = pytz.timezone("Asia/Jakarta")

# BASE URL FIREBASE
FIREBASE_BASE_URL = "https://ifoox-smartbox-default-rtdb.asia-southeast1.firebasedatabase.app"

# Load Model AI
try:
    model = joblib.load("model/model_ifoox_rf.pkl")
except Exception:
    st.error(
        "❌ Model AI belum ditemukan! Jalankan 'python3 train_model.py' dulu."
    )


# --- INISIALISASI SESSION STATE PER BOKS ---
def init_box_state(box_id):
    if box_id not in st.session_state:
        st.session_state[box_id] = {
            "sudah_dianalisis": False,
            "last_status": "Belum Dianalisis",
            "last_sisa_jam": 0,
            "last_max_jam": 24,
        }


# --- FUNGSI BACA DATA FIREBASE KHUSUS SATU BOKS ---
def read_sensor_data(box_id):
    url = f"{FIREBASE_BASE_URL}/boxes/{box_id}.json"
    try:
        response = requests.get(url, timeout=3)
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
    }


# --- FUNGSI BACA SELURUH BOKS UNTUK OVERVIEW ---
def read_all_boxes():
    url = f"{FIREBASE_BASE_URL}/boxes.json"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200 and response.json():
            return response.json()
    except Exception:
        pass
    return {}


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


# ==========================================
# 📌 SIDEBAR: KONTROL PERANGKAT & RINGKASAN ONLY
# ==========================================
st.sidebar.header("⚙️ Kontrol Perangkat")

pilihan_boks = ["box_01", "box_02", "box_03"]
selected_box = st.sidebar.selectbox(
    "Pilih SmartBox Target:",
    pilihan_boks,
    format_func=lambda x: f"📦 iFOOX SmartBox #{x.split('_')[1]}",
)

# Inisialisasi state & baca data sensor boks aktif
init_box_state(selected_box)
sensor_data = read_sensor_data(selected_box)

st.sidebar.divider()

# RINGKASAN MULTI-DEVICE STATUS DI SIDEBAR
st.sidebar.subheader("🌐 Status Ringkas All-Box")
all_boxes_data = read_all_boxes()

for b_id in pilihan_boks:
    b_data = all_boxes_data.get(b_id, {})
    b_gas = float(b_data.get("kadar_gas_ppm", 0.0))
    b_temp = float(b_data.get("suhu_c", 0.0))

    if b_gas == 0.0 and b_temp == 0.0:
        status_ringkas = "⚪ Offline"
    elif b_gas > 580:
        status_ringkas = "🔴 Basi / Rawan"
    elif b_gas > 360:
        status_ringkas = "🟡 Segera Konsumsi"
    else:
        status_ringkas = "🟢 Aman"

    st.sidebar.metric(
        label=f"SmartBox #{b_id.split('_')[1]} {'(Aktif)' if b_id == selected_box else ''}",
        value=status_ringkas,
        delta=f"Gas: {b_gas:.0f} PPM | Suhu: {b_temp:.1f}°C",
        delta_color="off",
    )

st.sidebar.divider()

# TOGGLE AUTO REFRESH
auto_refresh = st.sidebar.checkbox("🔄 Auto Refresh (Real-Time)", value=True)
refresh_rate = st.sidebar.slider(
    "Interval Refresh (detik)", min_value=1, max_value=10, value=3
)


# ==========================================
# 🍱 MAIN DASHBOARD: MONITORING & INPUT FORM
# ==========================================
st.title("🍱 iFOOX SMARTBOX DASHBOARD")
st.caption(
    "Teknologi Penyimpanan Makanan Berbasis AI & IoT Multi-Device untuk Reduksi Food Waste"
)

st.divider()

# --- 1. PEMANTAUAN SENSOR REAL-TIME ---
st.subheader(
    f"📡 Pemantauan Sensor Real-Time: **iFOOX SmartBox #{selected_box.split('_')[1]}**"
)
col_s1, col_s2, col_s3, col_s4 = st.columns(4)

suhu_val = float(sensor_data.get("suhu_c", 0.0))
rh_val = float(sensor_data.get("kelembapan_rh", 0.0))
gas_val = float(sensor_data.get("kadar_gas_ppm", 0.0))
slope_val = float(sensor_data.get("slope_gas", 0.0))

col_s1.metric(label="Suhu Ruang Box", value=f"{suhu_val:.1f} °C")
col_s2.metric(label="Kelembapan Air", value=f"{rh_val:.1f} %RH")
col_s3.metric(label="Kadar Gas Pembusukan", value=f"{gas_val:.0f} PPM")
col_s4.metric(
    label="Laju Pembusukan (Slope)",
    value=f"{slope_val:.2f} PPM/m",
    delta="Stabil" if slope_val <= 1.0 else "Meningkat",
    delta_color="off" if slope_val <= 1.0 else "inverse",
)

jam_sekarang_wib = datetime.now(wib_tz).strftime("%H:%M:%S")
st.caption(
    f"🔄 Terakhir diperbarui dari ESP32 [{selected_box}]: **{jam_sekarang_wib} WIB**"
)

st.divider()

# --- 2. INPUT DATA MAKANAN (DIPINDAHKAN KE UTAMA) ---
st.subheader(
    f"📝 Form Input & Analisis Prediksi AI - **{selected_box.upper()}**"
)

with st.expander("📌 Masukkan Data Makanan dalam Boks", expanded=True):
    col_f1, col_f2 = st.columns(2)

    opsi_makanan = [
        "Nasi & Karbohidrat",
        "Lauk Hewani",
        "Lauk Nabati",
        "Sayuran Olahan",
        "Buah Potong",
        "Kue & Penganan",
        "Olahan Susu & Santan",
    ]

    with col_f1:
        jenis_makanan = st.selectbox("Jenis Makanan", opsi_makanan)
        massa_gram = st.number_input(
            "Berat Makanan (Gram)", min_value=10, max_value=2000, value=150
        )

    # Waktu Saat Ini Berdasarkan WIB
    now_wib = datetime.now(wib_tz)

    with col_f2:
        tgl_masuk = st.date_input("Tanggal Penyimpanan", value=now_wib.date())

        list_jam = []
        for h in range(24):
            for m in range(0, 60, 15):
                list_jam.append(f"{h:02d}:{m:02d}")

        jam_default = f"{now_wib.hour:02d}:{(now_wib.minute // 15) * 15:02d}"
        idx_default = (
            list_jam.index(jam_default) if jam_default in list_jam else 0
        )

        jam_pilihan_str = st.selectbox(
            "Jam Penyimpanan", list_jam, index=idx_default
        )

    # Parsing jam pilihan ke datetime ber-timezone WIB
    jam_h, jam_m = map(int, jam_pilihan_str.split(":"))
    waktu_gabung_naive = datetime.combine(
        tgl_masuk, datetime.min.time().replace(hour=jam_h, minute=jam_m)
    )
    waktu_gabung_wib = wib_tz.localize(waktu_gabung_naive)

    # Kalkulasi Durasi Simpan Presisi (Sama-sama WIB)
    selisih = now_wib - waktu_gabung_wib
    waktu_simpan_jam = max(0, int(selisih.total_seconds() // 3600))
    st.info(
        f"⏳ Durasi Terdeteksi Disimpan: **{waktu_simpan_jam} Jam** (Waktu WIB)"
    )

# --- 3. TOMBOL & HASIL ANALISIS AI ---
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

    box_state = st.session_state[selected_box]

    # LOGIKA PENGUNCI MONOTONIK MUTLAK PER BOKS (Anti-Naik)
    if box_state["sudah_dianalisis"]:
        last_sisa = box_state.get("last_sisa_jam", sisa_jam)
        if sisa_jam > last_sisa:
            sisa_jam = last_sisa

    box_state["last_sisa_jam"] = sisa_jam
    box_state["last_max_jam"] = max_jam
    box_state["last_status"] = status_prediksi
    box_state["sudah_dianalisis"] = True

# TAMPILKAN HASIL TERAKHIR UNTUK BOKS AKTIF
current_box_state = st.session_state[selected_box]

if current_box_state["sudah_dianalisis"]:
    status_prediksi = current_box_state["last_status"]
    sisa_jam = current_box_state["last_sisa_jam"]
    max_jam = current_box_state["last_max_jam"]

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

    st.write(
        f"**Indikator Sisa Umur Simpan Makanan (Boks #{selected_box.split('_')[1]}):**"
    )
    st.progress(persentase_sisa)
else:
    st.info(
        f"💡 Isikan form makanan di atas lalu klik tombol **'Hitung Prediksi Shelf Life'** untuk menganalisis sisa waktu simpan **{selected_box.upper()}**."
    )

# LOOP AUTO RERUN
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
