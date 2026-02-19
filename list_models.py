import google.generativeai as genai
import os

API_KEY = "AIzaSyCWPlKqiET1w46PSJ8WbRgGYwGIQczwrgM"
genai.configure(api_key=API_KEY)

try:
    print("Listing models...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
except Exception as e:
    print(f"Error: {e}")
