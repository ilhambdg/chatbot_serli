import gc
import json
import streamlit as st
from config import (
  SRL_PHASES, MAX_HISTORY, MAX_CHAT_PER_PHASE, 
  MIN_CHAT_FOR_LLM_TRIGGER, PHASE_SCORE_THRESHOLD, logger
)
from services import get_eval_client

def init_session_state() -> None:
  defaults = {
    "logged_in": False,
    "role": "Siswa",
    "messages": [],
    "phase": SRL_PHASES[0],
    "st_id": "",
    "st_name": "",
    "chat_count_in_phase": 0,
    "phase_scores": {p: 0.0 for p in SRL_PHASES},
  }
  for key, val in defaults.items():
    if key not in st.session_state:
      st.session_state[key] = val

def trim_history() -> None:
  max_elements = MAX_HISTORY * 2
  if len(st.session_state.messages) > max_elements:
    st.session_state.messages = st.session_state.messages[-max_elements:]
    gc.collect()

def get_phase_index(phase: str) -> int:
  try:
    return SRL_PHASES.index(phase)
  except ValueError:
    return -1

def trigger_next_phase(reason: str) -> None:
  current_idx = get_phase_index(st.session_state.phase)
  next_idx = current_idx + 1

  if next_idx < len(SRL_PHASES):
    next_phase = SRL_PHASES[next_idx]
    st.session_state.phase = next_phase
    st.session_state.chat_count_in_phase = 0
    st.session_state.phase_scores[next_phase] = 0.0
    logger.info("Fase Naik: %s -> %s | Alasan: %s", SRL_PHASES[current_idx], next_phase, reason)
    st.toast(f"✅ Fase berpindah ke **{next_phase}**", icon="🎓")

def evaluate_phase_progression(current_phase: str) -> dict:
  recent = st.session_state.messages[-4:]
  if not recent:
    return {"progress_increment": 0.0, "reason": "no_chat"}

  context_lines = [f"{'Siswa' if m['role'] == 'user' else 'Asisten'}: {m['content'][:300]}" for m in recent]
  formatted_context = "\n".join(context_lines)

  prompt = f"""Kamu adalah sistem evaluasi SRL (Self-Regulated Learning).
  Nilai apakah siswa sudah MEMENUHI kriteria untuk fase aktif saat ini.

  Fase aktif sekarang: "{current_phase}"

  Kriteria Kelulusan Umum:
  - Jika fase mengandung kata 'Forethought' atau 'Perencanaan': Siswa harus menetapkan tujuan atau membuat rencana belajar.
  - Jika fase mengandung kata 'Performance' atau 'Aksi': Siswa harus sedang mengerjakan soal, mencoba menjawab, atau menunjukkan progres latihan matematika.
  - Jika fase mengandung kata 'Self-Reflection' atau 'Refleksi': Siswa harus mengevaluasi hasil kerja, membuat kesimpulan materi, atau menilai pemahamannya sendiri.

  Konteks 2 turn chat terakhir:
  {formatted_context}

  Balas HANYA dengan format JSON mentah tanpa markdown, contoh: {{"progress_increment": 1.0, "reason": "menetapkan tujuan belajar"}}
  Jika belum memenuhi kriteria, berikan progress_increment sebesar 0.0."""

  try:
    eval_client = get_eval_client()
    response = eval_client.invoke(prompt)
    clean = response.content.strip().lstrip("```json").rstrip("```").strip()
    result = json.loads(clean)
    result["progress_increment"] = float(result.get("progress_increment", 0.0))
    return result
  except Exception as e:
    logger.warning("Error Evaluator: %s", e)
    return {"progress_increment": 0.0, "reason": "error"}

def update_srl_state_machine() -> None:
  st.session_state.chat_count_in_phase += 1
  current_phase = st.session_state.phase

  if st.session_state.chat_count_in_phase >= MAX_CHAT_PER_PHASE:
    trigger_next_phase(reason="batas_maksimum_chat_tercapai")
    return

  if st.session_state.chat_count_in_phase < MIN_CHAT_FOR_LLM_TRIGGER:
    return

  eval_result = evaluate_phase_progression(current_phase)
  st.session_state.phase_scores[current_phase] += eval_result["progress_increment"]

  if st.session_state.phase_scores[current_phase] >= PHASE_SCORE_THRESHOLD:
    trigger_next_phase(reason=eval_result.get("reason", "kriteria_terpenuhi"))

import gc

def reset_user_session() -> None:
  keys_to_reset = ["logged_in", "role", "messages", "st_id", "st_name", "chat_count_in_phase"]
  for key in keys_to_reset:
    if key in st.session_state:
      if isinstance(st.session_state[key], list):
        st.session_state[key] = []
      elif isinstance(st.session_state[key], bool):
        st.session_state[key] = False
      else:
        st.session_state[key] = ""
              
  st.session_state.phase_scores = {p: 0.0 for p in SRL_PHASES}
  st.session_state.phase = SRL_PHASES[0]
  gc.collect()