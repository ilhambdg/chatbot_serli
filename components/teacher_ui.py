import streamlit as st
import services as svc
import state_management as sm

def render_teacher_dashboard(render_ai_response_func) -> None:
  nama_admin = st.session_state.get("st_name", "Admin")
  id_admin = st.session_state.get("st_id", "00000")
  
  st.title("📊 Dasbor Pemantauan")
  st.markdown(f"### 👋 Selamat Datang, {nama_admin} (ID: {id_admin})")
  st.caption("Pantau perkembangan belajar dan interaksi siswa dengan Serli AI di sini.")
  st.divider()
  
  with st.sidebar:
    st.markdown(f"**Admin Aktif:** {nama_admin}")
    st.write("Di sini Anda bisa melihat log aktivitas belajar siswa.")
    st.divider()
    
    st.subheader("🔍 Riwayat Belajar Siswa")
    all_sheets = svc.gs_list_sheets()
    student_sheets = [s for s in all_sheets if "_" in s]

    selected_sheet = None
    if not student_sheets:
      st.info("Belum ada data riwayat belajar siswa.")
    else:
      selected_sheet = st.selectbox(
        "Pilih Siswa:", student_sheets,
        format_func=lambda x: x.replace("_", " ", 1)
      )
      if selected_sheet:
        st.divider()
        st.markdown("### 📁 Data Raw")
        with st.expander("Tampilkan Data Table", expanded=False):
          st.dataframe(svc.gs_read_sheet(selected_sheet), use_container_width=True)
                
    st.divider()
    if st.button("Log Out Dashboard", use_container_width=True):
      sm.reset_user_session()
      st.rerun()

  if selected_sheet:
    df_history = svc.gs_read_sheet(selected_sheet)
    c1, c2 = st.columns(2)
    c1.metric("Total Interaksi", f"{len(df_history)} Chat")
    fase_terakhir = df_history["Fase_SRL"].iloc[-1] if not df_history.empty else "Belum Mulai"
    c2.metric("Fase SRL Terakhir", fase_terakhir)

    nama_siswa = selected_sheet.replace("_", " ", 1)
    st.info(f"👤 Menampilkan riwayat belajar dari siswa: **{nama_siswa}**")

    st.divider()
    st.markdown("### 💬 History Chat Siswa")
    
    MAX_DISPLAY = 50
    for _, row in df_history.tail(MAX_DISPLAY).iterrows():
      st.caption(f"⏱️ {row['Timestamp']} | 🔄 Fase: {row['Fase_SRL']}")
      
      with st.chat_message("user", avatar="👤"):
        # === MODIFIKASI: Menambahkan nama siswa dengan format bold ===
        st.markdown(f"**{nama_siswa}**")
        st.markdown(row["Input_Siswa"])
          
      with st.chat_message("assistant", avatar="✨"):
        render_ai_response_func(row["Jawaban_Serli"])