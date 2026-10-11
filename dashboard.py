from datetime import datetime
import json
import os
import time
import joblib
import pandas as pd
import pytz
import requests
import streamlit as st
import extra_streamlit_components as stx

# Setup Halaman Streamlit
st.set_page_config(
    page_title="iFOOX Smartbox Multi-Device Dashboard",
    page_icon="🍱",
    layout="wide",
)

# Set Zona Waktu WIB (Asia/Jakarta)
wib_tz = pytz.timezone("Asia/Jakarta")

# FIREBASE CONFIG
FIREBASE_BASE_URL = "https://ifoox-smartbox-default-rtdb.asia-southeast1.firebasedatabase.app"
FIREBASE_API_KEY = st.secrets.get("FIREBASE_API_KEY", "AIzaSyB30K84Ka0ZsfDR06PcBzbJfmEbl8ZQunw")

# Inisialisasi Pengurus Cookie Browser (Fitur Remember Me)
cookie_manager = stx.CookieManager()

# Load Model AI
try:
    model = joblib.load("model/model_ifoox_rf.pkl")
except Exception:
    st.error("❌ Model AI belum ditemukan! Jalankan 'python3 train_model.py' dulu.")


# --- FUNGSI AUTHENTICATION FIREBASE ---
def login_user(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    res = requests.post(url, json=payload)
    if res.status_code == 200:
        return res.json()
    else:
        return None


def register_user(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    res = requests.post(url, json=payload)
    if res.status_code == 200:
        return res.json()
    else:
        err_msg = res.json().get("error", {}).get("message", "Gagal mendaftar")
        return {"error": err_msg}


def refresh_token_request(refresh_token):
    url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    res = requests.post(url, data=payload)
    if res.status_code == 200:
        return res.json()
    return None


# --- MANAGEMENT BOKS DINAMIS PER USER ---
def get_user_box_ids(user_id, auth_token):
    """Mendapatkan daftar ID boks yang dimiliki user dari Firebase."""
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/my_boxes.json?auth={auth_token}"
    try:
        res = requests.get(url, timeout=3)
        if res.status_code == 200 and res.json():
            boxes = res.json()
            if isinstance(boxes, dict):
                return list(boxes.keys())
            elif isinstance(boxes, list):
                return [b for b in boxes if b]
    except Exception:
        pass
    return ["box_01"]  # Default awal jika akun baru terdaftar


def add_user_box_id(user_id, new_box_id, auth_token):
    """Menambahkan ID boks baru ke daftar milik user di Firebase."""
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/my_boxes/{new_box_id}.json?auth={auth_token}"
    try:
        requests.put(url, json=True, timeout=3)
    except Exception:
        pass


# --- FUNGSI BACA BOKS DARI FIREBASE ---
def read_box_data(user_id, box_id, auth_token):
    data = {}
    # 1. Baca data sensor real-time publik langsung dari ESP32
    url_sensor = f"{FIREBASE_BASE_URL}/boxes/{box_id}.json"
    try:
        response = requests.get(url_sensor, timeout=3)
        if response.status_code == 200 and response.json():
            data = response.json()
    except Exception:
        pass

    # 2. Baca konfigurasi makanan milik akun user
    url_config = f"{FIREBASE_BASE_URL}/users/{user_id}/boxes/{box_id}/config.json?auth={auth_token}"
    try:
        response = requests.get(url_config, timeout=3)
        if response.status_code == 200 and response.json():
            data["config"] = response.json()
    except Exception:
        pass

    return data


# --- FUNGSI SIMPAN CONFIG MENGGUNAKAN PATCH ---
def save_box_config(user_id, box_id, config_dict, auth_token):
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/boxes/{box_id}/config.json?auth={auth_token}"
    try:
        requests.patch(url, json=config_dict, timeout=3)
    except Exception:
        pass


# --- FUNGSI BACA SELURUH BOKS USER ---
def read_all_boxes(user_id, auth_token, pilihan_boks_list):
    all_data = {}
    for b_id in pilihan_boks_list:
        all_data[b_id] = read_box_data(user_id, b_id, auth_token)
    return all_data


# Fungsi Hitung Shelf Life (SINKRON DENGAN AI)
def hitung_shelf_life(jenis, durasi_jam, suhu, gas, slope, status_ai="Aman"):
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

    if status_ai == "Segera konsumsi":
        sisa_jam = min(sisa_jam, max(1, int(max_hours * 0.3)))
    elif status_ai != "Aman":
        sisa_jam = 0

    return sisa_jam, max_hours


# ==========================================
# 🔑 MANAGEMENT SESSION AUTHENTICATION & REMEMBER ME
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None

# Semak Cookie Browser untuk Auto-Login
saved_refresh_token = cookie_manager.get("ifoox_refresh_token")
if not st.session_state.authenticated and saved_refresh_token:
    token_data = refresh_token_request(saved_refresh_token)
    if token_data:
        saved_email = cookie_manager.get("ifoox_user_email") or "User"
        st.session_state.authenticated = True
        st.session_state.user_info = {
            "localId": token_data["user_id"],
            "idToken": token_data["id_token"],
            "email": saved_email,
        }

# HALAMAN LOGIN / REGISTER JIKA BELUM AUTHENTICATED
if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center;'>🍱 iFOOX Smartbox</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center;'>Portal Masuk Akun Monitoring</h3>", unsafe_allow_html=True)
    st.write("")

    col_auth1, col_auth2, col_auth3 = st.columns([1, 2, 1])
    with col_auth2:
        tab_login, tab_register = st.tabs(["🔒 Login", "📝 Daftar Akun Baru"])

        with tab_login:
            login_email = st.text_input("Email", key="login_email")
            login_pass = st.text_input("Password", type="password", key="login_pass")
            remember_me = st.checkbox("Ingat Saya (Remember Me)", value=True, key="remember_me_checkbox")

            if st.button("Masuk ke Dashboard", type="primary", use_container_width=True):
                if login_email and login_pass:
                    auth_data = login_user(login_email, login_pass)
                    if auth_data:
                        st.session_state.authenticated = True
                        st.session_state.user_info = auth_data

                        if remember_me and "refreshToken" in auth_data:
                            cookie_manager.set("ifoox_refresh_token", auth_data["refreshToken"], max_age=30*24*3600)
                            cookie_manager.set("ifoox_user_email", auth_data["email"], max_age=30*24*3600)

                        st.success("Berhasil login!")
                        st.rerun()
                    else:
                        st.error("Email atau Password salah!")
                else:
                    st.warning("Mohon isi Email dan Password.")

        with tab_register:
            reg_email = st.text_input("Email Baru", key="reg_email")
            reg_pass = st.text_input("Password Baru (min 6 karakter)", type="password", key="reg_pass")
            if st.button("Buat Akun", use_container_width=True):
                if reg_email and reg_pass:
                    res = register_user(reg_email, reg_pass)
                    if "error" not in res:
                        st.success("Akun berhasil dibuat! Silakan login di tab 'Login'.")
                    else:
                        st.error(f"Gagal pendaftaran: {res['error']}")
                else:
                    st.warning("Mohon isi seluruh form pendaftaran.")

    st.stop()


# ==========================================
# 🏠 HOMEPAGE: OVERVIEW MULTI-SMARTBOX
# ==========================================
user_id = st.session_state.user_info["localId"]
auth_token = st.session_state.user_info["idToken"]
user_email = st.session_state.user_info["email"]

# Dapatkan Boks Milik User dari Firebase (Dinamis)
pilihan_boks = get_user_box_ids(user_id, auth_token)

if "page" not in st.session_state:
    st.session_state.page = "home"
if "target_box" not in st.session_state or st.session_state.target_box not in pilihan_boks:
    st.session_state.target_box = pilihan_boks[0]

st.markdown("""
<style>
.stApp {
    background:
      radial-gradient(circle at 8% 0%, rgba(32, 160, 130, .10), transparent 28%),
      radial-gradient(circle at 95% 12%, rgba(75, 120, 220, .09), transparent 25%);
}
div[data-testid="stButton"] > button {
    border-radius: 12px;
    border: 1px solid rgba(120, 140, 160, .30);
    transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
div[data-testid="stButton"] > button:hover {
    transform: translateY(-5px);
    box-shadow: 0 12px 28px rgba(20, 50, 70, .14);
    border-color: #2aa889;
}
.box-summary {
    border: 1px solid rgba(120, 140, 160, .25);
    border-radius: 18px;
    padding: 20px 20px 16px 20px;
    min-height: 190px;
    background: rgba(255,255,255,.72);
    box-shadow: 0 4px 16px rgba(20,50,70,.05);
    transition: transform .22s ease, box-shadow .22s ease;
}
.box-summary:hover {
    transform: translateY(-5px);
    box-shadow: 0 14px 30px rgba(20,50,70,.12);
}
.box-subtitle { color: #687782; font-size: 13px; }
.box-status { font-size: 17px; font-weight: 700; margin: 10px 0 14px; }
.status-dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:7px; }
</style>
""", unsafe_allow_html=True)


def buka_detail_box(box_id_pilihan):
    st.session_state.target_box = box_id_pilihan
    st.session_state.page = "box"


if st.session_state.page == "home":
    all_boxes_data = read_all_boxes(user_id, auth_token, pilihan_boks)
    st.markdown("# 🍱 iFOOX SMARTBOX")
    st.markdown(f"### Selamat datang, `{user_email}` 👋")
    st.caption("Overview perangkat • sensor real-time • prediksi kualitas makanan berbasis AI")
    st.divider()

    statuses = []
    for b_id in pilihan_boks:
        b_data = all_boxes_data.get(b_id, {}) or {}
        b_cfg = b_data.get("config", {}) or {}
        gas = float(b_data.get("kadar_gas_ppm", 0) or 0)
        temp = float(b_data.get("suhu_c", 0) or 0)
        if gas == 0 and temp == 0:
            status = "Offline"
        elif not b_cfg.get("is_saved", False):
            status = "Kosong"
        else:
            status = b_cfg.get("last_status", "Aman")
        statuses.append(status)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total SmartBox", len(pilihan_boks))
    c2.metric("Perangkat Online", sum(1 for s in statuses if s != "Offline"))
    c3.metric("Perlu Perhatian", sum(1 for s in statuses if s in ("Segera konsumsi", "Tidak disarankan", "Basi / Rawan")))
    st.markdown("## Pilih SmartBox")

    cols = st.columns(min(len(pilihan_boks), 3), gap="large")
    for i, b_id in enumerate(pilihan_boks):
        b_data = all_boxes_data.get(b_id, {}) or {}
        b_cfg = b_data.get("config", {}) or {}
        temp = float(b_data.get("suhu_c", 0) or 0)
        rh = float(b_data.get("kelembapan_rh", 0) or 0)
        gas = float(b_data.get("kadar_gas_ppm", 0) or 0)
        slope = float(b_data.get("slope_gas", 0) or 0)

        if gas == 0 and temp == 0:
            status, color, dot = "Offline", "#89939b", "⚪"
        elif not b_cfg.get("is_saved", False):
            status, color, dot = "Kosong / Siap Digunakan", "#3286c8", "🔵"
        else:
            ai_status = b_cfg.get("last_status", "Aman")
            if ai_status == "Aman":
                status, color, dot = "Aman", "#1c9a6c", "🟢"
            elif ai_status == "Segera konsumsi":
                status, color, dot = "Segera Konsumsi", "#d99a19", "🟡"
            else:
                status, color, dot = "Basi / Rawan", "#d64a4a", "🔴"

        with cols[i % 3]:
            st.markdown(f"""
            <div class="box-summary">
              <div class="box-subtitle">IFO OX • MULTI-DEVICE</div>
              <h3 style="margin:7px 0 2px;">📦 SmartBox #{b_id}</h3>
              <div class="box-status" style="color:{color};">{dot} {status}</div>
              <div class="box-subtitle">🌡️ Suhu <b>{temp:.1f} °C</b> &nbsp; · &nbsp; 💧 RH <b>{rh:.1f}%</b></div>
              <div class="box-subtitle" style="margin-top:7px;">🧪 Gas <b>{gas:.0f} PPM</b> &nbsp; · &nbsp; Slope <b>{slope:.2f}</b></div>
            </div>
            """, unsafe_allow_html=True)

            sisa = b_cfg.get("last_sisa_jam", 0)
            maksimum = b_cfg.get("last_max_jam", 24)
            try:
                progress = max(0.0, min(1.0, float(sisa) / max(1.0, float(maksimum)))) if b_cfg.get("is_saved", False) else 0.0
            except (ValueError, TypeError, ZeroDivisionError):
                progress = 0.0
            st.caption(f"Estimasi sisa shelf life: {sisa} jam" if b_cfg.get("is_saved", False) else "Belum ada makanan terdaftar")
            st.progress(progress)
            st.button(f"Buka SmartBox #{b_id} →", key=f"open_{b_id}", on_click=buka_detail_box, args=(b_id,), use_container_width=True)

    st.divider()
    st.caption("iFOOX SmartBox • AI & IoT Food Quality Monitoring")
    st.stop()


# ==========================================
# ⚙️ SIDEBAR: KONTROL PERANGKAT & LOGOUT
# ==========================================
st.sidebar.header("👤 Akun Saya")
st.sidebar.write(f"Logged in as: **{user_email}**")

if st.sidebar.button("🚪 Logout / Keluar", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.user_info = None
    cookie_manager.delete("ifoox_refresh_token")
    cookie_manager.delete("ifoox_user_email")
    st.rerun()

st.sidebar.divider()

# --- FORM INPUT TAMBAH BOKS BARU DARI USER ---
st.sidebar.header("➕ Tambah Perangkat Boks")
new_box_input = st.sidebar.text_input("ID SmartBox Baru (misal: box_02)", key="input_new_box_id")
if st.sidebar.button("Simpan Boks Baru", use_container_width=True):
    clean_box_id = new_box_input.strip()
    if clean_box_id:
        add_user_box_id(user_id, clean_box_id, auth_token)
        st.sidebar.success(f"Berhasil menambahkan {clean_box_id}!")
        st.rerun()

st.sidebar.divider()
st.sidebar.header("⚙️ Kontrol Perangkat")

if st.sidebar.button("← Kembali ke Homepage", use_container_width=True):
    st.session_state.page = "home"
    st.rerun()

default_index = pilihan_boks.index(st.session_state.target_box) if st.session_state.target_box in pilihan_boks else 0
radio_selected = st.sidebar.radio(
    "Pilih SmartBox Target:",
    pilihan_boks,
    index=default_index,
    format_func=lambda x: f"📦 iFOOX SmartBox #{x}",
)

if radio_selected != st.session_state.target_box:
    st.session_state.target_box = radio_selected
    st.rerun()

selected_box = st.session_state.target_box

# Baca data boks langsung dari Cloud Firebase Database
full_box_data = read_box_data(user_id, selected_box, auth_token)
box_config = full_box_data.get("config", {})

# Ambil status dan konfigurasi tersimpan
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
all_boxes_data = read_all_boxes(user_id, auth_token, pilihan_boks)

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
        label=f"SmartBox #{b_id} {'(Aktif)' if b_id == selected_box else ''}",
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
st.caption("Teknologi Penyimpanan Makanan Berbasis AI & IoT Multi-Device untuk Reduksi Food Waste")

st.divider()

# --- 1. PEMANTAUAN SENSOR REAL-TIME ---
st.subheader(
    f"📡 Pemantauan Sensor Real-Time: **iFOOX SmartBox #{selected_box}**"
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

# --- 2. INPUT DATA MAKANAN ---
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
                save_box_config(user_id, selected_box, new_cfg, auth_token)
                st.rerun()
        else:
            st.success("🔒 Form Terkunci di Firebase Database")

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
                save_box_config(user_id, selected_box, reset_cfg, auth_token)
                st.rerun()

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
        saved_jenis,
        waktu_simpan_jam,
        suhu_val,
        gas_val,
        slope_val,
        status_ai=status_prediksi,
    )

    last_sisa = box_config.get("last_sisa_jam", sisa_jam)
    if last_sisa > 0 and sisa_jam > last_sisa:
        sisa_jam = last_sisa

    if (
        box_config.get("last_status") != status_prediksi
        or box_config.get("last_sisa_jam") != sisa_jam
    ):
        box_config["last_status"] = status_prediksi
        box_config["last_sisa_jam"] = sisa_jam
        box_config["last_max_jam"] = max_jam
        save_box_config(user_id, selected_box, box_config, auth_token)

    col_r1, col_r2 = st.columns([2, 1])

    with col_r1:
        if status_prediksi == "Aman":
            st.success(f"### STATUS: {status_prediksi.upper()}")
            st.write("🟢 Makanan masih segar, bagus, dan sangat aman dikonsumsi.")
        elif status_prediksi == "Segera konsumsi":
            st.warning(f"### STATUS: {status_prediksi.upper()}")
            st.write("⚠️ Kualitas makanan mulai menurun. Sangat disarankan untuk segera dihabiskan!")
        else:
            st.error(f"### STATUS: {status_prediksi.upper()}")
            st.write("🚨 Makanan terdeteksi BASI / membusuk! Tidak disarankan untuk dikonsumsi.")

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

    st.write(f"**Indikator Sisa Umur Simpan Makanan (Boks #{selected_box}):**")
    st.progress(persentase_sisa)
else:
    st.warning(
        f"⚠️ **{selected_box.upper()} belum diisi/disimpan!** Silakan pilih jenis makanan pada form di atas lalu klik **'Simpan & Kunci Makanan'** untuk mengaktifkan pemantauan AI."
    )

if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
