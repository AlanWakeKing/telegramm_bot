from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_user(session: AsyncSession, tg_user_id: int, chat_id: int, username: str | None, referrer_id: int | None = None) -> dict[str, Any]:
    q = text(
        """
        insert into tg_users (tg_user_id, chat_id, username, role, last_seen_at)
        values (:tg_user_id, :chat_id, :username, 'user', now())
        on conflict (tg_user_id) do update
        set chat_id = excluded.chat_id,
            username = excluded.username,
            last_seen_at = now()
        returning id as user_id, tg_user_id, chat_id, username, role, is_blocked, referrer_id, referral_code;
        """
    )
    res = await session.execute(q, {"tg_user_id": tg_user_id, "chat_id": chat_id, "username": username})
    row = res.mappings().first()
    user = dict(row) if row else {}
    if user:
        if not user.get("referral_code"):
            code = f"REF{user['user_id']}"
            await session.execute(
                text("update tg_users set referral_code = :code where id = :id"),
                {"code": code, "id": user["user_id"]},
            )
            user["referral_code"] = code
        if referrer_id and not user.get("referrer_id") and referrer_id != user.get("user_id"):
            await session.execute(
                text("update tg_users set referrer_id = :referrer_id where id = :id"),
                {"referrer_id": referrer_id, "id": user["user_id"]},
            )
            user["referrer_id"] = referrer_id
    return user


async def ensure_session(session: AsyncSession, tg_user_id: int) -> dict[str, Any]:
    q = text(
        """
        insert into tg_sessions (tg_user_id, state, payload, updated_at)
        values (:tg_user_id, 'menu', '{}'::jsonb, now())
        on conflict (tg_user_id) do update
        set updated_at = now()
        returning tg_user_id, state, payload;
        """
    )
    res = await session.execute(q, {"tg_user_id": tg_user_id})
    row = res.mappings().first()
    return dict(row) if row else {}


async def load_user_with_session(session: AsyncSession, tg_user_id: int) -> dict[str, Any] | None:
    q = text(
        """
        select
          u.id as user_id, u.tg_user_id, u.chat_id, u.username, u.role, u.is_blocked,
          u.referrer_id, u.referral_code,
          s.state, s.payload
        from tg_users u
        left join tg_sessions s on s.tg_user_id = u.tg_user_id
        where u.tg_user_id = :tg_user_id
        limit 1;
        """
    )
    res = await session.execute(q, {"tg_user_id": tg_user_id})
    row = res.mappings().first()
    return dict(row) if row else None


async def load_user_by_id(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    q = text(
        """
        select id as user_id, tg_user_id, chat_id, username, role, is_blocked,
               referrer_id, referral_code
        from tg_users
        where id = :user_id
        limit 1;
        """
    )
    res = await session.execute(q, {"user_id": user_id})
    row = res.mappings().first()
    return dict(row) if row else None


async def _load_setting(session: AsyncSession, key: str, default: Any) -> Any:
    q = text(
        """
        select value_json
        from bot_settings
        where key = :key
        limit 1;
        """
    )
    res = await session.execute(q, {"key": key})
    row = res.mappings().first()
    if not row:
        await session.execute(
            text("insert into bot_settings (key, value_json, updated_at) values (:key, CAST(:value AS jsonb), now())"),
            {"key": key, "value": json.dumps(default)},
        )
        return default
    return row["value_json"]


async def _save_setting(session: AsyncSession, key: str, value: Any) -> None:
    await session.execute(
        text(
            """
            insert into bot_settings (key, value_json, updated_at)
            values (:key, CAST(:value AS jsonb), now())
            on conflict (key) do update set value_json = excluded.value_json, updated_at = now();
            """
        ),
        {"key": key, "value": json.dumps(value)},
    )


DEFAULT_REFERRAL_SETTINGS = {
    "percent": 10,
    "delay_hours": 24,
}

async def _ensure_support_schema(session: AsyncSession) -> None:
    await session.execute(text("""
        create table if not exists support_tickets (
            id bigserial primary key,
            user_id bigint not null references tg_users(id) on delete cascade,
            tg_user_id bigint not null,
            chat_id bigint not null,
            username text,
            status text not null default 'open',
            user_ticket_id integer not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            message_count integer not null default 0
        );
    """))
    await session.execute(text("""
        create unique index if not exists ux_support_tickets_user_id_user_ticket_id
        on support_tickets(user_id, user_ticket_id);
    """))
    await session.execute(text("""
        create table if not exists support_messages (
            id bigserial primary key,
            ticket_id bigint not null references support_tickets(id) on delete cascade,
            sender text not null,
            text text not null,
            created_at timestamptz not null default now()
        );
    """))


async def _ensure_promo_schema(session: AsyncSession) -> None:
    await session.execute(text("""
        create table if not exists promo_codes (
            code text primary key,
            bonus integer not null,
            active boolean not null default true,
            max_uses integer,
            used_count integer not null default 0,
            expires_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );
    """))
    await session.execute(text("""
        create table if not exists promo_usages (
            id bigserial primary key,
            user_id bigint not null references tg_users(id) on delete cascade,
            code text not null references promo_codes(code) on delete cascade,
            used_at timestamptz not null default now(),
            unique(user_id, code)
        );
    """))


async def _ensure_referral_schema(session: AsyncSession) -> None:
    await session.execute(text("""
        create table if not exists referral_wallets (
            user_id bigint primary key references tg_users(id) on delete cascade,
            balance integer not null default 0,
            updated_at timestamptz not null default now()
        );
    """))
    await session.execute(text("""
        create table if not exists referral_pending (
            id bigserial primary key,
            order_id bigint not null,
            referrer_user_id bigint not null,
            referred_user_id bigint not null,
            amount_minor integer not null,
            bonus_minor integer not null,
            percent integer not null,
            due_at timestamptz not null,
            created_at timestamptz not null default now()
        );
    """))
    await session.execute(text("""
        create unique index if not exists ux_referral_pending_order_id
        on referral_pending(order_id);
    """))
    await session.execute(text("""
        create table if not exists referral_withdrawals (
            id bigserial primary key,
            user_id bigint not null references tg_users(id) on delete cascade,
            amount integer not null,
            status text not null default 'pending',
            meta jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );
    """))
DEFAULT_SUPPORT_SETTINGS = {
    "admin_group_id": -5130507662,
}


async def get_referral_settings(session: AsyncSession) -> dict[str, Any]:
    raw = await _load_setting(session, "REFERRAL_SETTINGS", DEFAULT_REFERRAL_SETTINGS)
    settings = dict(DEFAULT_REFERRAL_SETTINGS)
    if isinstance(raw, dict):
        settings.update(raw)
    percent = settings.get("percent")
    try:
        if isinstance(percent, str):
            percent = percent.strip().replace("%", "")
        settings["percent"] = int(percent)
    except Exception:
        settings["percent"] = DEFAULT_REFERRAL_SETTINGS["percent"]
    delay = settings.get("delay_hours")
    try:
        settings["delay_hours"] = int(delay)
    except Exception:
        settings["delay_hours"] = DEFAULT_REFERRAL_SETTINGS["delay_hours"]
    if raw != settings:
        await _save_setting(session, "REFERRAL_SETTINGS", settings)
    return settings


async def get_support_settings(session: AsyncSession) -> dict[str, Any]:
    raw = await _load_setting(session, "SUPPORT_SETTINGS", DEFAULT_SUPPORT_SETTINGS)
    settings = dict(DEFAULT_SUPPORT_SETTINGS)
    if isinstance(raw, dict):
        settings.update(raw)
    try:
        settings["admin_group_id"] = int(settings.get("admin_group_id"))
    except Exception:
        settings["admin_group_id"] = DEFAULT_SUPPORT_SETTINGS["admin_group_id"]
    if raw != settings:
        await _save_setting(session, "SUPPORT_SETTINGS", settings)
    return settings


async def get_admin_group_id(session: AsyncSession) -> int:
    settings = await get_support_settings(session)
    return int(settings.get("admin_group_id") or 0)


async def resolve_referrer_user_id(session: AsyncSession, referrer_id: int) -> int | None:
    if not referrer_id:
        return None
    user = await load_user_by_id(session, referrer_id)
    if user:
        return int(user["user_id"])
    # fallback: treat as tg_user_id
    user = await load_user_with_session(session, referrer_id)
    if user:
        return int(user["user_id"])
    return None


async def get_referral_pending(session: AsyncSession) -> list[dict[str, Any]]:
    await _ensure_referral_schema(session)
    res = await session.execute(text("""
        select id, order_id, referrer_user_id, referred_user_id, amount_minor, bonus_minor, percent, due_at
        from referral_pending
        order by id asc;
    """))
    return [dict(r) for r in res.mappings().all()]


async def get_ref_withdrawals(session: AsyncSession) -> list[dict[str, Any]]:
    await _ensure_referral_schema(session)
    res = await session.execute(text("""
        select id, user_id, amount, status, meta, created_at, updated_at
        from referral_withdrawals
        order by id desc;
    """))
    return [dict(r) for r in res.mappings().all()]


async def add_ref_withdraw_request(session: AsyncSession, user_id: int, amount: int) -> str | None:
    await _ensure_referral_schema(session)
    # one pending per user
    res = await session.execute(text("""
        select id from referral_withdrawals
        where user_id = :user_id and status = 'pending'
        limit 1;
    """), {"user_id": user_id})
    if res.mappings().first():
        return None
    res = await session.execute(text("""
        insert into referral_withdrawals (user_id, amount, status, created_at, updated_at)
        values (:user_id, :amount, 'pending', now(), now())
        returning id;
    """), {"user_id": user_id, "amount": int(amount)})
    row = res.mappings().first()
    return f"RW{row['id']}" if row else None


async def get_ref_withdraw_request(session: AsyncSession, req_id: str) -> dict[str, Any] | None:
    await _ensure_referral_schema(session)
    raw = str(req_id or "")
    if raw.upper().startswith("RW"):
        raw = raw[2:]
    try:
        req_num = int(raw)
    except Exception:
        return None
    res = await session.execute(text("""
        select id, user_id, amount, status, meta, created_at, updated_at
        from referral_withdrawals
        where id = :id
        limit 1;
    """), {"id": req_num})
    row = res.mappings().first()
    return dict(row) if row else None


async def update_ref_withdraw_status(session: AsyncSession, req_id: str, status: str, meta: dict | None = None) -> None:
    await _ensure_referral_schema(session)
    raw = str(req_id or "")
    if raw.upper().startswith("RW"):
        raw = raw[2:]
    try:
        req_num = int(raw)
    except Exception:
        return
    await session.execute(text("""
        update referral_withdrawals
        set status = :status,
            meta = COALESCE(meta, '{}'::jsonb) || CAST(:meta AS jsonb),
            updated_at = now()
        where id = :id;
    """), {
        "status": status,
        "meta": json.dumps(meta or {}),
        "id": req_num,
    })


async def _next_user_ticket_id(session: AsyncSession, user_id: int) -> int:
    await _ensure_support_schema(session)
    res = await session.execute(text("""
        select coalesce(max(user_ticket_id), 0) + 1 as next_id
        from support_tickets
        where user_id = :user_id;
    """), {"user_id": user_id})
    row = res.mappings().first()
    return int(row["next_id"]) if row else 1


async def get_support_tickets(session: AsyncSession) -> list[dict[str, Any]]:
    await _ensure_support_schema(session)
    res = await session.execute(text("""
        select id, user_id, tg_user_id, chat_id, username, status, user_ticket_id, created_at, updated_at, message_count
        from support_tickets
        order by updated_at desc;
    """))
    return [dict(r) for r in res.mappings().all()]


async def _save_support_tickets(session: AsyncSession, tickets: list[dict[str, Any]]) -> None:
    await _ensure_support_schema(session)
    for t in tickets:
        await session.execute(text("""
            insert into support_tickets
              (id, user_id, tg_user_id, chat_id, username, status, user_ticket_id, created_at, updated_at, message_count)
            values
              (:id, :user_id, :tg_user_id, :chat_id, :username, :status, :user_ticket_id, :created_at, :updated_at, :message_count)
            on conflict (id) do update set
              status = excluded.status,
              updated_at = excluded.updated_at,
              message_count = excluded.message_count;
        """), {
            "id": t.get("id"),
            "user_id": t.get("user_id"),
            "tg_user_id": t.get("tg_user_id"),
            "chat_id": t.get("chat_id"),
            "username": t.get("username"),
            "status": t.get("status"),
            "user_ticket_id": t.get("user_ticket_id"),
            "created_at": t.get("created_at"),
            "updated_at": t.get("updated_at"),
            "message_count": t.get("message_count") or 0,
        })


async def get_support_messages(session: AsyncSession) -> list[dict[str, Any]]:
    await _ensure_support_schema(session)
    res = await session.execute(text("""
        select id, ticket_id, sender, text, created_at
        from support_messages
        order by created_at asc;
    """))
    return [dict(r) for r in res.mappings().all()]


async def _save_support_messages(session: AsyncSession, messages: list[dict[str, Any]]) -> None:
    await _ensure_support_schema(session)
    for m in messages:
        await session.execute(text("""
            insert into support_messages (id, ticket_id, sender, text, created_at)
            values (:id, :ticket_id, :sender, :text, :created_at)
            on conflict (id) do nothing;
        """), {
            "id": m.get("id"),
            "ticket_id": m.get("ticket_id"),
            "sender": m.get("sender"),
            "text": m.get("text"),
            "created_at": m.get("created_at"),
        })


async def list_support_tickets_for_user(session: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    await _ensure_support_schema(session)
    res = await session.execute(text("""
        select id, user_id, tg_user_id, chat_id, username, status, user_ticket_id, created_at, updated_at, message_count
        from support_tickets
        where user_id = :user_id
        order by updated_at desc;
    """), {"user_id": user_id})
    return [dict(r) for r in res.mappings().all()]


async def get_support_ticket(session: AsyncSession, ticket_id: int) -> dict[str, Any] | None:
    await _ensure_support_schema(session)
    res = await session.execute(text("""
        select id, user_id, tg_user_id, chat_id, username, status, user_ticket_id, created_at, updated_at, message_count
        from support_tickets
        where id = :id
        limit 1;
    """), {"id": ticket_id})
    row = res.mappings().first()
    return dict(row) if row else None


async def count_open_tickets_for_user(session: AsyncSession, user_id: int) -> int:
    await _ensure_support_schema(session)
    res = await session.execute(text("""
        select count(*) as cnt
        from support_tickets
        where user_id = :user_id and status = 'open';
    """), {"user_id": user_id})
    row = res.mappings().first()
    return int(row["cnt"]) if row else 0


async def get_last_open_ticket_for_user(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    await _ensure_support_schema(session)
    res = await session.execute(text("""
        select id, user_id, tg_user_id, chat_id, username, status, user_ticket_id, created_at, updated_at, message_count
        from support_tickets
        where user_id = :user_id and status = 'open'
        order by updated_at desc
        limit 1;
    """), {"user_id": user_id})
    row = res.mappings().first()
    return dict(row) if row else None


async def add_support_ticket(session: AsyncSession, user: dict, text: str) -> dict[str, Any]:
    await _ensure_support_schema(session)
    user_ticket_id = await _next_user_ticket_id(session, int(user["user_id"]))
    res = await session.execute(text("""
        insert into support_tickets
          (user_id, tg_user_id, chat_id, username, status, user_ticket_id, created_at, updated_at, message_count)
        values
          (:user_id, :tg_user_id, :chat_id, :username, 'open', :user_ticket_id, now(), now(), 0)
        returning id, user_id, tg_user_id, chat_id, username, status, user_ticket_id, created_at, updated_at, message_count;
    """), {
        "user_id": int(user["user_id"]),
        "tg_user_id": int(user["tg_user_id"]),
        "chat_id": int(user["chat_id"]),
        "username": user.get("username"),
        "user_ticket_id": user_ticket_id,
    })
    ticket = dict(res.mappings().first())
    await add_support_message(session, ticket["id"], "user", text)
    return ticket


async def add_support_message(session: AsyncSession, ticket_id: int, sender: str, text: str) -> None:
    await _ensure_support_schema(session)
    await session.execute(text("""
        insert into support_messages (ticket_id, sender, text, created_at)
        values (:ticket_id, :sender, :text, now());
    """), {"ticket_id": int(ticket_id), "sender": sender, "text": text})
    await session.execute(text("""
        update support_tickets
        set updated_at = now(),
            message_count = message_count + 1
        where id = :ticket_id;
    """), {"ticket_id": int(ticket_id)})


async def list_support_messages_for_ticket(session: AsyncSession, ticket_id: int, limit: int = 10) -> list[dict[str, Any]]:
    await _ensure_support_schema(session)
    res = await session.execute(text("""
        select id, ticket_id, sender, text, created_at
        from support_messages
        where ticket_id = :ticket_id
        order by created_at asc
        limit :limit;
    """), {"ticket_id": int(ticket_id), "limit": int(limit)})
    return [dict(r) for r in res.mappings().all()]


async def close_support_ticket(session: AsyncSession, ticket_id: int) -> None:
    await _ensure_support_schema(session)
    await session.execute(text("""
        update support_tickets
        set status = 'closed', updated_at = now()
        where id = :ticket_id;
    """), {"ticket_id": int(ticket_id)})


async def count_referrals(session: AsyncSession, referrer_user_id: int) -> int:
    q = text(
        """
        select count(*) as cnt
        from tg_users
        where referrer_id = :referrer_id;
        """
    )
    res = await session.execute(q, {"referrer_id": referrer_user_id})
    row = res.mappings().first()
    return int(row["cnt"]) if row else 0


async def get_referral_wallet(session: AsyncSession, referrer_user_id: int) -> int:
    await _ensure_referral_schema(session)
    res = await session.execute(text("""
        insert into referral_wallets (user_id, balance, updated_at)
        values (:user_id, 0, now())
        on conflict (user_id) do update set updated_at = now()
        returning balance;
    """), {"user_id": referrer_user_id})
    row = res.mappings().first()
    return int(row["balance"]) if row else 0


async def add_referral_wallet(session: AsyncSession, referrer_user_id: int, amount: int) -> int:
    await _ensure_referral_schema(session)
    res = await session.execute(text("""
        insert into referral_wallets (user_id, balance, updated_at)
        values (:user_id, :amount, now())
        on conflict (user_id) do update
        set balance = referral_wallets.balance + :amount,
            updated_at = now()
        returning balance;
    """), {"user_id": referrer_user_id, "amount": int(amount)})
    row = res.mappings().first()
    return int(row["balance"]) if row else 0


async def clear_referral_wallet(session: AsyncSession, referrer_user_id: int) -> None:
    await _ensure_referral_schema(session)
    await session.execute(text("""
        update referral_wallets
        set balance = 0, updated_at = now()
        where user_id = :user_id;
    """), {"user_id": referrer_user_id})


async def add_referral_pending(
    session: AsyncSession,
    referrer_user_id: int,
    referred_user_id: int,
    amount_minor: int,
    order_id: int,
) -> int:
    await _ensure_referral_schema(session)
    settings = await get_referral_settings(session)
    percent = int(settings.get("percent") or 0)
    if percent <= 0:
        return 0
    bonus = int(amount_minor * percent / 100)
    if bonus <= 0:
        return 0
    due_at = datetime.now(timezone.utc) + timedelta(hours=int(settings.get("delay_hours") or 0))
    res = await session.execute(text("""
        insert into referral_pending
          (order_id, referrer_user_id, referred_user_id, amount_minor, bonus_minor, percent, due_at)
        values
          (:order_id, :referrer_user_id, :referred_user_id, :amount_minor, :bonus_minor, :percent, :due_at)
        on conflict (order_id) do nothing
        returning id;
    """), {
        "order_id": order_id,
        "referrer_user_id": referrer_user_id,
        "referred_user_id": referred_user_id,
        "amount_minor": amount_minor,
        "bonus_minor": bonus,
        "percent": percent,
        "due_at": due_at,
    })
    if not res.mappings().first():
        return 0
    return bonus


async def has_referral_bonus(session: AsyncSession, order_id: int) -> bool:
    q = text(
        """
        select 1
        from balance_transactions
        where reason = 'referral_bonus'
          and meta->>'order_id' = CAST(:order_id AS text)
        limit 1;
        """
    )
    res = await session.execute(q, {"order_id": order_id})
    row = res.mappings().first()
    return bool(row)


async def process_referral_pending(session: AsyncSession, referrer_user_id: int) -> int:
    await _ensure_referral_schema(session)
    canonical_ref_id = await resolve_referrer_user_id(session, referrer_user_id)
    if not canonical_ref_id:
        canonical_ref_id = referrer_user_id
    res = await session.execute(text("""
        select id, order_id, referrer_user_id, bonus_minor, due_at
        from referral_pending
        where due_at <= now();
    """))
    rows = [dict(r) for r in res.mappings().all()]
    applied = 0
    for item in rows:
        item_ref_id = int(item.get("referrer_user_id") or 0)
        if item_ref_id != canonical_ref_id:
            resolved = await resolve_referrer_user_id(session, item_ref_id)
            if resolved != canonical_ref_id:
                continue
        bonus = int(item.get("bonus_minor") or 0)
        if bonus <= 0:
            continue
        await add_referral_wallet(session, canonical_ref_id, bonus)
        await session.execute(text("delete from referral_pending where id = :id"), {"id": item["id"]})
        applied += 1
    return applied


async def process_referral_pending_all(session: AsyncSession) -> int:
    await _ensure_referral_schema(session)
    res = await session.execute(text("""
        select id, order_id, referrer_user_id, bonus_minor, due_at
        from referral_pending
        where due_at <= now();
    """))
    rows = [dict(r) for r in res.mappings().all()]
    applied = 0
    for item in rows:
        bonus = int(item.get("bonus_minor") or 0)
        if bonus <= 0:
            continue
        item_ref_id = int(item.get("referrer_user_id") or 0)
        ref_user_id = await resolve_referrer_user_id(session, item_ref_id)
        if not ref_user_id:
            continue
        await add_referral_wallet(session, ref_user_id, bonus)
        await session.execute(text("delete from referral_pending where id = :id"), {"id": item["id"]})
        applied += 1
    return applied


async def set_state_clear(session: AsyncSession, tg_user_id: int, state: str) -> None:
    q = text(
        """
        update tg_sessions
        set state = :state,
            payload = payload - 'buy' - 'connect',
            updated_at = now()
        where tg_user_id = :tg_user_id;
        """
    )
    await session.execute(q, {"tg_user_id": tg_user_id, "state": state})


async def set_state_payload(session: AsyncSession, tg_user_id: int, state: str, key: str, value: Any) -> None:
    q = text(
        """
        update tg_sessions
        set payload =
              coalesce(payload, '{}'::jsonb)
              || jsonb_build_object(
                   CAST(:key AS text),
                   coalesce(payload->CAST(:key AS text), '{}'::jsonb)
                   || CAST(:value AS jsonb)
                 ),
            state = :state,
            updated_at = now()
        where tg_user_id = :tg_user_id;
        """
    )
    await session.execute(q, {
        "tg_user_id": tg_user_id,
        "state": state,
        "key": key,
        "value": json.dumps(value),
    })


async def list_servers(session: AsyncSession) -> list[dict[str, Any]]:
    q = text(
        """
        select s.id, s.name, s.country,
               s.capacity,
               coalesce(p.cnt, 0) as active_keys
        from vpn_servers s
        left join (
            select server_id, count(*) as cnt
            from vpn_profiles
            where status = 'active' and revoked_at is null
            group by server_id
        ) p on p.server_id = s.id
        where s.enabled = true
        order by s.weight desc, s.id asc;
        """
    )
    res = await session.execute(q)
    return [dict(r) for r in res.mappings().all()]


async def list_plans(session: AsyncSession) -> list[dict[str, Any]]:
    q = text(
        """
        select id, code, title, duration_days, price_minor, currency
        from plans
        where enabled = true
        order by price_minor asc, id asc;
        """
    )
    res = await session.execute(q)
    return [dict(r) for r in res.mappings().all()]


async def load_plan(session: AsyncSession, plan_id: int) -> dict[str, Any] | None:
    q = text(
        """
        select id, code, title, duration_days, price_minor, currency
        from plans
        where id = :id
        limit 1;
        """
    )
    res = await session.execute(q, {"id": plan_id})
    row = res.mappings().first()
    return dict(row) if row else None


async def load_admin_ids(session: AsyncSession) -> list[int]:
    q = text(
        """
        select value_json
        from bot_settings
        where key = 'ADMIN_TG_IDS'
        limit 1;
        """
    )
    res = await session.execute(q)
    row = res.mappings().first()
    if not row:
        return []
    ids = row["value_json"] or []
    return [int(x) for x in ids]


async def get_promo_codes(session: AsyncSession) -> list[dict[str, Any]]:
    await _ensure_promo_schema(session)
    res = await session.execute(text("""
        select code, bonus, active, max_uses, used_count, expires_at
        from promo_codes
        order by code asc;
    """))
    return [dict(r) for r in res.mappings().all()]


async def _save_promo_codes(session: AsyncSession, codes: list[dict[str, Any]]) -> None:
    await _ensure_promo_schema(session)
    for c in codes:
        await session.execute(text("""
            insert into promo_codes (code, bonus, active, max_uses, used_count, expires_at, updated_at)
            values (:code, :bonus, :active, :max_uses, :used_count, :expires_at, now())
            on conflict (code) do update set
                bonus = excluded.bonus,
                active = excluded.active,
                max_uses = excluded.max_uses,
                used_count = excluded.used_count,
                expires_at = excluded.expires_at,
                updated_at = now();
        """), {
            "code": str(c.get("code") or "").upper(),
            "bonus": int(c.get("bonus") or 0),
            "active": bool(c.get("active", True)),
            "max_uses": c.get("max_uses"),
            "used_count": int(c.get("used_count") or 0),
            "expires_at": c.get("expires_at"),
        })


async def _get_promo_used(session: AsyncSession, user_id: int) -> list[str]:
    await _ensure_promo_schema(session)
    res = await session.execute(text("""
        select code from promo_usages where user_id = :user_id;
    """), {"user_id": user_id})
    return [str(r["code"]).upper() for r in res.mappings().all()]


async def _save_promo_used(session: AsyncSession, user_id: int, used: list[str]) -> None:
    await _ensure_promo_schema(session)
    for code in set([str(u).upper() for u in used]):
        await session.execute(text("""
            insert into promo_usages (user_id, code, used_at)
            values (:user_id, :code, now())
            on conflict (user_id, code) do nothing;
        """), {"user_id": user_id, "code": code})


async def redeem_promo(session: AsyncSession, user_id: int, code_raw: str) -> tuple[bool, str, int]:
    code = (code_raw or "").strip().upper()
    if not code:
        return False, "Введите промокод.", 0

    await _ensure_promo_schema(session)
    res = await session.execute(text("""
        select code, bonus, active, max_uses, used_count, expires_at
        from promo_codes
        where upper(code) = :code
        limit 1;
    """), {"code": code})
    promo = res.mappings().first()
    if not promo or not promo.get("active", True):
        return False, "Промокод не найден или не активен.", 0

    res = await session.execute(text("""
        select 1 from promo_usages where user_id = :user_id and code = :code limit 1;
    """), {"user_id": user_id, "code": code})
    if res.mappings().first():
        return False, "Вы уже использовали этот промокод.", 0

    expires_at = promo.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(str(expires_at))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return False, "Срок действия промокода истек.", 0
        except Exception:
            pass

    max_uses = promo.get("max_uses")
    used_count = int(promo.get("used_count") or 0)
    if max_uses is not None:
        try:
            if used_count >= int(max_uses):
                return False, "Лимит использований промокода исчерпан.", 0
        except Exception:
            pass

    bonus = int(promo.get("bonus") or 0)
    if bonus <= 0:
        return False, "Промокод настроен некорректно.", 0

    # increment used_count safely
    res = await session.execute(text("""
        update promo_codes
        set used_count = used_count + 1, updated_at = now()
        where upper(code) = :code
          and (max_uses is null or used_count < max_uses)
        returning used_count;
    """), {"code": code})
    if not res.mappings().first():
        return False, "Лимит использований промокода исчерпан.", 0

    new_balance = await apply_balance_delta(
        session,
        user_id,
        bonus,
        "promo_bonus",
        {"code": code, "bonus": bonus},
    )
    await log_event(
        session,
        "user_actions",
        "info",
        None,
        user_id,
        "promo_redeemed",
        None,
        {"code": code, "bonus": bonus},
    )
    await session.execute(text("""
        insert into promo_usages (user_id, code, used_at)
        values (:user_id, :code, now())
        on conflict (user_id, code) do nothing;
    """), {"user_id": user_id, "code": code})

    return True, f"✅ Промокод принят.\n\nНа баланс начислено {bonus} ₽.", new_balance


async def load_last_paid_order(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    q = text(
        """
        select id, amount_minor, currency, updated_at
        from payment_orders
        where user_id = :user_id
          and status = 'paid'
        order by updated_at desc
        limit 1;
        """
    )
    res = await session.execute(q, {"user_id": user_id})
    row = res.mappings().first()
    return dict(row) if row else None


async def load_payment_history(session: AsyncSession, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    q = text(
        """
        select o.id, o.amount_minor, o.currency, o.status, o.updated_at, o.meta,
               p.tg_file_id, p.mime_type
        from payment_orders o
        left join payment_proofs p on p.order_id = o.id
        where o.user_id = :user_id
        order by o.updated_at desc
        limit :limit;
        """
    )
    res = await session.execute(q, {"user_id": user_id, "limit": limit})
    return [dict(r) for r in res.mappings().all()]


async def get_user_settings(session: AsyncSession, user_id: int) -> dict[str, Any]:
    q = text(
        """
        insert into user_settings (user_id, notifications_enabled, language)
        values (:user_id, true, 'ru')
        on conflict (user_id) do update set user_id = user_settings.user_id
        returning user_id, notifications_enabled, language;
        """
    )
    res = await session.execute(q, {"user_id": user_id})
    row = res.mappings().first()
    return dict(row)


async def set_notifications(session: AsyncSession, user_id: int, enabled: bool) -> None:
    q = text(
        """
        insert into user_settings (user_id, notifications_enabled, language)
        values (:user_id, :enabled, 'ru')
        on conflict (user_id) do update set notifications_enabled = :enabled;
        """
    )
    await session.execute(q, {"user_id": user_id, "enabled": enabled})


async def insert_payment_order(session: AsyncSession, user_id: int, plan_id: int | None, amount_minor: int, currency: str, meta: dict) -> int:
    q = text(
        """
        insert into payment_orders (user_id, plan_id, amount_minor, currency, provider, status, meta)
        values (:user_id, :plan_id, :amount_minor, :currency, 'manual', 'pending', CAST(:meta AS jsonb))
        returning id;
        """
    )
    res = await session.execute(q, {"user_id": user_id, "plan_id": plan_id, "amount_minor": amount_minor, "currency": currency, "meta": json.dumps(meta)})
    row = res.mappings().first()
    return int(row["id"])


async def insert_payment_proof(session: AsyncSession, order_id: int, file_id: str, file_name: str | None, mime_type: str | None, file_size: int | None, file_data: bytes) -> None:
    q = text(
        """
        insert into payment_proofs (order_id, tg_file_id, file_name, mime_type, file_size, file_data)
        values (:order_id, :tg_file_id, :file_name, :mime_type, :file_size, :file_data);
        """
    )
    await session.execute(q, {
        "order_id": order_id,
        "tg_file_id": file_id,
        "file_name": file_name,
        "mime_type": mime_type,
        "file_size": file_size,
        "file_data": file_data,
    })


async def load_payment_proof(session: AsyncSession, order_id: int) -> dict[str, Any] | None:
    q = text(
        """
        select id, tg_file_id, file_name, mime_type, file_size, created_at
        from payment_proofs
        where order_id = :order_id
        order by id desc
        limit 1;
        """
    )
    res = await session.execute(q, {"order_id": order_id})
    row = res.mappings().first()
    return dict(row) if row else None


async def log_event(session: AsyncSession, category: str, level: str, tg_user_id: int | None, user_id: int | None, action: str, message: str | None, context: dict | None = None) -> None:
    q = text(
        """
        insert into logs(category, level, tg_user_id, user_id, action, message, context)
        values (:category, :level, :tg_user_id, :user_id, :action, :message, CAST(:context AS jsonb));
        """
    )
    await session.execute(q, {
        "category": category,
        "level": level,
        "tg_user_id": tg_user_id,
        "user_id": user_id,
        "action": action,
        "message": message,
        "context": json.dumps(context or {}),
    })


async def update_order_status(session: AsyncSession, order_id: int, status: str) -> None:
    q = text(
        """
        update payment_orders
        set status = :status, updated_at = now()
        where id = :id;
        """
    )
    await session.execute(q, {"id": order_id, "status": status})


async def load_order(session: AsyncSession, order_id: int) -> dict[str, Any] | None:
    q = text(
        """
        select o.id, o.user_id, o.plan_id, o.amount_minor, o.currency, o.status, o.meta,
               u.chat_id, u.username, u.tg_user_id
        from payment_orders o
        join tg_users u on u.id = o.user_id
        where o.id = :id
        limit 1;
        """
    )
    res = await session.execute(q, {"id": order_id})
    row = res.mappings().first()
    return dict(row) if row else None


async def create_vpn_profile_stub(session: AsyncSession, user_id: int, protocol: str, server_id: int, tag: str, access_until: datetime | None = None) -> str:
    q = text(
        """
        insert into vpn_profiles
          (user_id, protocol, server_id, status, provider_client_id, provider_meta, config_uri, access_until)
        values
          (:user_id, CAST(:protocol AS public.vpn_protocol), :server_id, 'active', :client_id, CAST(:meta AS jsonb), :config_uri, :access_until)
        returning config_uri;
        """
    )
    config_uri = f"{protocol}://{tag}-{user_id}@server-{server_id}"
    res = await session.execute(q, {
        "user_id": user_id,
        "protocol": protocol,
        "server_id": server_id,
        "client_id": f"{tag}-{user_id}",
        "meta": json.dumps({"source": tag}),
        "config_uri": config_uri,
        "access_until": access_until,
    })
    row = res.mappings().first()
    return row["config_uri"]


async def update_profile_access_until(session: AsyncSession, profile_id: int, access_until: datetime) -> bool:
    q = text(
        """
        update vpn_profiles
        set access_until = :access_until
        where id = :id
        returning id;
        """
    )
    res = await session.execute(q, {"id": profile_id, "access_until": access_until})
    row = res.mappings().first()
    return bool(row)


async def list_active_profiles(session: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    q = text(
        """
        select p.id, p.protocol, p.server_id, s.name as server_name, p.status,
               p.config_uri, p.config_file, p.created_at, p.access_until, p.provider_meta
        from vpn_profiles p
        left join vpn_servers s on s.id = p.server_id
        where p.user_id = :user_id
          and p.status = 'active'
          and p.revoked_at is null
        order by p.created_at desc;
        """
    )
    res = await session.execute(q, {"user_id": user_id})
    return [dict(r) for r in res.mappings().all()]


async def has_trial_used(session: AsyncSession, user_id: int) -> bool:
    q = text(
        """
        select 1
        from vpn_profiles
        where user_id = :user_id
          and provider_meta->>'source' = 'trial'
        limit 1;
        """
    )
    res = await session.execute(q, {"user_id": user_id})
    row = res.mappings().first()
    return bool(row)


async def get_balance(session: AsyncSession, user_id: int) -> int:
    q = text("""
        select balance_rub
        from user_balance
        where user_id = :user_id
        limit 1;
    """)
    res = await session.execute(q, {"user_id": user_id})
    row = res.mappings().first()
    return int(row["balance_rub"]) if row else 0


async def apply_balance_delta(session: AsyncSession, user_id: int, delta: int, reason: str, meta: dict | None = None) -> int:
    q = text("""
        insert into user_balance (user_id, balance_rub)
        values (:user_id, :delta)
        on conflict (user_id) do update
        set balance_rub = user_balance.balance_rub + :delta
        returning balance_rub;
    """)
    res = await session.execute(q, {"user_id": user_id, "delta": delta})
    row = res.mappings().first()
    new_balance = int(row["balance_rub"])

    q2 = text("""
        insert into balance_transactions (user_id, amount_rub, kind, reason, meta)
        values (:user_id, :amount, :kind, :reason, CAST(:meta AS jsonb));
    """)
    await session.execute(q2, {
        "user_id": user_id,
        "amount": delta,
        "kind": "credit" if delta > 0 else "debit",
        "reason": reason,
        "meta": json.dumps(meta or {}),
    })

    return new_balance
