import html
import os
import re
import time
import urllib.parse
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st
from filelock import FileLock

# =====================================================================
#  CONFIG
# =====================================================================
st.set_page_config(page_title="Kia Bodyshop", layout="wide", page_icon="🚗", initial_sidebar_state="collapsed")

BRAND = "Kia"
BRAND_HI = "किआ"

DB_FILE = "claim_database.csv"
GUARD_FILE = "guard_entry.csv"
DB_LOCK = "claim_database.csv.lock"
GUARD_LOCK = "guard_entry.csv.lock"

# NOTE: kept exactly as before so the shared link keeps working. Update it if you move the app.
WEB_URL = "https://mahendra-bodyshop-pnzpwm5nbeok4x5usgtntb.streamlit.app/"


def get_secret(key, default):
    """Read credentials from .streamlit/secrets.toml if present, else use the default."""
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return default


# Set GUARD_PINS (comma separated) and ADMIN_PASSWORD in Streamlit secrets to override.
GUARD_PINS = [p.strip() for p in get_secret("GUARD_PINS", "krishna,0000").split(",") if p.strip()]
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "admin123")
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 60


def get_india_time():
    return datetime.now(pytz.timezone("Asia/Kolkata"))


def ts_string(dt):
    return f"{dt.strftime('%Y-%m-%d')} at {dt.strftime('%I:%M %p')}"


def esc(value):
    """Escape any user-entered text before it is placed inside HTML."""
    return html.escape(str(value if value is not None else ""))


def clean_text(value):
    v = str(value if value is not None else "").strip()
    return "" if v.lower() in ("nan", "none") else v


def normalize_car(value):
    """MH12AB1234 style: upper-case, no spaces/dashes."""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


for key, default in {
    "logged_in": False,
    "guard_logged_in": False,
    "login_fails": 0,
    "locked_until": 0.0,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# =====================================================================
#  CSS STYLES
# =====================================================================
st.markdown("""
    <style>
    .stApp { background-color: #f8f9fa; }
    .customer-card {
        background: white; padding: 25px; border-radius: 20px;
        box-shadow: 0px 8px 25px rgba(0,0,0,0.1); border-left: 10px solid #1E88E5;
        margin-top: 20px;
    }
    
    .stepper-wrapper {
        display: flex; justify-content: space-between; margin-top: 30px; margin-bottom: 30px; position: relative;
    }
    .stepper-item {
        position: relative; display: flex; flex-direction: column; align-items: center; flex: 1; z-index: 2;
    }
    .stepper-item::before {
        position: absolute; content: ""; border-bottom: 2px solid #e0e0e0; width: 100%; top: 11px; left: -50%; z-index: 1;
    }
    .stepper-item::after {
        position: absolute; content: ""; border-bottom: 2px solid #e0e0e0; width: 100%; top: 11px; left: 50%; z-index: 1;
    }
    .stepper-item .step-counter {
        position: relative; z-index: 5; display: flex; justify-content: center; align-items: center;
        width: 22px; height: 22px; border-radius: 50%; background: #fff; border: 2px solid #e0e0e0;
        margin-bottom: 6px; color: #ccc; font-weight: bold; font-size: 10px; transition: all 0.4s ease;
    }
    .stepper-item.completed .step-counter { 
        background-color: #28a745; border-color: #28a745; color: white;
        box-shadow: 0 0 8px rgba(40,167,69,0.3); 
    }
    .stepper-item.completed::after, .stepper-item.completed::before { border-bottom: 2px solid #28a745; }
    .stepper-item:first-child::before, .stepper-item:last-child::after { content: none; }
    .step-name { font-size: 8px; color: #888; text-align: center; font-weight: 600; text-transform: uppercase; line-height: 1.2; }
    .stepper-item.completed .step-name { color: #28a745; }

    div[data-baseweb="select"] input {
        caret-color: transparent !important;
        pointer-events: none !important;
    }
    .status-time {
        font-size: 13px; color: #1565C0; font-weight: bold; margin-bottom: 5px;
    }
    .delivery-ready-card {
        background: linear-gradient(135deg, #ffffff 0%, #f1f8e9 100%);
        padding: 30px; border-radius: 25px; border: 3px solid #28a745; 
        text-align: center; box-shadow: 0px 10px 30px rgba(40, 167, 69, 0.2);
    }
    .main-header {
        background: linear-gradient(135deg, #1E88E5 0%, #1565C0 100%);
        color: white; padding: 20px; border-radius: 15px; text-align: center; margin-bottom: 20px;
    }
    .disclaimer-box {
        background-color: #fdf2f2; border: 1px solid #f8d7da; color: #721c24;
        padding: 15px; border-radius: 10px; font-size: 13px; margin-bottom: 20px;
        text-align: center; line-height: 1.6;
    }
    .section-header {
        background-color: #ffffff; color: #333; padding: 12px;
        border-radius: 10px; margin: 25px 0 10px 0;
        font-weight: bold; font-size: 18px; border-left: 5px solid #1E88E5;
    }
    .advisor-header {
        background-color: #e3f2fd; color: #0d47a1; padding: 8px;
        border-radius: 5px; margin: 10px 0; font-weight: bold; font-size: 16px;
    }
    .note-box {
        background-color: #fff9c4; color: #5d4037; padding: 15px;
        border-radius: 10px; border-left: 5px solid #fbc02d; margin-top: 15px;
    }
    .next-step-box {
        background-color: #f1f8e9; border: 1px dashed #28a745;
        padding: 8px 15px; border-radius: 8px; margin-top: 10px; font-size: 14px;
    }
    .stButton>button { width: 100%; height: 3.5em; border-radius: 12px; font-weight: bold; }
    div.stFormSubmitButton > button {
        background-color: #28a745 !important;
        color: white !important;
    }
    .footer-text {
        color: #777; font-size: 14px; margin-top: 50px;
    }
    input[type="password"] {
        letter-spacing: 0.5em;
        text-align: center;
        font-size: 24px;
    }
    </style>
    """, unsafe_allow_html=True)

# =====================================================================
#  CONSTANTS
# =====================================================================
VEHICLE_MODELS = [
    "Select Model",
    # --- Current / recent models sold in India ---
    "Sonet", "Seltos", "Syros", "Carens", "Carens Clavis", "Carens Clavis EV",
    "Carnival", "Carnival Limousine", "EV6", "EV9",
    # --- Other Kia global models ---
    "Picanto", "Morning", "Ray", "Ray EV", "Rio", "Stonic", "Soul", "Soul EV",
    "K3 / Forte / Cerato", "K4", "K5 / Optima", "K8", "K9", "Stinger",
    "Niro", "Niro EV", "Seltos (Global)", "Sportage", "Sorento", "Mohave / Borrego",
    "Telluride", "Sedona", "Venga", "Cadenza", "Carens (Global)",
    "EV3", "EV4", "EV5", "EV9 (Global)", "PV5", "Tasman", "Bongo", "Other Kia Model",
]

MAIN_SEQUENCE = ["Car Received", "Claim Intimation", "Insurance Survey", "Insurance Approval", "Dismantle", "Denting", "Painting", "Fitting", "Delivery Order Waiting from Insurance Company", "Final Delivery"]
STATUS_LIST = ["Car Received", "Claim Intimation", "Insurance Survey", "Insurance Approval", "WCA - Waiting for Customer Approval", "Claim Rejected", "PNA - Part Not Available", "WIP - Work Started", "Dismantle", "Denting", "Painting", "Fitting", "Delivery Order Waiting from Insurance Company", "Final Delivery"]

FRONT_STATUSES = ["Car Received", "Claim Intimation", "Insurance Survey", "Insurance Approval", "WCA - Waiting for Customer Approval", "Claim Rejected"]
WORKSHOP_STATUSES = ["WIP - Work Started", "Dismantle", "Denting", "Painting", "Fitting", "PNA - Part Not Available"]
READY_STATUSES = ["Delivery Order Waiting from Insurance Company", "Final Delivery"]

APPROVAL_INDEX = STATUS_LIST.index("Insurance Survey")

STEPPER_STEPS = ["Received", "Intimation", "Survey", "Approval", "Repairing", "Denting", "Painting", "Fitting", "DO Wait", "Ready"]
STEPPER_MAP = {
    "Car Received": 1, "Claim Intimation": 2, "Insurance Survey": 3, "Insurance Approval": 4,
    "WCA - Waiting for Customer Approval": 4, "WIP - Work Started": 5, "Dismantle": 5,
    "Denting": 6, "Painting": 7, "Fitting": 8, "PNA - Part Not Available": 8,
    "Delivery Order Waiting from Insurance Company": 9, "Final Delivery": 10,
}

BASE_COLS = ["Car Number", "Customer Name", "Service Advisor", "Status", "Delivery Date", "Message", "Last Update", "Remark Update TS"]
TRACKING_COLS = [f"Date_{s.split(' - ')[0]}" for s in STATUS_LIST]
ALL_COLS = BASE_COLS + TRACKING_COLS
GUARD_COLS = ["Car Number", "Vehicle Model", "Kilometer", "Entry Date", "Entry Time"]

STATUS_DETAILS = {
    "Car Received": "We have received your vehicle. The next step will be the registration of your motor insurance claim / आपकी गाड़ी हमें प्राप्त हो गई है। अगले चरण में आपकी गाड़ी का बीमा क्लेम दर्ज किया जाएगा।",
    "Claim Intimation": "Your insurance claim has been successfully registered. A surveyor will visit our workshop within 24 hours to inspect your vehicle. / आपका बीमा क्लेम सफलतापूर्वक दर्ज कर लिया गया है। अगले 24 घंटों के अंदर इंश्योरेंस सर्वेयर हमारी वर्कशॉप पर आपकी गाड़ी चेक करने आएंगे।",
    "Insurance Survey": "The vehicle inspection by the insurance surveyor has been completed. We are now awaiting the official work approval to start the repairs. / बीमा सर्वेयर द्वारा गाड़ी का निरीक्षण पूरा कर लिया गया है। अब हम मरम्मत कार्य शुरू करने के लिए आधिकारिक मंजूरी (Approval) का इंतज़ार कर रहे हैं।",
    "Insurance Approval": "Work approval has been received from the surveyor. / आपकी गाड़ी का वर्क अप्रूवल सर्वेयर से प्राप्त हो गया है।",
    "WCA - Waiting for Customer Approval": "To proceed with your vehicle's repair, your confirmation is required. We request you to kindly get in touch with our service advisor or visit the garage to authorize the process. / आपकी गाड़ी की मरम्मत शुरू करने के लिए आपकी पुष्टि (Confirmation) ज़रूरी है। आपसे अनुरोध है कि कृपया हमारे सर्विस एडवाइजर से बात करें या गैराज पर संपर्क करें ताकि हम काम आगे बढ़ा सकें।",
    "Claim Rejected": "Claim has been rejected by the insurance company. Please pick up your vehicle from the garage or go with the cash work to repair your vehicle. / बीमा कंपनी द्वारा क्लेम निरस्त कर दिया गया है। कृपया गैरेज से अपनी गाड़ी ले जाएं या अपनी गाड़ी की मरम्मत के लिए नकद कार्य (Cash Work) के साथ आगे बढ़ें।",
    "PNA - Part Not Available": "Certain parts required for your vehicle are currently on order. Work will resume immediately upon their arrival. We apologize for the delay. / आपकी गाड़ी के लिए कुछ ज़रूरी पार्ट्स ऑर्डर किए गए हैं। उनके आते ही मरम्मत का काम तुरंत दोबारा शुरू कर दिया जाएगा। देरी के लिए हमें खेद है।",
    "WIP - Work Started": "Repair work has started on your vehicle. / आपकी गाड़ी में मरम्मत का काम शुरू कर दिया गया हैं।",
    "Dismantle": "Your vehicle is currently undergoing dismantling for a detailed damage assessment and repair preparation. / आपकी गाड़ी की मरम्मत की तैयारी और नुकसान की बारीकी से जांच करने के लिए उसे डिस्मेंटल किया (खोला) जा रहा है।",
    "Denting": "Denting work is in progress. / आपकी गाड़ी का डेंटिंग कार्य चल रहा है।",
    "Painting": "Painting work is in progress. / आपकी गाड़ी का पेंटिंग कार्य चल रहा है।",
    "Fitting": "The major repairs are complete. Your vehicle is now undergoing final assembly and quality testing to ensure your safety on the road. / मुख्य मरम्मत का काम पूरा हो चुका है। सड़क पर आपकी सुरक्षा सुनिश्चित करने के लिए अब गाड़ी की फाइनल फिटिंग और क्वालिटी टेस्टिंग की जा रही है।",
    "Delivery Order Waiting from Insurance Company": "The repair work is complete, and we are currently awaiting the official Delivery Order (DO) from the insurance surveyor. Please note that the vehicle cannot be released without this mandatory document. For any updates regarding the DO, we kindly request you to contact your insurance surveyor directly, as the repairer has no authority in this matter. We appreciate your cooperation. / आपकी गाड़ी की मरम्मत का कार्य पूरा हो चुका है, और अब हमें बीमा सर्वेयर से आधिकारिक डिलीवरी ऑर्डर (DO) मिलने का इंतज़ार है। कृपया ध्यान दें कि इस अनिवार्य दस्तावेज़ के बिना गाड़ी हैंडओवर नहीं की जा सकती। डिलीवरी ऑर्डर (DO) के संबंध में किसी भी जानकारी के लिए कृपया सीधे अपने बीमा सर्वेयर से संपर्क करें, क्योंकि इसमें रिपेयरर (वर्कशॉप) का कोई अधिकार नहीं होता है। आपके सहयोग के लिए धन्यवाद।",
    "Final Delivery": "Your vehicle is ready for delivery! / आपकी गाड़ी डिलीवरी के लिए तैयार हैं!"
}


# =====================================================================
#  HELPERS
# =====================================================================
def is_status_approved(status):
    """Delivery date is only meaningful once the insurer has approved the claim."""
    if status == "Claim Rejected" or status not in STATUS_LIST:
        return False
    return STATUS_LIST.index(status) > APPROVAL_INDEX


def get_next_status(current):
    if current == "Claim Rejected":
        return "N/A (Claim Terminated)"
    if current == "Final Delivery":
        return "Completed / पूर्ण"
    if current == "WCA - Waiting for Customer Approval":
        return "Resuming Work (Post Approval)"
    if current == "PNA - Part Not Available":
        return "Resuming Work (Post Parts Arrival)"
    if current == "WIP - Work Started":
        return "Dismantle"
    if current in MAIN_SEQUENCE:
        idx = MAIN_SEQUENCE.index(current)
        if idx < len(MAIN_SEQUENCE) - 1:
            return MAIN_SEQUENCE[idx + 1]
    return "Next process update soon"


def _read_csv(path, cols):
    """Read a CSV safely: missing file / empty file / missing columns are all handled."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df.reset_index(drop=True)


def load_data():
    with FileLock(DB_LOCK):
        return _read_csv(DB_FILE, ALL_COLS)


def load_guard_data():
    with FileLock(GUARD_LOCK):
        return _read_csv(GUARD_FILE, GUARD_COLS)


def save_data(df):
    """Atomic write (temp file + replace) so a crash can never corrupt the database."""
    tmp = DB_FILE + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, DB_FILE)


def save_guard(df):
    tmp = GUARD_FILE + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, GUARD_FILE)


def update_car(car_number, status, delivery_date, remark):
    """Re-read inside the lock so two staff members never overwrite each other's edits."""
    with FileLock(DB_LOCK):
        df = _read_csv(DB_FILE, ALL_COLS)
        match = df.index[df["Car Number"] == car_number]
        if len(match) == 0:
            return False
        i = match[0]
        now_ts = get_india_time()
        approved = is_status_approved(status)
        df.at[i, "Status"] = status
        df.at[i, "Delivery Date"] = str(delivery_date) if approved else ""
        df.at[i, "Message"] = remark.strip()
        df.at[i, "Remark Update TS"] = ts_string(now_ts)
        df.at[i, "Last Update"] = now_ts.strftime("%Y-%m-%d")
        track_col = f"Date_{status.split(' - ')[0]}"
        if track_col in df.columns and not clean_text(df.at[i, track_col]):
            df.at[i, track_col] = now_ts.strftime("%Y-%m-%d")
        save_data(df)
    return True


def delete_car(car_number):
    with FileLock(DB_LOCK):
        df = _read_csv(DB_FILE, ALL_COLS)
        save_data(df[df["Car Number"] != car_number])


def check_lockout():
    remaining = st.session_state["locked_until"] - time.time()
    if remaining > 0:
        st.error(f"Too many wrong attempts. Try again in {int(remaining) + 1} seconds.")
        return True
    return False


def register_failed_login():
    st.session_state["login_fails"] += 1
    if st.session_state["login_fails"] >= MAX_LOGIN_ATTEMPTS:
        st.session_state["locked_until"] = time.time() + LOCKOUT_SECONDS
        st.session_state["login_fails"] = 0
        st.error(f"Too many wrong attempts. Locked for {LOCKOUT_SECONDS} seconds.")
    else:
        st.error("Wrong credentials!")


def build_stepper(status):
    current = STEPPER_MAP.get(status, 1)
    out = '<div class="stepper-wrapper">'
    for idx, name in enumerate(STEPPER_STEPS, 1):
        done = "completed" if idx <= current else ""
        icon = "✓" if idx <= current else ""
        out += f'<div class="stepper-item {done}"><div class="step-counter">{icon}</div><div class="step-name">{name}</div></div>'
    return out + "</div>"


# =====================================================================
#  SIDEBAR / NAVIGATION
# =====================================================================
st.sidebar.markdown(f"### 🛠️ {BRAND} Bodyshop")
menu = st.sidebar.radio("Navigation", ["Customer Portal / ग्राहक पोर्टल", "Guard Portal / गार्ड पोर्टल", "Staff Dashboard / स्टाफ"], index=0)

# =====================================================================
#  CUSTOMER PORTAL
# =====================================================================
if menu == "Customer Portal / ग्राहक पोर्टल":
    st.markdown("<div class='main-header'><h1>KIA BODYSHOP</h1><p>Check Status / गाड़ी का स्टेटस देखें</p></div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='disclaimer-box'><b>DISCLAIMER / अस्वीकरण:</b><br>"
        f"This website is managed by a third party to provide information regarding your vehicle's claim status. "
        f"This portal has no direct affiliation with {BRAND} Company or {BRAND} Dealership.<br>"
        f"<i>यह वेबसाइट आपकी गाड़ी के क्लेम स्टेटस की जानकारी देने के लिए एक थर्ड पार्टी द्वारा मैनेज की जा रही है। "
        f"इस पोर्टल का {BRAND_HI} कंपनी या {BRAND_HI} डीलरशिप से कोई सीधा संबंध नहीं है।</i></div>",
        unsafe_allow_html=True,
    )

    with st.form("status_form"):
        car_raw = st.text_input("Enter Full Vehicle Number")
        submitted = st.form_submit_button("Check Status")

    if submitted:
        car_input = normalize_car(car_raw)
        if len(car_input) < 4:
            st.warning("Please enter a valid vehicle number.")
        else:
            df = load_data()
            res = df[df["Car Number"].map(normalize_car) == car_input]
            if res.empty:
                st.error("❌ No record found.")
            for _, row in res.iterrows():
                status = row["Status"]
                car_no, owner, advisor = esc(row["Car Number"]), esc(row["Customer Name"]), esc(row["Service Advisor"])
                last_ts = esc(row["Remark Update TS"])
                details = STATUS_DETAILS.get(status, "Updating...")
                nxt = get_next_status(status)
                approved = is_status_approved(status)

                if status == "Final Delivery":
                    st.markdown(
                        f"<div class='delivery-ready-card'><div style='font-size:26px; font-weight:bold; color:#1b5e20;'>🎉 Congratulations! / बधाई हो!</div>"
                        f"<h2 style='margin:10px 0;'>🚗 {car_no}</h2><p style='font-size:18px;'>{details}</p>"
                        f"<p>Service Advisor: <b>{advisor}</b></p><p class='status-time'>Final Update: {last_ts}</p>"
                        f"<hr style='border: 0.5px solid #ccc;'><p style='font-size:20px; color:#28a745; font-weight:bold;'>✨ Delivery Date: {esc(row['Delivery Date'])}</p></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    delivery_html = ""
                    if status != "Claim Rejected":
                        if approved and clean_text(row["Delivery Date"]):
                            delivery_html = f"<p>Expected Delivery: <b>{esc(row['Delivery Date'])}</b></p>"
                        else:
                            delivery_html = ("<p style='margin-top:10px; font-size:14px; color:#d32f2f; background:#fff3e0; padding:10px; border-radius:8px; border-left:4px solid #f57c00;'>"
                                             "<b>Note:</b> The estimated delivery date can only be confirmed once approval is received from the insurance company.</p>")
                    st.markdown(
                        f"<div class='customer-card'><h2 style='margin:0;'>🚗 {car_no}</h2>"
                        f"<p>Owner: <b>{owner}</b> | Advisor: <b>{advisor}</b></p><p class='status-time'>🕒 Last Update: {last_ts}</p>"
                        f"{build_stepper(status)}<hr style='opacity:0.3;'><h3 style='color:#1E88E5;'>Current Status: {esc(status)}</h3>"
                        f"<div class='next-step-box'><b>Next Step:</b> {esc(status)} ➔ <span style='color:#1565C0;'>{esc(nxt)}</span></div>"
                        f"<p style='margin-top:15px; font-size:16px; color:#333; background:#e3f2fd; padding:15px; border-radius:10px;'>{details}</p>{delivery_html}</div>",
                        unsafe_allow_html=True,
                    )

                msg = clean_text(row["Message"])
                if msg:
                    st.markdown(f"<div class='note-box'><b>Workshop Remarks:</b><br>\"{esc(msg)}\"</div>", unsafe_allow_html=True)

# =====================================================================
#  GUARD PORTAL
# =====================================================================
elif menu == "Guard Portal / गार्ड पोर्टल":
    if not st.session_state["guard_logged_in"]:
        st.markdown("<div class='main-header'><h1>🛡️ GUARD ACCESS</h1><p>Enter Quick PIN</p></div>", unsafe_allow_html=True)
        _, col_pin, _ = st.columns([1, 2, 1])
        with col_pin:
            if not check_lockout():
                with st.form("guard_login"):
                    g_pin = st.text_input("Quick PIN", type="password", max_chars=20)
                    if st.form_submit_button("🚀 UNLOCK PORTAL"):
                        if g_pin.strip() in GUARD_PINS:
                            st.session_state["guard_logged_in"] = True
                            st.session_state["login_fails"] = 0
                            st.rerun()
                        else:
                            register_failed_login()
    else:
        col_name, col_logout = st.columns([3, 1])
        with col_name:
            st.markdown("### 🔓 Gate Portal Active")
        with col_logout:
            if st.button("🔒 Logout"):
                st.session_state["guard_logged_in"] = False
                st.rerun()

        st.markdown(f"<div class='main-header'><h1>GATE ENTRY FORM</h1><p>{BRAND} Bodyshop</p></div>", unsafe_allow_html=True)
        with st.form("guard_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            g_car = normalize_car(c1.text_input("Vehicle Number"))
            g_model = c2.selectbox("Vehicle Model", VEHICLE_MODELS)
            g_km = c3.text_input("Kilometer Reading").replace(",", "").strip()

            if st.form_submit_button("✅ SAVE & OPEN GATE"):
                if not (g_car and g_km and g_model != "Select Model"):
                    st.warning("Please fill all details and select a model.")
                elif len(g_car) < 4:
                    st.warning("Please enter a valid vehicle number.")
                elif not g_km.isdigit():
                    st.warning("Kilometer reading must be a number.")
                else:
                    now_ts = get_india_time()
                    new_e = pd.DataFrame([{
                        "Car Number": g_car, "Vehicle Model": g_model, "Kilometer": g_km,
                        "Entry Date": now_ts.strftime("%Y-%m-%d"), "Entry Time": now_ts.strftime("%I:%M %p"),
                    }])
                    with FileLock(GUARD_LOCK):
                        gdf = _read_csv(GUARD_FILE, GUARD_COLS)
                        save_guard(pd.concat([gdf, new_e], ignore_index=True))
                    st.balloons()
                    st.success(f"Entry Saved for {g_car}!")
                    time.sleep(1)
                    st.rerun()

        st.markdown("### 🕒 Recent Entries")
        gdf = load_guard_data()
        if gdf.empty:
            st.info("No entries yet.")
        else:
            for i, row in gdf.iloc[::-1].head(10).iterrows():
                with st.expander(f"🚗 {row['Car Number']} | {row['Vehicle Model']} | {row['Kilometer']} KM"):
                    st.write(f"Time: {row['Entry Time']} | Date: {row['Entry Date']}")
                    confirm = st.checkbox("Confirm delete", key=f"conf_{i}")
                    if st.button("🗑️ Delete Entry", key=f"del_{i}", disabled=not confirm):
                        with FileLock(GUARD_LOCK):
                            cur = _read_csv(GUARD_FILE, GUARD_COLS)
                            if i in cur.index:
                                save_guard(cur.drop(i))
                        st.warning("Entry Removed!")
                        time.sleep(0.5)
                        st.rerun()

# =====================================================================
#  STAFF DASHBOARD
# =====================================================================
else:
    if not st.session_state["logged_in"]:
        _, col_login, _ = st.columns([1, 2, 1])
        with col_login:
            if not check_lockout():
                with st.form("admin_login"):
                    pw = st.text_input("Password", type="password")
                    if st.form_submit_button("🔓 Login"):
                        if pw == ADMIN_PASSWORD:
                            st.session_state["logged_in"] = True
                            st.session_state["login_fails"] = 0
                            st.rerun()
                        else:
                            register_failed_login()
    else:
        if st.sidebar.button("🔒 Logout"):
            st.session_state["logged_in"] = False
            st.rerun()

        today_str = get_india_time().strftime("%Y-%m-%d")
        col_title, col_share = st.columns([3, 1])
        with col_title:
            st.markdown(f"## 📋 {BRAND} Staff Dashboard")
        with col_share:
            wa_msg = f"Dear sir! Aap apni gaadi ka status yahan check kar sakte hain: {WEB_URL}"
            wa_link = f"https://wa.me/?text={urllib.parse.quote(wa_msg)}"
            st.markdown(f"<a href='{wa_link}' target='_blank' style='background-color: #25D366; color: white; padding: 10px 15px; border-radius: 10px; text-decoration: none; font-weight: bold; display: inline-block; float: right; margin-top: 20px;'>📲 Share Portal Link</a>", unsafe_allow_html=True)

        df = load_data()
        t1, t2, t3 = st.tabs(["📄 View Records", "➕ Add New Car", "🛡️ Guard Records"])

        # ---------------- View Records ----------------
        with t1:
            search_input = normalize_car(st.text_input("Search Car", placeholder="Enter Car Number or last 4 digits...", label_visibility="collapsed"))
            if search_input:
                f_df = df[df["Car Number"].map(normalize_car).str.contains(search_input, regex=False)]
            else:
                f_df = df
            st.caption(f"Showing {len(f_df)} of {len(df)} records")

            def render_staff_expander(i, r, lock_sensitive=False):
                tick = " ✅" if str(r["Last Update"]) == today_str else ""
                car_key = r["Car Number"]
                with st.expander(f"🚗 {r['Car Number']} - {r['Status']}{tick}"):
                    with st.form(f"f_{i}"):
                        c_stat, c_date = st.columns([2, 1])
                        cur_idx = STATUS_LIST.index(r["Status"]) if r["Status"] in STATUS_LIST else 0
                        ns = c_stat.selectbox("Status", STATUS_LIST, index=cur_idx)
                        try:
                            default_date = datetime.strptime(r["Delivery Date"], "%Y-%m-%d").date()
                        except (ValueError, TypeError):
                            default_date = get_india_time().date()
                        nd = c_date.date_input("Delivery Date", value=default_date, key=f"date_{i}")
                        nm = st.text_area("Remark", value=clean_text(r["Message"]))
                        st.caption("Delivery date is saved only for statuses after Insurance Survey (approved claims).")
                        b1, b2 = st.columns(2)
                        do_update = b1.form_submit_button("Update ✅")
                        do_delete = (not lock_sensitive) and b2.form_submit_button("Delete 🗑️")
                        if do_update:
                            update_car(car_key, ns, nd, nm)
                            st.rerun()
                        if do_delete:
                            delete_car(car_key)
                            st.rerun()

            st.markdown("<div class='section-header'>🏢 FRONT OFFICE</div>", unsafe_allow_html=True)
            front_df = f_df[f_df["Status"].isin(FRONT_STATUSES)]
            if front_df.empty:
                st.caption("No cars here.")
            for advisor in front_df["Service Advisor"].unique():
                st.markdown(f"<div class='advisor-header'>👤 Advisor: {esc(advisor) or 'Unassigned'}</div>", unsafe_allow_html=True)
                for i, r in front_df[front_df["Service Advisor"] == advisor].iterrows():
                    render_staff_expander(i, r)

            st.markdown("<div class='section-header'>🔧 WORKSHOP FLOOR</div>", unsafe_allow_html=True)
            workshop_df = f_df[f_df["Status"].isin(WORKSHOP_STATUSES)]
            if workshop_df.empty:
                st.caption("No cars here.")
            for i, r in workshop_df.iterrows():
                render_staff_expander(i, r, lock_sensitive=True)

            st.markdown("<div class='section-header'>🏁 Ready</div>", unsafe_allow_html=True)
            ready_df = f_df[f_df["Status"].isin(READY_STATUSES)]
            if ready_df.empty:
                st.caption("No cars here.")
            for i, r in ready_df.iterrows():
                render_staff_expander(i, r)

        # ---------------- Add New Car ----------------
        with t2:
            with st.form("new_car", clear_on_submit=True):
                nc = normalize_car(st.text_input("Car Number"))
                nn = st.text_input("Customer Name").strip()
                sa = st.text_input("Advisor").strip()
                if st.form_submit_button("Save Car"):
                    if not (nc and nn):
                        st.warning("Car Number and Customer Name are required.")
                    else:
                        with FileLock(DB_LOCK):
                            cur = _read_csv(DB_FILE, ALL_COLS)
                            already = cur[(cur["Car Number"].map(normalize_car) == nc) & (~cur["Status"].isin(["Final Delivery", "Claim Rejected"]))]
                            if not already.empty:
                                st.error(f"{nc} is already in the system with an active claim.")
                            else:
                                now_ts = get_india_time()
                                new_data = {col: "" for col in ALL_COLS}
                                new_data.update({
                                    "Car Number": nc, "Customer Name": nn, "Service Advisor": sa, "Status": "Car Received",
                                    "Last Update": now_ts.strftime("%Y-%m-%d"), "Remark Update TS": ts_string(now_ts),
                                    "Date_Car Received": now_ts.strftime("%Y-%m-%d"),
                                })
                                save_data(pd.concat([cur, pd.DataFrame([new_data])], ignore_index=True))
                                st.success(f"{nc} Saved!")
                                time.sleep(1)
                                st.rerun()

        # ---------------- Guard Records ----------------
        with t3:
            st.markdown("### 🛡️ Guard Entry Logs")
            gdf = load_guard_data()
            g_search = normalize_car(st.text_input("Search Guard Records (Car No.)", key="g_search"))
            if gdf.empty:
                st.info("No guard entries found.")
            else:
                if g_search:
                    gdf = gdf[gdf["Car Number"].map(normalize_car).str.contains(g_search, regex=False)]
                if gdf.empty:
                    st.info("No matching entries.")
                for i, row in gdf.iloc[::-1].iterrows():
                    with st.expander(f"🚗 {row['Car Number']} | {row['Vehicle Model']} | {row['Kilometer']} KM | {row['Entry Date']} at {row['Entry Time']}"):
                        st.write(f"**Vehicle:** {row['Car Number']}")
                        st.write(f"**Model:** {row['Vehicle Model']}")
                        st.write(f"**KM Reading:** {row['Kilometer']}")
                        st.write(f"**Date:** {row['Entry Date']}")
                        st.write(f"**Time:** {row['Entry Time']}")

st.markdown(f"<br><center class='footer-text'><b>Engineered by Owais</b><br>{BRAND} Bodyshop Portal © 2026</center>", unsafe_allow_html=True)