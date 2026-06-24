import streamlit as st
from langchain_groq import ChatGroq
import pandas as pd
import datetime
import requests
import json
from zoneinfo import ZoneInfo
import gc
import logging

# ==========================================
# KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(
    page_title="Serli AI - Digital Assistant",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="auto",
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

GROQ_API_KEY    = st.secrets["GROQ_API_KEY"]
APPS_SCRIPT_URL = st.secrets["APPS_SCRIPT_URL"]

TEACHER_ID   = "12345"
TEACHER_NAME = "lutfianto"
MAX_HISTORY  = 20

# [BARU] Single source of truth untuk urutan fase.
# Tuple (immutable) agar tidak ada kode lain yang mengganti urutannya.
# Seluruh logika transisi cukup beroperasi pada indeks integer — tidak perlu
# hardcode string "Forethought ..." berulang kali di banyak tempat.
SRL_PHASES: tuple[str, ...] = (
    "Forethought (Perencanaan)",
    "Performance (Aksi)",
    "Self-Reflection (Refleksi)",
)

# Pemetaan dari nama teknis backend ke nama ramah pengguna di UI
PHASE_DISPLAY_MAP = {
    "Forethought (Perencanaan)" : "🎯 Rencana Belajar",
    "Performance (Aksi)" : "📝 Belajar & Latihan",
    "Self-Reflection (Refleksi)" : "🤔 Cek & Evaluasi",
}


# [BARU] Batas maksimum chat per fase sebelum auto-advance (rule-based O(1))
MAX_CHAT_PER_PHASE = 8

# [BARU] Skor akumulatif minimum agar LLM-path memicu transisi
PHASE_SCORE_THRESHOLD = 1.0

# [BARU] Minimum chat dalam fase sebelum LLM-path boleh memicu transisi
MIN_CHAT_FOR_LLM_TRIGGER = 2

# ==========================================
# CACHE RESOURCE: LLM CLIENT (chat) & EVAL CLIENT
# ==========================================
@st.cache_resource(show_spinner=False)
def init_llm_client(api_key: str) -> ChatGroq:
    return ChatGroq(
        groq_api_key=api_key,
        model_name="llama-3.3-70b-versatile",
        temperature=0.7,
        max_retries=2,
        request_timeout=30,
    )

# [BARU] Eval client berdiri sendiri di cache agar tidak re-instantiate
# setiap turn. Temperature=0 penting untuk konsistensi output JSON.
@st.cache_resource(show_spinner=False)
def init_eval_client(api_key: str) -> ChatGroq:
    return ChatGroq(
        groq_api_key=api_key,
        model_name="llama-3.3-70b-versatile",
        temperature=0.0,
        max_retries=1,
        request_timeout=10,
    )

llm_client  = init_llm_client(GROQ_API_KEY)
eval_client = init_eval_client(GROQ_API_KEY)    # [BARU]

# ==========================================
# SESSION HTTP (Connection Pooling)
# ==========================================
@st.cache_resource(show_spinner=False)
def get_http_session() -> requests.Session:
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=2,
        pool_maxsize=5,
        max_retries=requests.adapters.Retry(total=2, backoff_factor=0.3),
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

http = get_http_session()

# ==========================================
# GOOGLE SHEETS HELPERS (tidak diubah)
# ==========================================
@st.cache_data(ttl=15, show_spinner=False)
def gs_list_sheets() -> list[str]:
    try:
        r = http.get(APPS_SCRIPT_URL, params={"action": "list"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "ok":
            return data.get("sheets", [])
    except requests.exceptions.Timeout:
        st.warning("⚠️ Koneksi Google Sheets timeout.")
    except requests.exceptions.RequestException as e:
        logger.warning("gs_list_sheets error: %s", e)
    return []


@st.cache_data(ttl=20, show_spinner=False)
def gs_read_sheet(sheet_name: str) -> pd.DataFrame:
    _FALLBACK_COLS = ["Timestamp", "Fase_SRL", "Input_Siswa", "Jawaban_Serli"]
    try:
        r = http.get(
            APPS_SCRIPT_URL,
            params={"action": "read", "sheet": sheet_name},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "ok":
            rows = data.get("data", [])
            if rows:
                df = pd.DataFrame(rows)
                for col in _FALLBACK_COLS:
                    if col not in df.columns:
                        df[col] = ""
                return df[_FALLBACK_COLS + [c for c in df.columns if c not in _FALLBACK_COLS]]
            return pd.DataFrame(columns=_FALLBACK_COLS)
    except requests.exceptions.Timeout:
        st.warning(f"⚠️ Timeout membaca sheet '{sheet_name}'.")
    except requests.exceptions.RequestException as e:
        logger.warning("gs_read_sheet error: %s", e)
    return pd.DataFrame(columns=["Timestamp", "Fase_SRL", "Input_Siswa", "Jawaban_Serli"])


def gs_write_row(
    student_id: str,
    student_name: str,
    user_input: str,
    ai_response: str,
    phase: str,
) -> None:
    safe_name  = student_name.replace(" ", "_").strip()
    sheet_name = f"{student_id}_{safe_name}"
    timestamp  = f"'{datetime.datetime.now(ZoneInfo('Asia/Jakarta')).strftime('%Y-%m-%d %H:%M:%S')}"
    payload = {
        "sheet":     sheet_name,
        "timestamp": timestamp,
        "phase":     phase,
        "input":     user_input,
        "response":  ai_response,
    }
    try:
        r = http.post(APPS_SCRIPT_URL, json=payload, timeout=15)
        r.raise_for_status()
        result = r.json()
        if result.get("status") != "ok":
            st.warning(f"⚠️ Gagal menyimpan: {result.get('message')}")
    except requests.exceptions.Timeout:
        st.warning("⚠️ Timeout saat menyimpan ke Google Sheets.")
    except requests.exceptions.RequestException as e:
        logger.warning("gs_write_row error: %s", e)

# ==========================================
# HELPERS MEMORI & NAMA SHEET
# ==========================================
def trim_history() -> None:
    max_elements = MAX_HISTORY * 2
    if len(st.session_state.messages) > max_elements:
        st.session_state.messages = st.session_state.messages[-max_elements:]
        gc.collect()


def make_sheet_name(student_id: str, student_name: str) -> str:
    return f"{student_id}_{student_name.replace(' ', '_').strip()}"

# ==========================================
# [BARU] HELPER INDEKS FASE — O(1), tanpa perulangan string
# ==========================================
def _phase_index(phase: str) -> int:
    """Kembalikan indeks fase dalam SRL_PHASES. -1 jika tidak ditemukan."""
    try:
        return SRL_PHASES.index(phase)
    except ValueError:
        return -1

# ==========================================
# [BARU] EVALUATOR BERBASIS LLM — HEMAT TOKEN
# Hanya membaca 2 turn terakhir (max 4 pesan), temperature=0 untuk konsistensi.
# ==========================================
def evaluate_phase_progression(current_phase: str) -> dict:
    """
    Evaluasi apakah siswa sudah memenuhi kriteria fase saat ini.
    Hanya menggunakan 2 turn terakhir agar hemat token & latensi < 0.5 detik.

    Returns:
        dict dengan kunci:
          - progress_increment (float): 1.0 jika kriteria terpenuhi, 0.0 jika belum
          - reason (str)              : alasan singkat untuk logging
    """
    recent = st.session_state.messages[-4:]          # maks 2 turn (user+assistant)
    if not recent:
        return {"progress_increment": 0.0, "reason": "no_chat"}

    # Format ringkas — hindari mengirim seluruh teks panjang ke evaluator
    context_lines = []
    for msg in recent:
        role = "Siswa" if msg["role"] == "user" else "Asisten"
        # Potong tiap pesan ke 300 karakter; cukup untuk sinyal fase
        context_lines.append(f"{role}: {msg['content'][:300]}")
    formatted_context = "\n".join(context_lines)

    prompt = f"""Kamu adalah sistem evaluasi SRL (Self-Regulated Learning).
Nilai apakah siswa sudah MEMENUHI kriteria fase "{current_phase}".

Kriteria kelulusan:
- Forethought (Perencanaan) : Siswa menetapkan tujuan ATAU membuat rencana belajar.
- Performance (Aksi)        : Siswa mengerjakan soal, mencoba menjawab, atau menunjukkan progres latihan.
- Self-Reflection (Refleksi): Siswa mengevaluasi hasil, menyimpulkan materi, atau menilai dirinya sendiri.

Potongan chat (2 turn terakhir):
{formatted_context}

Balas HANYA dengan JSON, tanpa markdown, tanpa penjelasan tambahan:
{{"progress_increment": <1.0 jika terpenuhi, 0.0 jika belum>, "reason": "<alasan singkat max 10 kata>"}}"""

    try:
        response   = eval_client.invoke(prompt)
        clean      = response.content.strip().lstrip("```json").rstrip("```").strip()
        result     = json.loads(clean)
        # Validasi tipe agar tidak crash di accumulator
        result["progress_increment"] = float(result.get("progress_increment", 0.0))
        result["reason"]             = str(result.get("reason", ""))
        return result
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("evaluate_phase_progression parse error: %s", e)
        return {"progress_increment": 0.0, "reason": "parse_error"}
    except Exception as e:
        logger.warning("evaluate_phase_progression error: %s", e)
        return {"progress_increment": 0.0, "reason": "error"}

# ==========================================
# [BARU] TRIGGER TRANSISI FASE
# Dipisah dari state machine agar mudah di-test & di-log secara independen.
# ==========================================
def trigger_next_phase(reason: str) -> None:
    """
    Pindahkan fase ke tahap berikutnya jika masih ada.
    Reset counter & skor akumulatif untuk fase baru.
    Tampilkan toast informatif ke pengguna.
    """
    current_idx = _phase_index(st.session_state.phase)
    next_idx    = current_idx + 1

    if next_idx >= len(SRL_PHASES):
        # Sudah di fase terakhir — tidak ada transisi
        logger.info("trigger_next_phase: sudah di fase terakhir, skip.")
        return

    next_phase = SRL_PHASES[next_idx]
    st.session_state.phase                          = next_phase
    st.session_state.chat_count_in_phase            = 0
    st.session_state.phase_scores[next_phase]       = 0.0  # pastikan skor bersih

    logger.info("Fase naik: %s → %s | alasan: %s", SRL_PHASES[current_idx], next_phase, reason)
    st.toast(f"✅ Fase berpindah ke **{next_phase}**", icon="🎓")

# ==========================================
# [BARU] STATE MACHINE — AUTO TRIGGER FASE
# Menggabungkan dua jalur:
#   1. Rule-based O(1) : batas chat per fase (hard cap, anti-stuck)
#   2. LLM-based       : evaluasi semantik 2 turn terakhir
# ==========================================
def update_srl_state_machine() -> None:
    """
    Dipanggil sekali setiap selesai mendapatkan respons AI.
    Urutan evaluasi: rule-based dulu (lebih murah), baru LLM.
    """
    st.session_state.chat_count_in_phase += 1
    current_phase = st.session_state.phase

    # ── Jalur 1: Rule-based O(1) ────────────────────────────────────────────
    # Siswa tidak boleh stuck selamanya di satu fase.
    if st.session_state.chat_count_in_phase >= MAX_CHAT_PER_PHASE:
        trigger_next_phase(reason="batas_maksimum_chat_tercapai")
        return  # early-return; tidak perlu panggil LLM

    # ── Jalur 2: LLM Evaluator ───────────────────────────────────────────────
    # Hanya evaluasi jika sudah ada cukup chat (MIN_CHAT_FOR_LLM_TRIGGER).
    # Ini mencegah transisi terlalu cepat hanya dari 1 pesan pertama.
    if st.session_state.chat_count_in_phase < MIN_CHAT_FOR_LLM_TRIGGER:
        return

    eval_result = evaluate_phase_progression(current_phase)
    st.session_state.phase_scores[current_phase] += eval_result["progress_increment"]

    logger.debug(
        "Fase=%s | skor_akum=%.1f | increment=%.1f | alasan=%s",
        current_phase,
        st.session_state.phase_scores[current_phase],
        eval_result["progress_increment"],
        eval_result["reason"],
    )

    if st.session_state.phase_scores[current_phase] >= PHASE_SCORE_THRESHOLD:
        trigger_next_phase(reason=eval_result.get("reason", "kriteria_terpenuhi"))

# ==========================================
# HELPER RENDER OUTPUT AI
# ==========================================
def render_ai_response(text: str) -> None:
    lines  = text.split("\n")
    buffer: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped in ("---", "___", "***"):
            if buffer:
                st.markdown("\n".join(buffer))
                buffer = []
            st.markdown("---")
            continue
        if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
            if buffer:
                st.markdown("\n".join(buffer))
                buffer = []
            st.latex(stripped[2:-2])
            continue
        buffer.append(line)

    if buffer:
        st.markdown("\n".join(buffer))

# ==========================================
# INISIALISASI SESSION STATE — SATU TEMPAT
# [DIUBAH] Tambah kunci untuk dynamic phase: chat_count_in_phase & phase_scores
# ==========================================
_DEFAULTS: dict = {
    "logged_in":          False,
    "role":               "Siswa",
    "messages":           [],
    "phase":              SRL_PHASES[0],        # [DIUBAH] pakai SRL_PHASES, bukan string literal
    "st_id":              "",
    "st_name":            "",
    # [BARU] State machine SRL
    "chat_count_in_phase": 0,
    "phase_scores":        {p: 0.0 for p in SRL_PHASES},
}
for key, val in _DEFAULTS.items():
    if key not in st.session_state:
        # Pastikan phase_scores selalu memuat semua fase,
        # bahkan jika session lama belum punya kunci baru.
        if key == "phase_scores" and key in st.session_state:
            for p in SRL_PHASES:
                st.session_state.phase_scores.setdefault(p, 0.0)
        else:
            st.session_state[key] = val

# ==========================================
# HALAMAN LOGIN (tidak diubah)
# ==========================================
if not st.session_state.logged_in:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            "<h1 style='text-align:center;color:#60EFFF;'>✨ Serli AI</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align:center;'>Self-Regulated Learning Assistant</p>",
            unsafe_allow_html=True,
        )

        st_id   = st.text_input("Index Siswa / ID Guru")
        st_name = st.text_input("Nama Lengkap")

        if st.button("Masuk Sesi", use_container_width=True):
            if st_id and st_name:
                is_teacher = (
                    st_id.strip() == TEACHER_ID
                    and st_name.strip().lower() == TEACHER_NAME.lower()
                )
                st.session_state.update(
                    logged_in=True,
                    st_id=st_id.strip(),
                    role="Guru" if is_teacher else "Siswa",
                    st_name=TEACHER_NAME if is_teacher else st_name.strip(),
                    messages=[],
                    # [BARU] Reset state machine saat login baru
                    chat_count_in_phase=0,
                    phase=SRL_PHASES[0],
                    phase_scores={p: 0.0 for p in SRL_PHASES},
                )
                st.success("Login Guru Berhasil!" if is_teacher else "Login Siswa Berhasil!")
                st.rerun()
            else:
                st.error("Mohon isi ID dan Nama Lengkap Anda.")
    st.stop()

# ==========================================
# HALAMAN GURU (tidak diubah)
# ==========================================
if st.session_state.role == "Guru":
    st.title("📊 Dasbor Pemantauan")

    with st.sidebar:
        st.markdown(f"**User:** {st.session_state.st_name} (Guru)")

        st.write("Di sini Anda bisa melihat log aktivitas belajar siswa.")
        st.divider()

        st.subheader("🔍 Riwayat Belajar Siswa")
        all_sheets     = gs_list_sheets()
        student_sheets = [s for s in all_sheets if "_" in s]

        selected_sheet: str | None = None
        if not student_sheets:
            st.info("Belum ada data riwayat belajar siswa.")
        else:
            selected_sheet = st.selectbox(
                "Pilih Siswa:",
                student_sheets,
                format_func=lambda x: x.replace("_", " ", 1),
            )
            if selected_sheet:
                st.divider()
                st.markdown("### 📁 Data siswa")
                with st.expander("Tampilkan Data", expanded=False):
                    st.dataframe(gs_read_sheet(selected_sheet), use_container_width=True)
        st.divider()
        if st.button("Log Out"):
            st.session_state.logged_in = False
            st.rerun()

    if selected_sheet:
        df_history = gs_read_sheet(selected_sheet)

        col1, col2 = st.columns(2)
        col1.metric("Total Interaksi", f"{len(df_history)} Chat")
        fase_terakhir = (
            df_history["Fase_SRL"].iloc[-1] if not df_history.empty else "Belum Mulai"
        )
        col2.metric("Fase SRL Terakhir", fase_terakhir)

        st.divider()
        st.markdown("### 💬 History Chat")

        MAX_DISPLAY = 50
        display_df  = df_history.tail(MAX_DISPLAY)
        if len(df_history) > MAX_DISPLAY:
            st.caption(f"Menampilkan {MAX_DISPLAY} dari {len(df_history)} total.")

        for _, row in display_df.iterrows():
            st.caption(f"⏱️ {row['Timestamp']} | 🔄 Fase: {row['Fase_SRL']}")
            with st.chat_message("user", avatar="👤"):
                st.markdown(row["Input_Siswa"])
            with st.chat_message("assistant", avatar="✨"):
                st.markdown(row["Jawaban_Serli"])
            st.write("")

    st.stop()

# ==========================================
# HALAMAN SISWA — SIDEBAR
# [DIUBAH] Selector fase sekarang read-only progress indicator;
# perubahan manual masih bisa, tapi posisi default ditentukan state machine.
# ==========================================
with st.sidebar:
    st.title("📊 Panel Kontrol")
    st.markdown(f"**Siswa:** {st.session_state.st_name}")
    st.markdown(f"**ID:** {st.session_state.st_id}")
    st.divider()

    # [DIUBAH] Selector tetap ada untuk override manual guru/siswa,
    # tapi default-nya sekarang dikendalikan state machine (bukan hard-coded index)
    st.markdown("### Personalisasi Serli")
    current_idx = _phase_index(st.session_state.phase)
    selected_phase = st.selectbox(
        "Opsional:",
        SRL_PHASES,                             # [DIUBAH] dari literal list ke tuple terpusat
        index=max(current_idx, 0),
        format_func=lambda x: PHASE_DISPLAY_MAP.get(x, x),
    )

    # Jika guru/siswa override manual → reset counter & skor untuk fase baru
    if selected_phase != st.session_state.phase:
        st.session_state.phase                = selected_phase
        st.session_state.chat_count_in_phase  = 0
        st.session_state.phase_scores[selected_phase] = 0.0
        st.rerun()

    st.divider()
    st.markdown("### 📁 Arsip Data")

    my_sheet   = make_sheet_name(st.session_state.st_id, st.session_state.st_name)
    all_sheets = gs_list_sheets()

    if my_sheet in all_sheets:
        with st.expander("Riwayat Belajar", expanded=True):
            st.dataframe(gs_read_sheet(my_sheet), use_container_width=True)
    else:
        st.info("Belum ada riwayat belajar tersimpan.")

    st.divider()
    
    if st.button("Log out akun", use_container_width=True):
        for key in ["logged_in", "messages", "phase", "st_id", "st_name", "role",
                    "chat_count_in_phase", "phase_scores"]:     # [DIUBAH] tambah kunci baru
            st.session_state.pop(key, None)
        gc.collect()
        st.rerun()

# ==========================================
# HALAMAN SISWA — HEADER & CHAT UI (tidak diubah)
# ==========================================
st.title("✨ Serli - Asisten AI belajar mu")
st.caption(f"### Selamat datang {st.session_state.st_name}")
st.markdown("---")

if not st.session_state.messages:
    st.markdown(
        "Aku Serli. Mari kita mulai belajar **Fungsi Matematika**. "
        "Sebelum kita masuk ke materi, ceritakan dong apa target atau tujuan belajarmu hari ini?"
    )

visible_msgs = st.session_state.messages[-(MAX_HISTORY * 2):]
for msg in visible_msgs:
    with st.chat_message(msg["role"], avatar="👤" if msg["role"] == "user" else "✨"):
        if msg["role"] == "assistant":
            render_ai_response(msg["content"])
        else:
            st.markdown(msg["content"])

# ==========================================
# INTERAKSI CHAT — STREAMING + STATE MACHINE
# [DIUBAH] Tambah satu pemanggilan update_srl_state_machine() setelah respons AI
# ==========================================
if user_query := st.chat_input("Ketik pertanyaan atau progres belajarmu di sini..."):

    with st.chat_message("user", avatar="👤"):
        st.markdown(user_query)
    st.session_state.messages.append({"role": "user", "content": user_query})

    trim_history()

    system_prompt = (
        f"Anda adalah Serli AI, asisten Self-Regulated Learning. "
        f"Saat ini siswa berada pada fase: {st.session_state.phase}. "
        "Jawablah dengan edukatif, singkat, dan sesuai konteks fase tersebut."
    )
    api_messages = [{"role": "system", "content": system_prompt}] + [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]

    with st.chat_message("assistant", avatar="✨"):
        try:
            response_placeholder = st.empty()
            full_response        = ""

            for chunk in llm_client.stream(api_messages):
                full_response += chunk.content

                response_placeholder.markdown(full_response + "▌")


            response_placeholder.empty()
            render_ai_response(full_response)

        except Exception as e:
            full_response = "⚠️ Maaf, terjadi gangguan koneksi dengan Serli AI. Silakan coba lagi."
            st.error(full_response)
            logger.error("Gagal mendapatkan respons LLM: %s", e)

    st.session_state.messages.append({"role": "assistant", "content": full_response})

    gs_write_row(
        student_id=st.session_state.st_id,
        student_name=st.session_state.st_name,
        user_input=user_query,
        ai_response=full_response,
        phase=st.session_state.phase,
    )

    # [BARU] Satu baris ini yang menggerakkan seluruh state machine.
    # Dipanggil setelah respons AI tersimpan agar evaluator punya konteks lengkap.
    update_srl_state_machine()
