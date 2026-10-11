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


# --- FUNGSI BACA BOKS LENGKAP DARI FIREBASE ---
def read_box_data(box_id):
    url = f"{FIREBASE_BASE_URL}/boxes/{box_id}.json"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200 and response.json():
            return response.json()
    except Exception:
        pass
    return {}


# --- FUNGSI SIMPAN CONFIG (STREAMLIT -> FIREBASE VIA PATCH) ---
def save_box_config(box_id, config_dict):
    url = f"{FIREBASE_BASE_URL}/boxes/{box_id}/config.json"
    try:
        requests.patch(url, json=config_dict, timeout=3)
    except Exception:
        pass


# --- FUNGSI BACA SELURUH BOKS UNTUK OVERVIEW SIDEBAR ---
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
# 📌 SIDEBAR: KONTROL PERANGKAT & RINGKASAN
# ==========================================
st.sidebar.header("⚙️ Kontrol Perangkat")

pilihan_boks = ["box_01", "box_02", "box_03"]

selected_box = st.sidebar.radio(
    "Pilih SmartBox Target:",
    pilihan_boks,
    format_func=lambda x: f"📦 iFOOX SmartBox #{x.split('_')[1]}",
)

# BACA BOKS LANGSUNG DARI CLOUD FIREBASE
full_box_data = read_box_data(selected_box)
box_config = full_box_data.get("config", {})

# Ambil status terkunci & input tersimpan langsung dari Firebase
is_saved = box_config.get("is_saved", False)
saved_jenis = box_config.get("jenis_makanan", "Nasi & Karbohidrat")
saved_massa = box_config.get("massa_gram", 150)
saved_tgl_str = box_config.get(
    "tgl_masuk", datetime.now(wib_tz).strftime("%Y-%m-%d")
)
saved_jam_str = box_config.get(
    "jam_pilihan_str",
    f"{datetime.now(wib_tz).hour:02d}:{(datetime.now(wib_tz).minute // 15) * 15:02d}",
)

st.sidebar.divider()

# RINGKASAN MULTI-DEVICE STATUS DI SIDEBAR
st.sidebar.subheader("🌐 Status Ringkas All-Box")
all_boxes_data = read_all_boxes()

for b_id in pilihan_boks:
    b_data = all_boxes_data.get(b_id, {})
    b_gas = float(b_data.get("kadar_gas_ppm", 0.0))
    b_temp = float(b_data.get("suhu_c", 0.0))
    b_cfg = b_data.get("config", {})

    if b_gas == 0.0 and b_temp == 0.0:
        status_ringkas = "⚪ Offline"
    elif not b_cfg.get("is_saved", False):
        status_ringkas = "🟦 Kosong / Unlocked"
    else:
        st_ai = b_cfg.get("last_status", "Aman")
        if st_ai == "Aman":
            status_ringkas = "🟢 Aman"
        elif st_ai == "Segera konsumsi":
            status_ringkas = "🟡 Segera Konsumsi"
        else:
            status_ringkas = "🔴 Basi / Rawan"

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

suhu_val = float(full_box_data.get("suhu_c", 0.0))
rh_val = float(full_box_data.get("kelembapan_rh", 0.0))
gas_val = float(full_box_data.get("kadar_gas_ppm", 0.0))
slope_val = float(full_box_data.get("slope_gas", 0.0))

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

# --- 2. INPUT DATA MAKANAN (SISTEM SAVE, LOCK & DELETE 2-WAY PERSISTENCE) ---
st.subheader(
    f"📝 Form Input Makanan & Status Kunci - **{selected_box.upper()}**"
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
        idx_makanan = (
            opsi_makanan.index(saved_jenis) if saved_jenis in opsi_makanan else 0
        )
        jenis_makanan = st.selectbox(
            "Jenis Makanan",
            opsi_makanan,
            index=idx_makanan,
            disabled=is_saved,
        )
        massa_gram = st.number_input(
            "Berat Makanan (Gram)",
            min_value=10,
            max_value=2000,
            value=int(saved_massa),
            disabled=is_saved,
        )

    now_wib = datetime.now(wib_tz)
    with col_f2:
        try:
            tgl_parsed = datetime.strptime(saved_tgl_str, "%Y-%m-%d").date()
        except Exception:
            tgl_parsed = now_wib.date()

        tgl_masuk = st.date_input(
            "Tanggal Penyimpanan",
            value=tgl_parsed,
            disabled=is_saved,
        )

        list_jam = []
        for h in range(24):
            for m in range(0, 60, 15):
                list_jam.append(f"{h:02d}:{m:02d}")

        idx_default = (
            list_jam.index(saved_jam_str) if saved_jam_str in list_jam else 0
        )
        jam_pilihan_str = st.selectbox(
            "Jam Penyimpanan",
            list_jam,
            index=idx_default,
            disabled=is_saved,
        )

    # TOMBOL SAVE/LOCK & DELETE/RESET
    col_btn1, col_btn2 = st.columns([1, 1])

    with col_btn1:
        if not is_saved:
            if st.button("💾 Simpan & Kunci Makanan", type="primary"):
                new_cfg = {
                    "is_saved": True,
                    "jenis_makanan": jenis_makanan,
                    "massa_gram": massa_gram,
                    "tgl_masuk": tgl_masuk.strftime("%Y-%m-%d"),
                    "jam_pilihan_str": jam_pilihan_str,
                    "last_status": "Aman",
                    "last_sisa_jam": 24,
                    "last_max_jam": 24,
                }
                save_box_config(selected_box, new_cfg)
                st.rerun()
        else:
            st.success("🔒 Form Terkunci & Tersimpan Permanen di Cloud Firebase")

    with col_btn2:
        if is_saved:
            if st.button("🗑️ Hapus / Kosongkan Boks"):
                reset_cfg = {
                    "is_saved": False,
                    "jenis_makanan": "Nasi & Karbohidrat",
                    "massa_gram": 150,
                    "tgl_masuk": datetime.now(wib_tz).strftime("%Y-%m-%d"),
                    "jam_pilihan_str": f"{datetime.now(wib_tz).hour:02d}:{(datetime.now(wib_tz).minute // 15) * 15:02d}",
                    "last_status": "Belum Ada Makanan",
                    "last_sisa_jam": 0,
                    "last_max_jam": 24,
                }
                save_box_config(selected_box, reset_cfg)
                st.rerun()

    # Hitung durasi simpan real-time jika terkunci
    if is_saved:
        jam_h, jam_m = map(int, saved_jam_str.split(":"))
        waktu_gabung_naive = datetime.combine(
            tgl_parsed, datetime.min.time().replace(hour=jam_h, minute=jam_m)
        )
        waktu_gabung_wib = wib_tz.localize(waktu_gabung_naive)

        selisih = now_wib - waktu_gabung_wib
        waktu_simpan_jam = max(0, int(selisih.total_seconds() // 3600))
        st.info(
            f"⏳ Durasi Terdeteksi Disimpan: **{waktu_simpan_jam} Jam** (Waktu WIB)"
        )


# --- 3. PROSES KALKULASI AI REAL-TIME ---
if is_saved:
    payload_dict = {
        "suhu_c": suhu_val,
        "kelembapan_rh": rh_val,
        "massa_gram": saved_massa,
        "kadar_gas_ppm": gas_val,
        "waktu_simpan_jam": waktu_simpan_jam,
    }

    for item in opsi_makanan:
        col_name = f"jenis_makanan_{item}"
        payload_dict[col_name] = 1 if saved_jenis == item else 0

    df_input = pd.DataFrame([payload_dict])

    if hasattr(model, "feature_names_in_"):
        df_input = df_input[model.feature_names_in_]

    status_prediksi = model.predict(df_input)[0]

    sisa_jam, max_jam = hitung_shelf_life(
        saved_jenis, waktu_simpan_jam, suhu_val, gas_val, slope_val
    )

    # Logika Monotonik mutlak (sisa jam tidak naik)
    last_sisa = box_config.get("last_sisa_jam", sisa_jam)
    if last_sisa > 0 and sisa_jam > last_sisa:
        sisa_jam = last_sisa

    # Simpan pembaruan status ke Firebase secara persisten
    if (
        box_config.get("last_status") != status_prediksi
        or box_config.get("last_sisa_jam") != sisa_jam
    ):
        box_config["last_status"] = status_prediksi
        box_config["last_sisa_jam"] = sisa_jam
        box_config["last_max_jam"] = max_jam
        save_box_config(selected_box, box_config)

    # --- TAMPILAN HASIL PREDIKSI ---
    col_r1, col_r2 = st.columns([2, 1])

    with col_r1:
        if status_prediksi == "Aman":
            st.success(f"### STATUS: {status_prediksi.upper()}")
            st.write(
                "🟢 Makanan masih segar, bagus, dan sangat aman dikonsumsi."
            )
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
    st.warning(
        f"⚠️ **{selected_box.upper()} belum diisi/disimpan!** Silakan pilih jenis makanan pada form di atas lalu klik **'Simpan & Kunci Makanan'** untuk mengaktifkan pemantauan AI."
    )

# LOOP AUTO RERUN
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
