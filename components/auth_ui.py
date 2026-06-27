import streamlit as st
from config import TEACHER_ID, TEACHER_NAME, SRL_PHASES

def render_login_form() -> None:
  _, col, _ = st.columns([1, 2, 1])
  with col:
    st.markdown("<h1 style='text-align:center;'>✨ Serli AI</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;'>Self-Regulated Learning Assistant</p>", unsafe_allow_html=True)
    
    st_id = st.text_input("Index Siswa / ID Guru", key="input_login_id")
    st_name = st.text_input("Nama Lengkap", key="input_login_name")

    if st.button("Masuk Sesi", use_container_width=True):
      if st_id and st_name:
        is_teacher = (st_id.strip() == TEACHER_ID and st_name.strip().lower() == TEACHER_NAME.lower())
        st.session_state.update(
          logged_in=True, 
          st_id=st_id.strip(),
          role="Guru" if is_teacher else "Siswa",
          st_name=TEACHER_NAME if is_teacher else st_name.strip(),
          messages=[], 
          chat_count_in_phase=0, 
          phase=SRL_PHASES[0],
          phase_scores={p: 0.0 for p in SRL_PHASES}
        )
        st.rerun()
      else:
        st.error("Mohon isi ID dan Nama Lengkap Anda.")