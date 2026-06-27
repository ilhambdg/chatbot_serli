import requests
import os

def cek_model_aktif():
  url = "https://api.groq.com/openai/v1/models"
  headers = {
    "Authorization": f"Bearer {os.getenv("GROQ_API_KEY")}",
    "Content-Type": "application/json"
  }

  try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
      models = response.json()['data']
      print("--- DAFTAR MODEL AKTIF ---")
      for model in models:
        print(f"Model ID: {model['id']}")
    else:
      print(f"Gagal mengambil data. Status Code: {response.status_code}")
      print(response.text)
  except Exception as e:
    print(f"Terjadi error: {e}")

if __name__ == "__main__":
  cek_model_aktif()