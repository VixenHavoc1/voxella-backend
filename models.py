from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    verification_code = Column(String, nullable=True)
    is_verified = Column(Boolean, default=False)

    access = relationship("AccessControl", back_populates="user")  # ✅ links to AccessControl
    payments = relationship("Payment", back_populates="user")      # ✅ links to Payment



class AccessControl(Base):
    __tablename__ = "access_control"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))  # ✅ links to User.id
    tier = Column(String)
    expires_at = Column(DateTime)

    user = relationship("User", back_populates="access")

class ChatMessage(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    user_message = Column(String, nullable=False)
    bot_reply = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

# models.py
class MessageCount(Base):
    __tablename__ = "message_count"
    user_id = Column(String, primary_key=True)
    count = Column(Integer, default=0)

# models.py
class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)  # ✅ FIXED HERE
    payment_id = Column(String, unique=True, nullable=False)  # from NowPayments
    tier = Column(String, nullable=False)
    status = Column(String, default="waiting")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="payments")  # ✅ Add this

