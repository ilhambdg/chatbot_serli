import json
import requests
import pandas as pd
import datetime
from zoneinfo import ZoneInfo
from langchain_groq import ChatGroq
import streamlit as st
from config import GROQ_API_KEY, APPS_SCRIPT_URL, logger

@st.cache_resource(show_spinner=False)
def get_llm_client() -> ChatGroq:
  return ChatGroq(
    groq_api_key=GROQ_API_KEY,
    model_name="llama-3.3-70b-versatile",
    temperature=0.7,
    max_retries=2,
    request_timeout=30,
  )

@st.cache_resource(show_spinner=False)
def get_eval_client() -> ChatGroq:
  return ChatGroq(
    groq_api_key=GROQ_API_KEY,
    model_name="llama-3.3-70b-versatile",
    temperature=0.0,
    max_retries=1,
    request_timeout=10,
  )

@st.cache_resource(show_spinner=False)
def get_http_session() -> requests.Session:
  session = requests.Session()
  adapter = requests.adapters.HTTPAdapter(
    pool_connections=2, pool_maxsize=5,
    max_retries=requests.adapters.Retry(total=2, backoff_factor=0.3)
  )
  session.mount("https://", adapter)
  session.mount("http://", adapter)
  return session

http = get_http_session()

@st.cache_data(ttl=15, show_spinner=False)
def gs_list_sheets() -> list[str]:
  try:
    r = http.get(APPS_SCRIPT_URL, params={"action": "list"}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "ok":
      return data.get("sheets", [])
  except Exception as e:
    logger.warning("gs_list_sheets error: %s", e)
  return []

@st.cache_data(ttl=20, show_spinner=False)
def gs_read_sheet(sheet_name: str) -> pd.DataFrame:
  fallback_cols = ["Timestamp", "Fase_SRL", "Input_Siswa", "Jawaban_Serli"]
  try:
    r = http.get(APPS_SCRIPT_URL, params={"action": "read", "sheet": sheet_name}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "ok" and data.get("data"):
      df = pd.DataFrame(data["data"])
      for col in fallback_cols:
        if col not in df.columns:
          df[col] = ""
      return df[fallback_cols + [c for c in df.columns if c not in fallback_cols]]
  except Exception as e:
    logger.warning("gs_read_sheet error: %s", e)
  return pd.DataFrame(columns=fallback_cols)

def gs_write_row(student_id: str, student_name: str, user_input: str, ai_response: str, phase: str) -> None:
  sheet_name = f"{student_id}_{student_name.replace(' ', '_').strip()}"
  timestamp = f"'{datetime.datetime.now(ZoneInfo('Asia/Jakarta')).strftime('%Y-%m-%d %H:%M:%S')}"
  payload = {
    "sheet": sheet_name, "timestamp": timestamp, "phase": phase,
    "input": user_input, "response": ai_response
  }
  try:
    r = http.post(APPS_SCRIPT_URL, json=payload, timeout=15)
    r.raise_for_status()
  except Exception as e:
    logger.warning("gs_write_row error: %s", e)

def get_safe_sheet_name(student_id: str, student_name: str) -> str:
  """Menghasilkan nama sheet seragam tanpa spasi berlebih untuk mencegah key error."""
  clean_name = student_name.strip().replace(" ", "_")
  return f"{student_id.strip()}_{clean_name}"