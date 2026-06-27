import streamlit as st
import services as svc
import state_management as sm
from config import SRL_PHASES, PHASE_DISPLAY_MAP, MAX_HISTORY

def render_student_chat(render_ai_response_func) -> None:
  with st.sidebar:
    st.title("📊 Panel Kontrol")
    st.markdown(f"**Siswa:** {st.session_state.st_name} | **ID:** {st.session_state.st_id}")
    st.divider()

    st.markdown("### Personalisasi Serli")
    current_idx = sm.get_phase_index(st.session_state.phase)
    selected_phase = st.selectbox(
      "Fase Berjalan:", SRL_PHASES,
      index=max(current_idx, 0),
      format_func=lambda x: PHASE_DISPLAY_MAP.get(x, x)
    )
    
    if selected_phase != st.session_state.phase:
      st.session_state.phase = selected_phase
      st.session_state.chat_count_in_phase = 0
      st.session_state.phase_scores[selected_phase] = 0.0
      st.rerun()

    st.divider()
    st.markdown("### 📁 Arsip Data")
    
    my_sheet = svc.get_safe_sheet_name(st.session_state.st_id, st.session_state.st_name)
    if my_sheet in svc.gs_list_sheets():
        with st.expander("Riwayat Belajar", expanded=False):
          st.dataframe(svc.gs_read_sheet(my_sheet), use_container_width=True)
    else:
      st.info("Belum ada riwayat belajar tersimpan.")

    if st.button("Log out akun", use_container_width=True):
      sm.reset_user_session()
      st.rerun()

  st.title("✨ Serli - Asisten AI belajar mu")
  st.caption(f"Selamat datang **{st.session_state.st_name}** | Fase: *{PHASE_DISPLAY_MAP.get(st.session_state.phase, st.session_state.phase)}*")
  st.markdown("---")

  if not st.session_state.messages:
    st.markdown("Aku Serli. Mari kita mulai belajar **Fungsi Matematika**. Sebelum kita masuk ke materi, ceritakan dong apa target atau tujuan belajarmu hari ini?")

  for msg in st.session_state.messages[-(MAX_HISTORY * 2):]:
    with st.chat_message(msg["role"], avatar="👤" if msg["role"] == "user" else "✨"):
      if msg["role"] == "assistant":
        render_ai_response_func(msg["content"])
      else:
        st.markdown(f"**{st.session_state.st_name}**")
        st.markdown(msg["content"])

  if user_query := st.chat_input("Ketik pertanyaan atau progres belajarmu di sini..."):
    with st.chat_message("user", avatar="👤"):
      st.markdown(f"**{st.session_state.st_name}**")
      st.markdown(user_query)
        
    st.session_state.messages.append({"role": "user", "content": user_query})
    sm.trim_history()

    system_prompt = (
      f"Anda adalah Serli AI, asisten Self-Regulated Learning. "
      f"Saat ini siswa berada pada fase: {st.session_state.phase}. "
      f"Jawablah dengan edukatif, singkat, dan sesuai konteks fase tersebut. "
      f"Gunakan format tabel Markdown jika menyajikan data. "
      f"Gunakan $ untuk matematika sebaris (inline) dan $$ untuk blok rumus matematika. "
      
      f"""
ATURAN 1 - VISUALISASI GRAFIK INTERAKTIF (HTML)

Jika pengguna meminta grafik matematika, koordinat Kartesius, fungsi, trigonometri,
diagram batang, diagram garis, diagram lingkaran, histogram, atau visualisasi statistik,
MAKA keluarkan SATU blok ```html (WAJIB diawali dengan pembuka ```html dan diakhiri penutup ``` ) dan tidak boleh ada blok html kedua. JANGAN langsung menulis kode HTML tanpa pembungkus blok ini!

WAJIB menghasilkan HTML lengkap dengan struktur berikut:

<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
html,body{{
    margin:0;
    padding:0;
    background:transparent;
}}
#plot{{
    width:100%;
    height:430px;
}}
</style>
</head>

WAJIB mengikuti aturan berikut:

- gunakan CDN:
[https://cdn.plot.ly/plotly-latest.min.js](https://cdn.plot.ly/plotly-latest.min.js)

- JANGAN gunakan cdn.plotly.com.

- Selalu gunakan id div = "plot".

- Selalu panggil Plotly.newPlot() di dalam
window.addEventListener('load', ...)

- Jangan menggunakan JavaScript yang bergantung pada framework lain.

- Jangan menuliskan penjelasan di dalam blok html.

- Setelah blok ```html selesai, lanjutkan penjelasan matematika dalam Markdown biasa.
"""
      f"ATURAN 2 - ILUSTRASI KONSEP (ASCII ART): "
      f"Jika siswa meminta ilustrasi konsep dasar (seperti himpunan, pohon faktor, pecahan, bangun datar, matriks, atau logika dasar), "
      f"buatlah visualisasi menggunakan teks murni (ASCII art) yang rapi, simetris, dan dibungkus dalam blok kode ```text. "
      f"KHUSUS untuk pemetaan himpunan (Domain ke Kodomain), DILARANG membuat susunan vertikal. WAJIB tiru persis spasi dan struktur template menyamping ini:\n"
      f"   Himpunan A               Himpunan B\n"
      f"  .----------.             .----------.\n"
      f" /            \\           /            \\\n"
      f"|      a       | ======> |      1       |\n"
      f"|              |         |              |\n"
      f"|      b       | ======> |      2       |\n"
      f" \\            /           \\            /\n"
      f"  '----------'             '----------'\n"
      f"Untuk konsep lain di luar pemetaan himpunan, sesuaikan bentuk ASCII art-nya sekreatif dan serapi mungkin agar logis dan mudah dipahami."
    )

    api_messages = [{"role": "system", "content": system_prompt}] + [
      {"role": m["role"], "content": m["content"]} for m in st.session_state.messages
    ]

    with st.chat_message("assistant", avatar="✨"):
      try:
        res_placeholder = st.empty()
        full_response = ""
        llm_client = svc.get_llm_client()
        
        for chunk in llm_client.stream(api_messages):
          full_response += chunk.content
          res_placeholder.markdown(full_response + "▌")
            
        res_placeholder.empty()
        render_ai_response_func(full_response)
          
      except Exception as e:
        full_response = "⚠️ Maaf, terjadi gangguan koneksi dengan Serli AI. Silakan coba lagi."
        st.error(full_response)

    st.session_state.messages.append({"role": "assistant", "content": full_response})
    
    svc.gs_write_row(
      student_id=st.session_state.st_id, 
      student_name=st.session_state.st_name, 
      user_input=user_query, 
      ai_response=full_response, 
      phase=st.session_state.phase
    )
    sm.update_srl_state_machine()
    st.rerun()