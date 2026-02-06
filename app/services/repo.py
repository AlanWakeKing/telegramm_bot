from __future__ import annotations

import json
from datetime import datetime
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
