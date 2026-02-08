from __future__ import annotations

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PromoCode(Base):
    __tablename__ = "promo_codes"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    bonus: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PromoUsage(Base):
    __tablename__ = "promo_usages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tg_users.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text, ForeignKey("promo_codes.code", ondelete="CASCADE"))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ReferralWallet(Base):
    __tablename__ = "referral_wallets"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tg_users.id", ondelete="CASCADE"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ReferralPending(Base):
    __tablename__ = "referral_pending"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger)
    referrer_user_id: Mapped[int] = mapped_column(BigInteger)
    referred_user_id: Mapped[int] = mapped_column(BigInteger)
    amount_minor: Mapped[int] = mapped_column(Integer)
    bonus_minor: Mapped[int] = mapped_column(Integer)
    percent: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ReferralWithdrawal(Base):
    __tablename__ = "referral_withdrawals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tg_users.id", ondelete="CASCADE"))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="pending")
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tg_users.id", ondelete="CASCADE"))
    tg_user_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")
    user_ticket_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    message_count: Mapped[int] = mapped_column(Integer, default=0)


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("support_tickets.id", ondelete="CASCADE"))
    sender: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TgUser(Base):
    __tablename__ = "tg_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="user")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TgSession(Base):
    __tablename__ = "tg_sessions"

    tg_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tg_users.tg_user_id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(Text, default="menu")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    duration_days: Mapped[int] = mapped_column(Integer)
    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, default="RUB")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tg_users.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("plans.id"))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, default="RUB")
    provider: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="new")
    external_id: Mapped[str | None] = mapped_column(Text)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PaymentProof(Base):
    __tablename__ = "payment_proofs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("payment_orders.id", ondelete="CASCADE"))
    tg_file_id: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_data: Mapped[bytes] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class VpnProfile(Base):
    __tablename__ = "vpn_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tg_users.id", ondelete="CASCADE"))
    protocol: Mapped[str] = mapped_column(Text)
    server_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, default="active")
    provider_client_id: Mapped[str] = mapped_column(Text)
    provider_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    config_uri: Mapped[str | None] = mapped_column(Text)
    config_file: Mapped[str | None] = mapped_column(Text)
    rotated_from: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
