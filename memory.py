from models import ChatMessage
from sqlalchemy.orm import Session
from datetime import datetime

def store_message(db: Session, user_id: str, user_message: str, bot_reply: str):
    message = ChatMessage(
        user_id=user_id,
        user_message=user_message,
        bot_reply=bot_reply,
        timestamp=datetime.utcnow()
    )
    db.add(message)
    db.commit()

def get_chat_history(db: Session, user_id: str, k: int = 10):
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.timestamp.desc())
        .limit(k)
        .all()
    )
    # Oldest to newest
    return [{"user": m.user_message, "bot": m.bot_reply} for m in reversed(messages)]

