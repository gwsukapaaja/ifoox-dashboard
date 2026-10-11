from datetime import datetime
import json
import os
import time
import joblib
import pandas as pd
import pytz
import requests
import streamlit as st

# Setup Halaman
st.set_page_config(page_title="iFOOX Smartbox Multi-Device Dashboard", page_icon="🍱", layout="wide")
wib_tz = pytz.timezone("Asia/Jakarta")

FIREBASE_BASE_URL = "https://ifoox-smartbox-default-rtdb.asia-southeast1.firebasedatabase.app"
FIREBASE_API_KEY = st.secrets.get("FIREBASE_API_KEY", "AIzaSyB30K84Ka0ZsfDR06PcBzbJfmEbl8ZQunw")

# Load Model AI
try:
    model = joblib.load("model/model_ifoox_rf.pkl")
except Exception:
    st.error("❌ Model AI belum ditemukan! Jalankan 'python3 train_model.py' dulu.")


# --- FUNGSI AUTHENTICATION FIREBASE ---
def auth_request(endpoint, email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:{endpoint}?key={FIREBASE_API_KEY}"
    res = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
    return res.json() if res.status_code == 200 else {"error": res.json().get("error", {}).get("message", "Error")}


# --- MANAGEMENT BOKS PER USER ---
def get_user_box_ids(user_id, auth_token):
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/my_boxes.json?auth={auth_token}"
    try:
        res = requests.get(url, timeout=3)
        if res.status_code == 200 and res.json():
            boxes = res.json()
            return list(boxes.keys()) if isinstance(boxes, dict) else [b for b in boxes if b]
    except Exception:
        pass
    return ["box_01"]


def add_user_box_id(user_id, new_box_id, auth_token):
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/my_boxes/{new_box_id}.json?auth={auth_token}"
    try:
        requests.put(url, json=True, timeout=3)
    except Exception:
        pass


def read_box_data(user_id, box_id, auth_token):
    data = {}
    try:
        res_sensor = requests.get(f"{FIREBASE_BASE_URL}/boxes/{box_id}.json", timeout=3)
        if res_sensor.status_code == 200 and res_sensor.json():
            data = res_sensor.json()
    except Exception:
        pass

    try:
        res_cfg = requests.get(f"{FIREBASE_BASE_URL}/users/{user_id}/configs/{box_id}.json?auth={auth_token}", timeout=3)
        if res_cfg.status_code == 200 and res_cfg.json():
            data["config"] = res_cfg.json()
    except Exception:
        pass
    return data


def save_box_config(user_id, box_id, config_dict, auth_token):
    try:
        requests.patch(f"{FIREBASE_BASE_URL}/users/{user_id}/configs/{box_id}.json?auth={auth_token}", json=config_dict, timeout=3)
    except Exception:
        pass


def hitung_shelf_life(jenis, durasi_jam, suhu, gas, slope, status_ai="Aman"):
    max_life_map = {
        "Nasi & Karbohidrat": 24, "Lauk Hewani": 36, "Lauk Nabati": 30,
        "Sayuran Olahan": 18, "Buah Potong": 48, "Kue & Penganan": 40, "Olahan Susu & Santan": 12
    }
    max_hours = max_life_map.get(jenis, 24)
    f_gas = 1.8 if gas > 580 else (1.3 if gas > 360 else 1.0)
    f_slope = 1.3 if slope > 3.0 else (1.1 if slope > 1.0 else 1.0)
    f_suhu = 1.2 if suhu > 30.0 else 1.0

    jam_efektif = durasi_jam * f_gas * f_suhu * f_slope
    sisa_jam = max(0, int(max_hours - jam_efektif))

    if status_ai == "Segera konsumsi":
        sisa_jam = min(sisa_jam, max(1, int(max_hours * 0.3)))
    elif status_ai != "Aman":
        sisa_jam = 0
    return sisa_jam, max_hours


# --- SESSION LOGIN ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center;'>🍱 iFOOX Smartbox</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center;'>Portal Masuk Akun Monitoring</h3>", unsafe_allow_html=True)
    
    _, col, _ = st.columns([1, 2, 1])
    with col:
        tab1, tab2 = st.tabs(["🔒 Login", "📝 Daftar Akun Baru"])
        with tab1:
            email, password = st.text_input("Email", key="l_e"), st.text_input("Password", type="password", key="l_p")
            if st.button("Masuk ke Dashboard", type="primary", use_container_width=True):
                res = auth_request("signInWithPassword", email, password)
                if "error" not in res:
                    st.session_state.authenticated, st.session_state.user_info = True, res
                    st.rerun()
                else:
                    st.error("Email atau Password salah!")
        with tab2:
            r_email, r_pass = st.text_input("Email Baru", key="r_e"), st.text_input("Password Baru", type="password", key="r_p")
            if st.button("Buat Akun", use_container_width=True):
                res = auth_request("signUp", r_email, r_pass)
                st.success("Akun berhasil dibuat! Silakan Login.") if "error" not in res else st.error(f"Gagal: {res['error']}")
    st.stop()


# --- INITIALISASI DASHBOARD ---
user_id = st.session_state.user_info["localId"]
auth_token = st.session_state.user_info["idToken"]
user_email = st.session_state.user_info["email"]

pilihan_boks = get_user_box_ids(user_id, auth_token)

if "page" not in st.session_state:
    st.session_state.page = "home"
if "selected_box" not in st.session_state or st.session_state.selected_box not in pilihan_boks:
    st.session_state.selected_box = pilihan_boks[0]


# --- SIDEBAR ---
st.sidebar.header("👤 Akun Saya")
st.sidebar.write(f"Logged in: **{user_email}**")
if st.sidebar.button("🚪 Logout", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.user_info = None
    st.rerun()

st.sidebar.divider()
st.sidebar.header("➕ Tambah Perangkat Boks")
new_box = st.sidebar.text_input("ID SmartBox (misal: box_02)", key="in_box")
if st.sidebar.button("Simpan Boks Baru", use_container_width=True):
    if new_box.strip():
        add_user_box_id(user_id, new_box.strip(), auth_token)
        st.sidebar.success(f"Berhasil menambahkan {new_box}!")
        st.rerun()

st.sidebar.divider()
st.sidebar.header("⚙️ Kontrol Perangkat")
if st.sidebar.button("← Kembali ke Homepage", use_container_width=True):
    st.session_state.page = "home"
    st.rerun()

selected_box = st.sidebar.radio("Pilih SmartBox Target:", pilihan_boks, index=pilihan_boks.index(st.session_state.selected_box), key="selected_box")

# STATUS RINGKAS SIDEBAR
st.sidebar.divider()
st.sidebar.subheader("🌐 Status Ringkas All-Box")
all_boxes_data = {b: read_box_data(user_id, b, auth_token) for b in pilihan_boks}

for b_id in pilihan_boks:
    b_data = all_boxes_data.get(b_id, {})
    b_cfg = b_data.get("config", {})
    gas, temp = float(b_data.get("kadar_gas_ppm", 0)), float(b_data.get("suhu_c", 0))

    if gas == 0 and temp == 0:
        st_txt = "⚪ Offline"
    elif not b_cfg.get("is_saved", False):
        st_txt = "🟦 Kosong"
    else:
        st_ai = b_cfg.get("last_status", "Aman")
        st_txt = "🟢 Aman" if st_ai == "Aman" else ("🟡 Segera Konsumsi" if st_ai == "Segera konsumsi" else "🔴 Basi / Rawan")

    st.sidebar.metric(label=f"SmartBox #{b_id}", value=st_txt, delta=f"Gas: {gas:.0f} PPM | Suhu: {temp:.1f}°C", delta_color="off")

auto_refresh = st.sidebar.checkbox("🔄 Auto Refresh", value=True)
refresh_rate = st.sidebar.slider("Interval (detik)", 1, 10, 3)


# --- HALAMAN HOMEPAGE ---
if st.session_state.page == "home":
    st.markdown("# 🍱 iFOOX SMARTBOX")
    st.markdown(f"### Selamat datang, `{user_email}` 👋")
    st.caption("Overview perangkat • sensor real-time • prediksi kualitas makanan berbasis AI")
    st.divider()

    cols = st.columns(min(len(pilihan_boks), 3), gap="large")
    for i, b_id in enumerate(pilihan_boks):
        b_data = all_boxes_data.get(b_id, {}) or {}
        b_cfg = b_data.get("config", {}) or {}
        temp, rh, gas, slope = float(b_data.get("suhu_c", 0)), float(b_data.get("kelembapan_rh", 0)), float(b_data.get("kadar_gas_ppm", 0)), float(b_data.get("slope_gas", 0))

        if gas == 0 and temp == 0:
            status, color, dot = "Offline", "#89939b", "⚪"
        elif not b_cfg.get("is_saved", False):
            status, color, dot = "Kosong / Siap Digunakan", "#3286c8", "🔵"
        else:
            ai_st = b_cfg.get("last_status", "Aman")
            status, color, dot = ("Aman", "#1c9a6c", "🟢") if ai_st == "Aman" else (("Segera Konsumsi", "#d99a19", "🟡") if ai_st == "Segera konsumsi" else ("Basi / Rawan", "#d64a4a", "🔴"))

        with cols[i % 3]:
            st.markdown(f"""
            <div style="border:1px solid rgba(120,140,160,.25); border-radius:18px; padding:20px; background:rgba(255,255,255,.72);">
              <div style="color:#687782; font-size:13px;">IFO OX • DEVICE</div>
              <h3 style="margin:7px 0 2px;">📦 SmartBox #{b_id}</h3>
              <div style="font-size:17px; font-weight:700; margin:10px 0 14px; color:{color};">{dot} {status}</div>
              <div style="color:#687782; font-size:13px;">🌡️ Suhu <b>{temp:.1f} °C</b> · 💧 RH <b>{rh:.1f}%</b></div>
              <div style="color:#687782; font-size:13px; margin-top:7px;">🧪 Gas <b>{gas:.0f} PPM</b> · Slope <b>{slope:.2f}</b></div>
            </div>
            """, unsafe_allow_html=True)

            sisa = b_cfg.get("last_sisa_jam", 0)
            st.caption(f"Estimasi sisa shelf life: {sisa} jam" if b_cfg.get("is_saved", False) else "Belum ada makanan terdaftar")
            if st.button(f"Buka SmartBox #{b_id} →", key=f"open_{b_id}", use_container_width=True):
                st.session_state.selected_box, st.session_state.page = b_id, "box"
                st.rerun()

    st.divider()
    st.caption("iFOOX SmartBox • AI & IoT Food Quality Monitoring")
    st.stop()


# --- HALAMAN DETAIL DASHBOARD BOKS ---
full_box_data = read_box_data(user_id, selected_box, auth_token)
box_config = full_box_data.get("config", {})

is_saved = box_config.get("is_saved", False)
saved_jenis = box_config.get("jenis_makanan", "Nasi & Karbohidrat")
saved_massa = box_config.get("massa_gram", 150)
saved_tgl_str = box_config.get("tgl_masuk", datetime.now(wib_tz).strftime("%Y-%m-%d"))
saved_jam_str = box_config.get("jam_pilihan_str", f"{datetime.now(wib_tz).hour:02d}:{(datetime.now(wib_tz).minute // 15) * 15:02d}")

st.title(f"🍱 MONITORING: SMARTBOX #{selected_box.upper()}")
c1, c2, c3, c4 = st.columns(4)

suhu_val, rh_val, gas_val, slope_val = float(full_box_data.get("suhu_c", 0)), float(full_box_data.get("kelembapan_rh", 0)), float(full_box_data.get("kadar_gas_ppm", 0)), float(full_box_data.get("slope_gas", 0))

c1.metric("Suhu Ruang Box", f"{suhu_val:.1f} °C")
c2.metric("Kelembapan Air", f"{rh_val:.1f} %RH")
c3.metric("Kadar Gas Pembusukan", f"{gas_val:.0f} PPM")
c4.metric("Laju Pembusukan (Slope)", f"{slope_val:.2f} PPM/m")

st.divider()

# FORM INPUT MAKANAN
opsi_makanan = ["Nasi & Karbohidrat", "Lauk Hewani", "Lauk Nabati", "Sayuran Olahan", "Buah Potong", "Kue & Penganan", "Olahan Susu & Santan"]

with st.expander("📌 Form Input Data Makanan", expanded=True):
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        jenis_makanan = st.selectbox("Jenis Makanan", opsi_makanan, index=opsi_makanan.index(saved_jenis) if saved_jenis in opsi_makanan else 0, disabled=is_saved)
        massa_gram = st.number_input("Berat Makanan (Gram)", min_value=10, max_value=2000, value=int(saved_massa), disabled=is_saved)

    with col_f2:
        try:
            tgl_parsed = datetime.strptime(saved_tgl_str, "%Y-%m-%d").date()
        except Exception:
            tgl_parsed = datetime.now(wib_tz).date()
        tgl_masuk = st.date_input("Tanggal Penyimpanan", value=tgl_parsed, disabled=is_saved)

        list_jam = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 15)]
        jam_pilihan_str = st.selectbox("Jam Penyimpanan", list_jam, index=list_jam.index(saved_jam_str) if saved_jam_str in list_jam else 0, disabled=is_saved)

    b1, b2 = st.columns([1, 1])
    with b1:
        if not is_saved:
            if st.button("💾 Simpan & Kunci Makanan", type="primary"):
                save_box_config(user_id, selected_box, {
                    "is_saved": True, "jenis_makanan": jenis_makanan, "massa_gram": massa_gram,
                    "tgl_masuk": tgl_masuk.strftime("%Y-%m-%d"), "jam_pilihan_str": jam_pilihan_str,
                    "last_status": "Aman", "last_sisa_jam": 24, "last_max_jam": 24,
                }, auth_token)
                st.rerun()
        else:
            st.success("🔒 Form Terkunci di Firebase Database")

    with b2:
        if is_saved:
            if st.button("🗑️ Hapus / Kosongkan Boks"):
                save_box_config(user_id, selected_box, {
                    "is_saved": False, "jenis_makanan": "Nasi & Karbohidrat", "massa_gram": 150,
                    "tgl_masuk": datetime.now(wib_tz).strftime("%Y-%m-%d"),
                    "jam_pilihan_str": "00:00", "last_status": "Belum Ada Makanan",
                    "last_sisa_jam": 0, "last_max_jam": 24,
                }, auth_token)
                st.rerun()

    if is_saved:
        jam_h, jam_m = map(int, saved_jam_str.split(":"))
        waktu_wib = wib_tz.localize(datetime.combine(tgl_parsed, datetime.min.time().replace(hour=jam_h, minute=jam_m)))
        waktu_simpan_jam = max(0, int((datetime.now(wib_tz) - waktu_wib).total_seconds() // 3600))
        st.info(f"⏳ Durasi Terdeteksi Disimpan: **{waktu_simpan_jam} Jam** (Waktu WIB)")


# PROSES KALKULASI AI REAL-TIME
if is_saved:
    payload_dict = {"suhu_c": suhu_val, "kelembapan_rh": rh_val, "massa_gram": saved_massa, "kadar_gas_ppm": gas_val, "waktu_simpan_jam": waktu_simpan_jam}
    for item in opsi_makanan:
        payload_dict[f"jenis_makanan_{item}"] = 1 if saved_jenis == item else 0

    df_input = pd.DataFrame([payload_dict])
    if hasattr(model, "feature_names_in_"):
        df_input = df_input[model.feature_names_in_]

    status_prediksi = model.predict(df_input)[0]
    sisa_jam, max_jam = hitung_shelf_life(saved_jenis, waktu_simpan_jam, suhu_val, gas_val, slope_val, status_ai=status_prediksi)

    last_sisa = box_config.get("last_sisa_jam", sisa_jam)
    if last_sisa > 0 and sisa_jam > last_sisa:
        sisa_jam = last_sisa

    if box_config.get("last_status") != status_prediksi or box_config.get("last_sisa_jam") != sisa_jam:
        box_config["last_status"], box_config["last_sisa_jam"], box_config["last_max_jam"] = status_prediksi, sisa_jam, max_jam
        save_box_config(user_id, selected_box, box_config, auth_token)

    col_r1, col_r2 = st.columns([2, 1])
    with col_r1:
        if status_prediksi == "Aman":
            st.success(f"### STATUS: {status_prediksi.upper()}\n🟢 Makanan masih segar, bagus, dan sangat aman dikonsumsi.")
        elif status_prediksi == "Segera konsumsi":
            st.warning(f"### STATUS: {status_prediksi.upper()}\n⚠️ Kualitas makanan mulai menurun. Sangat disarankan untuk segera dihabiskan!")
        else:
            st.error(f"### STATUS: {status_prediksi.upper()}\n🚨 Makanan terdeteksi BASI / membusuk! Tidak disarankan untuk dikonsumsi.")

    with col_r2:
        st.metric("Estimasi Sisa Shelf Life", "0 Jam" if status_prediksi == "Tidak disarankan" else f"{sisa_jam} Jam", delta="Kedaluwarsa" if status_prediksi == "Tidak disarankan" else f"Maks: {max_jam} Jam", delta_color="inverse" if status_prediksi == "Tidak disarankan" else "normal")

    st.progress(0.0 if status_prediksi == "Tidak disarankan" else max(0.0, min(1.0, sisa_jam / max_jam)))
else:
    st.warning(f"⚠️ **{selected_box.upper()} belum diisi/disimpan!** Silakan pilih jenis makanan pada form di atas lalu klik **'Simpan & Kunci Makanan'**.")

if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
