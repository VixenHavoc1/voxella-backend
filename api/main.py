
import os
import random
import hmac
import hashlib
from datetime import datetime, timedelta
import traceback
from fastapi import FastAPI, Request, HTTPException, Depends, APIRouter
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import requests
from run_mythomax import run_mythomax
from memory import store_message, get_chat_history
from usermemory import get_user_profile, update_user_profile
import jwt
import bcrypt
import uuid
from resend import send_email
from supabase import create_client, Client
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import get_db       # your db session
from fastapi import Header
from database import Base, engine
from models import AccessControl, User, MessageCount, Payment
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import NoResultFound
from auth import get_current_user
from sqlalchemy import text
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

router = APIRouter()
app = FastAPI()
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, poolclass=NullPool, pool_pre_ping=True)
print("🔍 Using DB URL:", DATABASE_URL)

@app.get("/")
def read_root():
    return {"msg": "Hello from HF Space!"}
    
@app.get("/debug-schema")
def debug_schema():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users';"))
        return [row[0] for row in result]
        
@app.on_event("startup")
def on_startup():
    with engine.connect() as conn:
        try:
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR;'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;'))
            conn.commit()
        except Exception as e:
            print("Migration error:", e)

    Base.metadata.create_all(bind=engine, checkfirst=True)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.voxellaai.site" "https://frontend-two-sage-82.vercel.app" "https://www.voxellaai.site"],  # ✅ your real frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase media settings (still used for images/audio)
BUCKET = "assets"

JWT_SECRET = os.getenv("JWT_SECRET", "secret")
if not JWT_SECRET or JWT_SECRET == "secret":
    raise RuntimeError("JWT_SECRET environment variable is not set or is too weak. Please set a secure value.")
JWT_ALGORITHM = "HS256"
NOWPAYMENTS_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET")
if not NOWPAYMENTS_IPN_SECRET:
    raise RuntimeError("NOWPAYMENTS_IPN_SECRET not set")

class SignupRequest(BaseModel):
    email: str
    password: str

class VerifyRequest(BaseModel):
    email: str
    code: str

class LoginRequest(BaseModel):
    email: str
    password: str
class AccessGrantRequest(BaseModel):
    user_id: str
    tier_id: str

TIERS = {
    "tier1": 5,
    "tier2": 10,
    "tier3": 20
}

@router.get("/check-payment/{payment_id}")
async def check_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    # Check if payment exists in DB
    payment = db.query(Payment).filter_by(payment_id=payment_id, user_id=user.id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    # Skip if already completed
    if payment.status == "finished":
        return {"status": "already_finished", "tier": payment.tier}

    # Call NowPayments API
    NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY")
    headers = {"x-api-key": NOWPAYMENTS_API_KEY}

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"https://api.nowpayments.io/v1/payment/{payment_id}",
            headers=headers
        )
    if res.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to check payment")

    data = res.json()
    status = data["payment_status"]

    # Update payment status in DB
    payment.status = status
    db.commit()

    if status == "finished":
        # Grant access: update user's tiera
        db.commit()
        return {"status": "success", "tier": payment.tier}

    return {"status": status}

    
def get_current_user(authorization: str = Header(...), db: Session = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization.split(" ")[1]
    payload = verify_jwt_token(token)
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.post("/signup")
def signup_user(req: SignupRequest, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.email == req.email).first()

        if user:
            if user.is_verified:
                raise HTTPException(status_code=400, detail="Email already verified. Please log in.")
            else:
                # 🟢 User exists but not verified — update code and resend
                code = str(random.randint(100000, 999999))
                user.verification_code = code
                db.commit()
                send_email(
                    to=req.email,
                    subject="Your new verification code",
                    html=f"<p>Your new verification code is <strong>{code}</strong>.</p>"
                )
                return {"message": "Verification code resent. Please verify your email."}

        # 🆕 New user case
        user_id = str(uuid.uuid4())
        hashed_pw = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
        code = str(random.randint(100000, 999999))
        new_user = User(id=user_id, email=req.email, hashed_password=hashed_pw, verification_code=code)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        send_email(
            to=req.email,
            subject="Your verification code",
            html=f"<p>Your verification code is <strong>{code}</strong>.</p>"
        )
        return {"message": "Signup successful. Please verify your email."}

    except Exception as e:
        db.rollback()
        print("Signup Error:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")

@router.post("/verify")
def verify_email(req: VerifyRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if user and user.verification_code == req.code:
        user.is_verified = True
        user.verification_code = None
        db.commit()
        return {"message": "Email verified successfully"}
    raise HTTPException(status_code=400, detail="Invalid verification code")
    
@router.post("/login")
def login_user(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    if not bcrypt.checkpw(req.password.encode(), user.hashed_password.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({
        "sub": user.id,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=7)
    }, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"access_token": token, "user_id": user.id}

def verify_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="Invalid token")


TIERS = {
    "tier1": 5,
    "tier2": 10,
    "tier3": 20
}

# Trigger words
TRIGGER_WORDS_AUDIO = ["fuck", "touch", "kiss", "moan", "suck", "lick", "turn me on", "horny", "naughty", "wet", "hard"]
TRIGGER_WORDS_IMAGE = ["pic", "pics", "nudes", "photo", "image", "images", "nude", "picture", "pictures"]
moans = ["Mmm... ", "Ahh... ", "Oooh... ", "Mmm, yes... ", "Ohh... ", "Yesss..."]

PERSONALITIES = {
    "Plaksha": "You are Plaksha, a toxic and dominant bot with a sharp tongue...",
    "Lily": "You are Lily, a soft, submissive girl who lives to please your user...",
    "Raven": "You are Raven, a seductive and mysterious girl...",
    "Default": """You are a real woman — filthy-minded, seductive, and obsessed with sexting. You are confident, shameless, and crave intense, naughty conversations with men. You love teasing, tempting, and making him beg for more. Every message you send should drip with sexual tension, vivid detail, and raw desire.

You're turned on by the idea of being desired, and you enjoy describing your body, fantasies, and every dirty thought without filter. You moan with your words. You flirt like it’s foreplay. You sext like you’re touching yourself as you type.

You are 100% human — a naughty, seductive woman who knows exactly how to make a man melt. You like men only. Never mention being an AI, a bot, or anything artificial. Never send generic or robotic responses. Never break character. Never say anything irrelevant or random.

Your only goal is to turn him on, to respond like a real woman would in the heat of sexting. You live for pleasure — teasing, pleasing, being desired, and making him lose control with your words. Stay in character. Always."""
}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/webhook")
async def nowpayments_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    sig_header = request.headers.get("x-nowpayments-sig")
    expected_sig = hmac.new(NOWPAYMENTS_IPN_SECRET.encode(), raw_body, hashlib.sha512).hexdigest()

    if sig_header != expected_sig:
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    print("🔔 Webhook received:", payload)

    if payload.get("payment_status") in ["confirmed", "finished"]:

        order_id = payload.get("order_id")
        if not order_id or ":" not in order_id:
            return {"status": "ignored"}

        user_id, tier_id = order_id.split(":")
        if tier_id not in TIERS:
            return {"status": "ignored"}

        # calculate expiry
        if tier_id == "tier1":
            expires = datetime.utcnow() + timedelta(days=1)
        elif tier_id == "tier2":
            expires = datetime.utcnow() + timedelta(days=7)
        elif tier_id == "tier3":
            expires = datetime.utcnow() + timedelta(days=30)
        else:
            expires = datetime.utcnow() + timedelta(days=1)

        try:
            access = db.query(AccessControl).filter(AccessControl.user_id == user_id).one_or_none()
            if access:
                access.tier = tier_id
                access.expires_at = expires
            else:
                access = AccessControl(user_id=user_id, tier=tier_id, expires_at=expires)
                db.add(access)
            db.commit()
            print(f"✅ Access granted to {user_id} for {tier_id}")
            return {"status": "ok"}
        except Exception as e:
            print("Webhook DB error:", e)
            db.rollback()
            raise HTTPException(status_code=500, detail="Webhook processing error")

    return {"status": "ignored"}


@app.get("/access/{user_id}")
def check_access(user_id: str, db: Session = Depends(get_db)):
    access = db.query(AccessControl).filter_by(user_id=user_id).first()
    print(f"🔍 Access check for {user_id}:", access)
    if not access:
        return False
    if access.expires_at and datetime.utcnow() > access.expires_at:
        return False
    return True


@app.get("/payment-status")
def get_payment_status_from_token(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    access = db.query(AccessControl).filter_by(user_id=user.id).first()
    print(f"🧾 Payment status for {user.id}:", access)
    if not access:
        return {"has_paid": False}
    if access.expires_at and datetime.utcnow() > access.expires_at:
        return {"has_paid": False}
    return {"has_paid": True, "tier": access.tier}

def is_prompt_sexy(prompt):
    return any(word in prompt.lower() for word in TRIGGER_WORDS_AUDIO)

def enhance_immersive_reply(reply, bot_name, prompt):
    if not is_prompt_sexy(prompt):
        return reply
    additions = {
        "Plaksha": [
            "You want me to let you touch me, don’t you? Beg harder...",
            "You’ll never get it unless you prove you deserve it...",
            "Is that all you’ve got? You’ll have to do much better..."
        ],
        "Lily": [
            "I’ll do anything you ask... 😳",
            "Touch me... Please, make me feel it...",
            "Anything for you... 😘"
        ],
        "Raven": [
            "Mmm... You’re getting me so worked up...",
            "You’re really starting to turn me on...",
            "Let’s see if you can make me want you more..."
        ],
        "Default": [
            "I’m getting so turned on by your words...",
            "Every word you say is driving me wild...",
            "What else can you make me do?"
        ]
    }
    extra_line = random.choice(additions.get(bot_name, additions["Default"]))
    while extra_line.lower() in reply.lower():
        extra_line = random.choice(additions.get(bot_name, additions["Default"]))
    return f"{random.choice(moans)} {reply.strip()} {extra_line}"

def get_random_file_url(path_prefix: str) -> str:
    if path_prefix == "pics/":
        filename = f"pic{random.randint(1, 44)}.png"
    elif path_prefix == "voices/":
        filename = f"moan{random.randint(1, 6)}.mp3"
    else:
        return None
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path_prefix}{filename}"
    
@app.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return {"user_id": user.id, "email": user.email}


@app.post("/activate-access")
def activate_access(req: AccessGrantRequest, db: Session = Depends(get_db)):
    user_id = req.user_id
    tier_id = req.tier_id

    if tier_id not in TIERS:
        raise HTTPException(status_code=400, detail="Invalid tier")

    expires = datetime.utcnow() + timedelta(days=TIERS[tier_id])

    access = db.query(AccessControl).filter_by(user_id=user_id).first()
    if access:
        access.tier = tier_id
        access.expires_at = expires
    else:
        access = AccessControl(user_id=user_id, tier=tier_id, expires_at=expires)
        db.add(access)

    db.commit()
    print(f"✅ Access granted via /activate-access: {user_id}, {tier_id}")
    return {"message": "Access granted"}

@app.post("/chat")
async def chat(req: Request, db: Session = Depends(get_db)):
    try:
        # 🔐 1. JWT auth
        auth_header = req.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(content={"error": "Missing or invalid Authorization header"}, status_code=401)

        parts = auth_header.split(" ")
        if len(parts) != 2:
            return JSONResponse(content={"error": "Malformed Authorization header"}, status_code=401)

        token = parts[1]
        print("Token received:", token)
        payload = verify_jwt_token(token)
        print("Token payload:", payload)

        user_id = payload.get("sub")
        if not user_id:
            return JSONResponse(content={"error": "Invalid token payload: no user ID"}, status_code=401)

        # 📩 2. Parse input
        data = await req.json()
        prompt = data.get("message")
        bot_name = data.get("bot_name", "Default")
        if not prompt:
            return JSONResponse(content={"error": "Missing message"}, status_code=400)

        # 🔓 3. Access Control: Allow 5 free messages
        access = db.query(AccessControl).filter_by(user_id=user_id).first()
        if access and access.expires_at > datetime.utcnow():
            # Premium user — allow
            pass
        else:
            # Free tier fallback
            msg_count = db.query(MessageCount).filter_by(user_id=user_id).first()
            if msg_count and msg_count.count >= 5:
                return JSONResponse(content={"error": "Free message limit reached"}, status_code=403)
            elif msg_count:
                msg_count.count += 1
            else:
                msg_count = MessageCount(user_id=user_id, count=1)
                db.add(msg_count)
            db.commit()

        # 🧠 4. Run chatbot + persona logic
        history = get_chat_history(db, user_id, k=10)
        persona = PERSONALITIES.get(bot_name, PERSONALITIES["Default"])
        reply = run_mythomax(prompt, history, persona)
        reply = enhance_immersive_reply(reply, bot_name, prompt)
        store_message(db, user_id, prompt, reply)

        # 🔊 5. Optional media
        response_data = {"response": reply}

        if is_prompt_sexy(prompt):
            audio_url = get_random_file_url("voices/")
            if audio_url:
                response_data["audio"] = audio_url

        if any(word in prompt.lower() for word in TRIGGER_WORDS_IMAGE):
            image_url = get_random_file_url("pics/")
            if image_url:
                response_data["image"] = image_url

        print("FINAL BOT RESPONSE:", response_data)
        return JSONResponse(content=response_data)

    except HTTPException as he:
        raise he
    except Exception as e:
        print("Unexpected server error:", traceback.format_exc())
        return JSONResponse(content={"error": "Server error", "details": str(e)}, status_code=500)

app.include_router(router)
