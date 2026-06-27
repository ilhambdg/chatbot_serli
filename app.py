import streamlit as st
import state_management as sm
import streamlit.components.v1 as components
import re
from components.auth_ui import render_login_form
from components.teacher_ui import render_teacher_dashboard
from components.student_ui import render_student_chat

st.set_page_config(page_title="Serli AI", page_icon="✨", layout="wide")
sm.init_session_state()

def render_ai_response(text: str):
  pattern = r"(```html.*?```|<!DOCTYPE html>.*?</html>|<html.*?</html>)"
  
  parts = re.split(pattern, text, flags=re.DOTALL | re.IGNORECASE)
  
  for part in parts:
      if not part:
        continue
          
      is_html = (
        part.strip().startswith("```html") or 
        part.strip().endswith("```") or 
        "<html" in part.lower() or 
        "<!doctype html" in part.lower()
      )
      
      if is_html:
        clean_html = re.sub(r"^```html\s*|```$", "", part.strip(), flags=re.IGNORECASE | re.DOTALL)
        components.html(clean_html, height=450, scrolling=False)
      else:
        if part.strip():
          st.markdown(part)

if not st.session_state.logged_in:
  render_login_form()
elif st.session_state.role == "Guru":
  render_teacher_dashboard(render_ai_response)
else:
  render_student_chat(render_ai_response)