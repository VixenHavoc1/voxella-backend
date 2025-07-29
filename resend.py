import os
import requests

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_API_URL = "https://api.resend.com/emails"

def send_email(to: str, subject: str, html: str):
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "from": "Voxella <no-reply@voxellaai.site>",  # ✅ Comma added here
        "to": [to],
        "subject": subject,
        "html": html
    }
    response = requests.post(RESEND_API_URL, headers=headers, json=data)
    response.raise_for_status()
    print(response.status_code, response.text)
