import streamlit as st
import logging

st.set_page_config(
  page_title="Serli AI - Digital Assistant",
  page_icon="✨",
  layout="wide",
  initial_sidebar_state="auto",
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("SerliAI")

GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
APPS_SCRIPT_URL = st.secrets["APPS_SCRIPT_URL"]

TEACHER_ID = "12345"
TEACHER_NAME = "lutfianto"
MAX_HISTORY = 20

SRL_PHASES: tuple[str, ...] = (
  "Forethought (Perencanaan)",
  "Performance (Aksi)",
  "Self-Reflection (Refleksi)",
)

PHASE_DISPLAY_MAP = {
  "Forethought (Perencanaan)": "🎯 Rencana Belajar",
  "Performance (Aksi)": "📝 Belajar & Latihan",
  "Self-Reflection (Refleksi)": "🤔 Cek & Evaluasi",
}

MAX_CHAT_PER_PHASE = 8
PHASE_SCORE_THRESHOLD = 1.0
MIN_CHAT_FOR_LLM_TRIGGER = 2