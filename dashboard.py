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
    page_title="iFOOX Smartbox Dashboard",
    page_icon="🍱",
    layout="wide",
)

# Set Zona Waktu WIB (Asia/Jakarta)
wib_tz = pytz.timezone("Asia/Jakarta")

# FIREBASE CONFIG
FIREBASE_BASE_URL = "https://ifoox-smartbox-default-rtdb.asia-southeast1.firebasedatabase.app"
FIREBASE_API_KEY = st.secrets.get("FIREBASE_API_KEY", "AIzaSyB30K84Ka0ZsfDR06PcBzbJfmEbl8ZQunw")

# Inisialisasi Cookie Manager (Remember Me)
cookie_manager = stx.CookieManager(key="ifoox_cookie_manager")

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
    return res.json() if res.status_code == 200 else None


def register_user(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    res = requests.post(url, json=payload)
    if res.status_code == 200:
        return res.json()
    err_msg = res.json().get("error", {}).get("message", "Gagal mendaftar")
    return {"error": err_msg}


def refresh_token_request(refresh_token):
    url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    res = requests.post(url, data=payload)
    return res.json() if res.status_code == 200 else None


def get_user_details(id_token):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}"
    payload = {"idToken": id_token}
    res = requests.post(url, json=payload)
    if res.status_code == 200 and "users" in res.json():
        return res.json()["users"][0]
    return None


# --- MANAGEMENT BOKS DINAMIS PER USER ---
def get_user_box_ids(user_id, auth_token):
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/my_boxes.json?auth={auth_token}"
    try:
        res = requests.get(url, timeout=3)
        if res.status_code == 200 and res.json() is not None:
            boxes = res.json()
            if isinstance(boxes, dict):
                return list(boxes.keys())
            elif isinstance(boxes, list):
                return [b for b in boxes if b]
    except Exception:
        pass
    return []


def add_user_box_id(user_id, new_box_id, auth_token):
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/my_boxes/{new_box_id}.json?auth={auth_token}"
    try:
        requests.put(url, json=True, timeout=3)
    except Exception:
        pass


def delete_user_box_id(user_id, box_id_to_delete, auth_token):
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/my_boxes/{box_id_to_delete}.json?auth={auth_token}"
    try:
        requests.delete(url, timeout=3)
    except Exception:
        pass


# --- FUNGSI BACA BOKS DARI FIREBASE ---
def read_box_data(user_id, box_id, auth_token):
    data = {}
    url_sensor = f"{FIREBASE_BASE_URL}/boxes/{box_id}.json"
    try:
        response = requests.get(url_sensor, timeout=3)
        if response.status_code == 200 and response.json():
            data = response.json()
    except Exception:
        pass

    url_config = f"{FIREBASE_BASE_URL}/users/{user_id}/boxes/{box_id}/config.json?auth={auth_token}"
    try:
        response = requests.get(url_config, timeout=3)
        if response.status_code == 200 and response.json():
            data["config"] = response.json()
    except Exception:
        pass

    return data


def save_box_config(user_id, box_id, config_dict, auth_token):
    url = f"{FIREBASE_BASE_URL}/users/{user_id}/boxes/{box_id}/config.json?auth={auth_token}"
    try:
        requests.patch(url, json=config_dict, timeout=3)
    except Exception:
        pass


def read_all_boxes(user_id, auth_token, pilihan_boks_list):
    all_data = {}
    for b_id in pilihan_boks_list:
        all_data[b_id] = read_box_data(user_id, b_id, auth_token)
    return all_data


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

    faktor_gas = 2.0 if gas > 500 else (1.4 if gas > 300 else 1.0)
    faktor_slope = 1.4 if slope > 3.0 else (1.2 if slope > 1.0 else 1.0)
    faktor_suhu = 1.4 if suhu > 30.0 else 1.0

    jam_terpakai_efektif = durasi_jam * faktor_gas * faktor_suhu * faktor_slope
    sisa_jam = max(0, int(max_hours - jam_terpakai_efektif))

    if status_ai == "Segera konsumsi":
        sisa_maks_peringatan = int(max_hours * 0.35)
        sisa_jam = min(sisa_jam, sisa_maks_peringatan)
    elif status_ai in ("Tidak disarankan", "Basi / Rawan"):
        sisa_jam = 0

    return sisa_jam, max_hours


# ==========================================
# 🔑 AUTHENTICATION & REMEMBER ME
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None

# Ambil cookie dari browser jika belum terautentikasi
if not st.session_state.authenticated:
    all_cookies = cookie_manager.get_all()
    saved_refresh_token = all_cookies.get("ifoox_refresh_token")
    saved_email = all_cookies.get("ifoox_user_email")

    if saved_refresh_token:
        token_data = refresh_token_request(saved_refresh_token)
        if token_data and "id_token" in token_data:
            user_detail = get_user_details(token_data["id_token"])
            email_found = user_detail.get("email") if user_detail else (saved_email or "User")

            st.session_state.authenticated = True
            st.session_state.user_info = {
                "localId": token_data.get("user_id") or token_data.get("user_id"),
                "idToken": token_data["id_token"],
                "email": email_found,
            }

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center;'>🍱 iFOOX Smartbox</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>AI-Powered Food Quality Monitoring</p>", unsafe_allow_html=True)
    st.write("")

    _, col_auth, _ = st.columns([1, 2, 1])
    with col_auth:
        tab_login, tab_register = st.tabs(["🔒 Login", "📝 Daftar Baru"])

        with tab_login:
            login_email = st.text_input("Email", key="login_email")
            login_pass = st.text_input("Password", type="password", key="login_pass")
            remember_me = st.checkbox("Ingat Saya", value=True, key="remember_me_checkbox")

            if st.button("Masuk", type="primary", use_container_width=True):
                if login_email and login_pass:
                    auth_data = login_user(login_email, login_pass)
                    if auth_data and "idToken" in auth_data:
                        st.session_state.authenticated = True
                        st.session_state.user_info = auth_data

                        if remember_me:
                            ref_token = auth_data.get("refreshToken") or auth_data.get("refresh_token")
                            if ref_token:
                                cookie_manager.set("ifoox_refresh_token", ref_token, max_age=30*24*3600, key="set_cookie_token")
                                cookie_manager.set("ifoox_user_email", auth_data.get("email", ""), max_age=30*24*3600, key="set_cookie_email")

                        st.success("Berhasil masuk!")
                        st.rerun()
                    else:
                        st.error("Email atau Password salah!")
                else:
                    st.warning("Mohon isi Email dan Password.")

        with tab_register:
            reg_email = st.text_input("Email Baru", key="reg_email")
            reg_pass = st.text_input("Password Baru", type="password", key="reg_pass")
            if st.button("Daftar Akun", use_container_width=True):
                if reg_email and reg_pass:
                    res = register_user(reg_email, reg_pass)
                    if "error" not in res:
                        st.success("Akun berhasil dibuat! Silakan login.")
                    else:
                        st.error(f"Gagal: {res['error']}")
                else:
                    st.warning("Mohon lengkapi formulir.")

    st.stop()


# ==========================================
# 🏠 GLOBAL STATE & CSS
# ==========================================
user_id = st.session_state.user_info["localId"]
auth_token = st.session_state.user_info["idToken"]
user_email = st.session_state.user_info.get("email", "User")

pilihan_boks = get_user_box_ids(user_id, auth_token)

if "page" not in st.session_state:
    st.session_state.page = "home"

if pilihan_boks:
    if "target_box" not in st.session_state or st.session_state.target_box not in pilihan_boks:
        st.session_state.target_box = pilihan_boks[0]
else:
    st.session_state.target_box = None

st.markdown("""
<style>
.box-summary {
    border: 1px solid rgba(120, 140, 160, .20);
    border-radius: 14px;
    padding: 16px;
    background: rgba(255,255,255,.8);
    box-shadow: 0 2px 10px rgba(0,0,0,.04);
}
</style>
""", unsafe_allow_html=True)


def buka_detail_box(box_id_pilihan):
    st.session_state.target_box = box_id_pilihan
    st.session_state.page = "box"


# ==========================================
# 🏠 HOMEPAGE: OVERVIEW RINGKAS
# ==========================================
if st.session_state.page == "home":
    all_boxes_data = read_all_boxes(user_id, auth_token, pilihan_boks)
    st.markdown("# 🍱 iFOOX Dashboard")
    st.caption(f"Logged in as: **{user_email}**")
    st.divider()

    if not pilihan_boks:
        st.write("")
        st.write("")
        col_a, col_b, col_c = st.columns([1, 2, 1])
        with col_b:
            st.markdown("""
            <div style="text-align: center; padding: 30px; border: 2px dashed #3286c8; border-radius: 16px; background-color: rgba(50, 134, 200, 0.05);">
                <h2 style="margin-bottom: 10px;">📦 Belum Ada SmartBox</h2>
                <p style="color: gray; margin-bottom: 20px;">Tambahkan perangkat SmartBox pertama kamu untuk mulai memantau kualitas makanan berbasis AI.</p>
            </div>
            """, unsafe_allow_html=True)
            st.write("")
            
            with st.form("form_tambah_box_utama"):
                st.subheader("➕ Tambah SmartBox Baru")
                input_box_baru = st.text_input("Masukkan ID SmartBox (misal: box_01, box_02)", placeholder="box_01")
                btn_simpan_utama = st.form_submit_button("➕ Tambah SmartBox", type="primary", use_container_width=True)
                
                if btn_simpan_utama:
                    clean_id = input_box_baru.strip()
                    if clean_id:
                        add_user_box_id(user_id, clean_id, auth_token)
                        st.session_state.target_box = clean_id
                        st.success(f"Berhasil menambahkan {clean_id}!")
                        st.rerun()
                    else:
                        st.warning("Mohon isi ID SmartBox terlebih dahulu.")
    else:
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
        c2.metric("Online", sum(1 for s in statuses if s != "Offline"))
        c3.metric("Perlu Perhatian", sum(1 for s in statuses if s in ("Segera konsumsi", "Tidak disarankan", "Basi / Rawan")))
        
        st.write("")
        col_title, col_btn_add = st.columns([3, 1])
        with col_title:
            st.subheader("Daftar SmartBox")
            
        with col_btn_add:
            with st.popover("➕ Tambah Boks Baru", use_container_width=True):
                st.write("### Tambah SmartBox")
                input_pop = st.text_input("ID SmartBox", key="pop_input_box")
                if st.button("Simpan Boks", type="primary", use_container_width=True):
                    clean_pop = input_pop.strip()
                    if clean_pop:
                        add_user_box_id(user_id, clean_pop, auth_token)
                        st.session_state.target_box = clean_pop
                        st.rerun()

        cols = st.columns(min(len(pilihan_boks), 3), gap="medium")
        for i, b_id in enumerate(pilihan_boks):
            b_data = all_boxes_data.get(b_id, {}) or {}
            b_cfg = b_data.get("config", {}) or {}
            temp = float(b_data.get("suhu_c", 0) or 0)
            rh = float(b_data.get("kelembapan_rh", 0) or 0)
            gas = float(b_data.get("kadar_gas_ppm", 0) or 0)

            if gas == 0 and temp == 0:
                status, color = "Offline", "#89939b"
            elif not b_cfg.get("is_saved", False):
                status, color = "Kosong", "#3286c8"
            else:
                ai_status = b_cfg.get("last_status", "Aman")
                color = "#1c9a6c" if ai_status == "Aman" else ("#d99a19" if ai_status == "Segera konsumsi" else "#d64a4a")
                status = ai_status

            with cols[i % 3]:
                st.markdown(f"""
                <div class="box-summary">
                  <h4>📦 SmartBox #{b_id}</h4>
                  <p style="color:{color}; font-weight:bold; font-size:16px;">● {status}</p>
                  <p style="font-size:13px; color:gray;">🌡️ {temp:.1f}°C &nbsp;|&nbsp; 💧 {rh:.1f}% &nbsp;|&nbsp; 🧪 {gas:.0f} PPM</p>
                </div>
                """, unsafe_allow_html=True)

                sisa = b_cfg.get("last_sisa_jam", 0)
                maksimum = b_cfg.get("last_max_jam", 24)
                progress = max(0.0, min(1.0, float(sisa) / max(1.0, float(maksimum)))) if b_cfg.get("is_saved", False) else 0.0
                st.progress(progress)
                st.button(f"Buka Box #{b_id}", key=f"open_{b_id}", on_click=buka_detail_box, args=(b_id,), use_container_width=True)

    st.stop()


# ==========================================
# ⚙️ SIDEBAR MANAGEMENT
# ==========================================
st.sidebar.markdown(f"👤 **{user_email}**")

if st.sidebar.button("🚪 Keluar", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.user_info = None

    # Menggunakan try-except agar hapus cookie tidak memicu KeyError jika cookie sudah tidak ada[cite: 14]
    try:
        cookie_manager.delete("ifoox_refresh_token", key="del_cookie_token")
    except Exception:
        pass

    try:
        cookie_manager.delete("ifoox_user_email", key="del_cookie_email")
    except Exception:
        pass

    st.rerun()

st.sidebar.divider()

if st.sidebar.button("🏠 Homepage Overview", use_container_width=True):
    st.session_state.page = "home"
    st.rerun()

if pilihan_boks:
    default_index = pilihan_boks.index(st.session_state.target_box) if st.session_state.target_box in pilihan_boks else 0
    radio_selected = st.sidebar.selectbox(
        "Pilih SmartBox Target:",
        pilihan_boks,
        index=default_index,
        format_func=lambda x: f"📦 SmartBox #{x}",
    )
    if radio_selected != st.session_state.target_box:
        st.session_state.target_box = radio_selected
        st.rerun()
    selected_box = st.session_state.target_box
else:
    selected_box = None

with st.sidebar.expander("⚙️ Kelola Perangkat Boks"):
    new_box_input = st.text_input("ID Boks Baru", key="input_new_box_id")
    if st.button("➕ Tambah Boks", use_container_width=True):
        clean_box_id = new_box_input.strip()
        if clean_box_id:
            add_user_box_id(user_id, clean_box_id, auth_token)
            st.session_state.target_box = clean_box_id
            st.rerun()

    if pilihan_boks:
        st.write("---")
        box_to_delete = st.selectbox("Pilih Boks Hapus:", pilihan_boks, key="select_delete_box")
        if st.button("🗑️ Hapus Boks Ini", use_container_width=True):
            delete_user_box_id(user_id, box_to_delete, auth_token)
            sisa_box = [b for b in pilihan_boks if b != box_to_delete]
            st.session_state.target_box = sisa_box[0] if sisa_box else None
            st.rerun()


# ==========================================
# 🍱 MAIN DASHBOARD DETIL BOKS (REAL-TIME FRAGMENT)
# ==========================================
if not selected_box:
    st.warning("⚠️ Belum ada SmartBox yang terdaftar. Tambahkan ID SmartBox pada menu di sidebar.")
    st.stop()

full_box_data = read_box_data(user_id, selected_box, auth_token)
box_config = full_box_data.get("config", {})

is_saved = box_config.get("is_saved", False)
saved_jenis = box_config.get("jenis_makanan", "Nasi & Karbohidrat")
saved_massa = box_config.get("massa_gram", 150)
saved_tgl_str = box_config.get("tgl_masuk", datetime.now(wib_tz).strftime("%Y-%m-%d"))
saved_jam_str = box_config.get("jam_pilihan_str", f"{datetime.now(wib_tz).hour:02d}:{(datetime.now(wib_tz).minute // 15) * 15:02d}")

st.title(f"📦 SmartBox #{selected_box}")

tab_monitor, tab_config = st.tabs(["📡 Sensor & Status AI", "📝 Konfigurasi Makanan"])

with tab_monitor:
    @st.fragment(run_every="3s")
    def render_live_sensor_and_ai():
        current_data = read_box_data(user_id, selected_box, auth_token)
        suhu_val = float(current_data.get("suhu_c", 0.0))
        rh_val = float(current_data.get("kelembapan_rh", 0.0))
        gas_val = float(current_data.get("kadar_gas_ppm", 0.0))
        slope_val = float(current_data.get("slope_gas", 0.0))

        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("Suhu", f"{suhu_val:.1f} °C")
        col_s2.metric("Kelembapan", f"{rh_val:.1f} %RH")
        col_s3.metric("Kadar Gas", f"{gas_val:.0f} PPM")
        col_s4.metric("Slope Pembusukan", f"{slope_val:.2f} PPM/m")
        st.caption(f"🔄 Real-time update dari ESP32 [{selected_box}] • {datetime.now(wib_tz).strftime('%H:%M:%S')} WIB")
        st.divider()

        if is_saved:
            now_wib = datetime.now(wib_tz)
            try:
                tgl_parsed = datetime.strptime(saved_tgl_str, "%Y-%m-%d").date()
            except Exception:
                tgl_parsed = now_wib.date()

            jam_h, jam_m = map(int, saved_jam_str.split(":"))
            waktu_gabung_wib = wib_tz.localize(datetime.combine(tgl_parsed, datetime.min.time().replace(hour=jam_h, minute=jam_m)))
            
            waktu_simpan_jam = max(0.0, (now_wib - waktu_gabung_wib).total_seconds() / 3600.0)

            opsi_makanan = ["Nasi & Karbohidrat", "Lauk Hewani", "Lauk Nabati", "Sayuran Olahan", "Buah Potong", "Kue & Penganan", "Olahan Susu & Santan"]
            payload_dict = {
                "suhu_c": suhu_val,
                "kelembapan_rh": rh_val,
                "massa_gram": saved_massa,
                "kadar_gas_ppm": gas_val,
                "waktu_simpan_jam": waktu_simpan_jam,
            }
            for item in opsi_makanan:
                payload_dict[f"jenis_makanan_{item}"] = 1 if saved_jenis == item else 0

            df_input = pd.DataFrame([payload_dict])
            if hasattr(model, "feature_names_in_"):
                df_input = df_input[model.feature_names_in_]

            status_prediksi = model.predict(df_input)[0]
            sisa_jam, max_jam = hitung_shelf_life(saved_jenis, waktu_simpan_jam, suhu_val, gas_val, slope_val, status_ai=status_prediksi)

            # Monotonic Decreasing
            last_sisa = box_config.get("last_sisa_jam", sisa_jam)
            if last_sisa > 0 and sisa_jam > last_sisa:
                sisa_jam = last_sisa

            # jika sisa jam matematika sudah habis (0 Jam), paksa status AI menjadi "Tidak disarankan"[cite: 13]
            if sisa_jam <= 0:
                status_prediksi = "Tidak disarankan"

            if box_config.get("last_status") != status_prediksi or box_config.get("last_sisa_jam") != sisa_jam:
                box_config["last_status"] = status_prediksi
                box_config["last_sisa_jam"] = sisa_jam
                box_config["last_max_jam"] = max_jam
                save_box_config(user_id, selected_box, box_config, auth_token)

            col_r1, col_r2 = st.columns([2, 1])
            with col_r1:
                if status_prediksi == "Aman":
                    st.success(f"### STATUS: {status_prediksi.upper()}\n🟢 Makanan masih segar dan aman dikonsumsi.")
                elif status_prediksi == "Segera konsumsi":
                    st.warning(f"### STATUS: {status_prediksi.upper()}\n⚠️ Kualitas mulai menurun, segera dihabiskan!")
                else:
                    st.error(f"### STATUS: TIDAK DISARANKAN / BASI\n🚨 Makanan terdeteksi BASI / Kadaluwarsa! Jangan dikonsumsi.")

            with col_r2:
                st.metric("Estimasi Sisa Umur", f"{sisa_jam} Jam", delta=f"Max: {max_jam} Jam")

            persentase_sisa = max(0.0, min(1.0, sisa_jam / max_jam)) if status_prediksi not in ("Tidak disarankan", "Basi / Rawan") else 0.0
            st.progress(persentase_sisa)
        else:
            st.info("💡 **SmartBox ini masih kosong.** Buka tab **📝 Konfigurasi Makanan** untuk mengisi data makanan.")

    render_live_sensor_and_ai()

with tab_config:
    opsi_makanan = ["Nasi & Karbohidrat", "Lauk Hewani", "Lauk Nabati", "Sayuran Olahan", "Buah Potong", "Kue & Penganan", "Olahan Susu & Santan"]
    idx_makanan = opsi_makanan.index(saved_jenis) if saved_jenis in opsi_makanan else 0

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        jenis_makanan = st.selectbox("Jenis Makanan", opsi_makanan, index=idx_makanan, disabled=is_saved)
        massa_gram = st.number_input("Berat Makanan (Gram)", min_value=10, max_value=2000, value=int(saved_massa), disabled=is_saved)

    with col_f2:
        try:
            tgl_parsed = datetime.strptime(saved_tgl_str, "%Y-%m-%d").date()
        except Exception:
            tgl_parsed = datetime.now(wib_tz).date()

        tgl_masuk = st.date_input("Tanggal Penyimpanan", value=tgl_parsed, disabled=is_saved)
        list_jam = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 15)]
        idx_default = list_jam.index(saved_jam_str) if saved_jam_str in list_jam else 0
        jam_pilihan_str = st.selectbox("Jam Penyimpanan", list_jam, index=idx_default, disabled=is_saved)

    st.write("")
    if not is_saved:
        if st.button("💾 Simpan & Kunci Makanan", type="primary", use_container_width=True):
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
        st.success("🔒 Form Terkunci (Makanan sedang dipantau)")
        if st.button("🗑️ Kosongkan Boks Ini", use_container_width=True):
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
