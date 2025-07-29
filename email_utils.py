import os
from resend import Resend

resend = Resend(api_key=os.getenv("RESEND_API_KEY"))

def send_verification_email(to_email: str, token: str):
    verify_url = f"https://your-domain.com/verify-email?token={token}"
    return resend.emails.send({
        "from": "Your App <noreply@yourdomain.com>",
        "to": [to_email],
        "subject": "Verify your email",
        "html": f"<p>Click <a href='{verify_url}'>here</a> to verify your email.</p>"
    })


