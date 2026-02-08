-- Migrate bot_settings JSON into normalized tables
-- Run in Postgres (psql or your DB tool) on the production DB.

begin;

-- Ensure schemas exist (matches repo.py)
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
create unique index if not exists ux_support_tickets_user_id_user_ticket_id
on support_tickets(user_id, user_ticket_id);

create table if not exists support_messages (
    id bigserial primary key,
    ticket_id bigint not null references support_tickets(id) on delete cascade,
    sender text not null,
    text text not null,
    created_at timestamptz not null default now()
);

-- Clean target tables to avoid duplicate user_ticket_id conflicts on reruns
delete from support_messages;
delete from support_tickets;

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

create table if not exists promo_usages (
    id bigserial primary key,
    user_id bigint not null references tg_users(id) on delete cascade,
    code text not null references promo_codes(code) on delete cascade,
    used_at timestamptz not null default now(),
    unique(user_id, code)
);

create table if not exists referral_wallets (
    user_id bigint primary key references tg_users(id) on delete cascade,
    balance integer not null default 0,
    updated_at timestamptz not null default now()
);

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
create unique index if not exists ux_referral_pending_order_id
on referral_pending(order_id);

create table if not exists referral_withdrawals (
    id bigserial primary key,
    user_id bigint not null references tg_users(id) on delete cascade,
    amount integer not null,
    status text not null default 'pending',
    meta jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Promo codes
insert into promo_codes (code, bonus, active, max_uses, used_count, expires_at, updated_at)
select
    (item->>'code')::text as code,
    coalesce(nullif(item->>'bonus','')::int, 0) as bonus,
    coalesce(nullif(item->>'active','')::boolean, true) as active,
    nullif(item->>'max_uses','')::int as max_uses,
    coalesce(nullif(item->>'used_count','')::int, 0) as used_count,
    nullif(item->>'expires_at','')::timestamptz as expires_at,
    now()
from bot_settings, jsonb_array_elements(value_json) as item
where key = 'PROMO_CODES'
on conflict (code) do update set
    bonus = excluded.bonus,
    active = excluded.active,
    max_uses = excluded.max_uses,
    used_count = excluded.used_count,
    expires_at = excluded.expires_at,
    updated_at = now();

-- Promo usages
insert into promo_usages (user_id, code)
select
    regexp_replace(key, '^PROMO_USED_', '')::bigint as user_id,
    jsonb_array_elements_text(value_json) as code
from bot_settings
where key like 'PROMO_USED_%'
on conflict do nothing;

-- Referral wallets
insert into referral_wallets (user_id, balance, updated_at)
select
    regexp_replace(key, '^REF_WALLET_', '')::bigint as user_id,
    coalesce(nullif(value_json->>'balance','')::int, 0) as balance,
    now()
from bot_settings
where key like 'REF_WALLET_%'
on conflict (user_id) do update set
    balance = excluded.balance,
    updated_at = now();

-- Referral pending
insert into referral_pending (order_id, referrer_user_id, referred_user_id, amount_minor, bonus_minor, percent, due_at, created_at)
select
    nullif(regexp_replace(item->>'order_id', '\\D', '', 'g'), '')::bigint,
    nullif(regexp_replace(item->>'referrer_user_id', '\\D', '', 'g'), '')::bigint,
    nullif(regexp_replace(item->>'referred_user_id', '\\D', '', 'g'), '')::bigint,
    coalesce(nullif(item->>'amount_minor','')::int, 0),
    coalesce(nullif(item->>'bonus_minor','')::int, 0),
    coalesce(nullif(item->>'percent','')::int, 0),
    (item->>'due_at')::timestamptz,
    coalesce(nullif(item->>'created_at','')::timestamptz, now())
from bot_settings, jsonb_array_elements(value_json) as item
where key = 'REFERRAL_PENDING'
  and nullif(regexp_replace(item->>'order_id', '\\D', '', 'g'), '') is not null
  and nullif(regexp_replace(item->>'referrer_user_id', '\\D', '', 'g'), '') is not null
  and nullif(regexp_replace(item->>'referred_user_id', '\\D', '', 'g'), '') is not null
on conflict (order_id) do nothing;

-- Referral withdrawals (with ids)
with src as (
    select
        case
            when regexp_replace(item->>'id', '\\D', '', 'g') ~ '^[0-9]+$'
                then regexp_replace(item->>'id', '\\D', '', 'g')::bigint
            else null
        end as id_num,
        nullif(regexp_replace(item->>'user_id', '\\D', '', 'g'), '')::bigint as user_id,
        coalesce(nullif(item->>'amount','')::int, 0) as amount,
        coalesce(nullif(item->>'status',''), 'pending') as status,
        item->'meta' as meta,
        coalesce(nullif(item->>'created_at','')::timestamptz, now()) as created_at,
        coalesce(nullif(item->>'updated_at','')::timestamptz, now()) as updated_at
    from bot_settings, jsonb_array_elements(value_json) as item
    where key = 'REFERRAL_WITHDRAWALS'
)
insert into referral_withdrawals (id, user_id, amount, status, meta, created_at, updated_at)
select id_num, user_id, amount, status, meta, created_at, updated_at
from src
where id_num is not null
  and user_id is not null
on conflict (id) do update set
    user_id = excluded.user_id,
    amount = excluded.amount,
    status = excluded.status,
    meta = excluded.meta,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at;

-- Referral withdrawals (without ids)
with src as (
    select
        case
            when regexp_replace(item->>'id', '\\D', '', 'g') ~ '^[0-9]+$'
                then regexp_replace(item->>'id', '\\D', '', 'g')::bigint
            else null
        end as id_num,
        nullif(regexp_replace(item->>'user_id', '\\D', '', 'g'), '')::bigint as user_id,
        coalesce(nullif(item->>'amount','')::int, 0) as amount,
        coalesce(nullif(item->>'status',''), 'pending') as status,
        item->'meta' as meta,
        coalesce(nullif(item->>'created_at','')::timestamptz, now()) as created_at,
        coalesce(nullif(item->>'updated_at','')::timestamptz, now()) as updated_at
    from bot_settings, jsonb_array_elements(value_json) as item
    where key = 'REFERRAL_WITHDRAWALS'
)
insert into referral_withdrawals (user_id, amount, status, meta, created_at, updated_at)
select user_id, amount, status, meta, created_at, updated_at
from src
where id_num is null
  and user_id is not null;

-- Support tickets
with src as (
    select
        case
            when regexp_replace(item->>'id', '\\D', '', 'g') ~ '^[0-9]+$'
                then regexp_replace(item->>'id', '\\D', '', 'g')::bigint
            else null
        end as id,
        nullif(regexp_replace(item->>'user_id', '\\D', '', 'g'), '')::bigint as user_id,
        nullif(regexp_replace(item->>'tg_user_id', '\\D', '', 'g'), '')::bigint as tg_user_id,
        nullif(regexp_replace(item->>'chat_id', '\\D', '', 'g'), '')::bigint as chat_id,
        nullif(item->>'username','') as username,
        coalesce(nullif(item->>'status',''), 'open') as status,
        nullif(item->>'user_ticket_id','')::int as user_ticket_id,
        coalesce(nullif(item->>'created_at','')::timestamptz, now()) as created_at,
        coalesce(nullif(item->>'updated_at','')::timestamptz, now()) as updated_at,
        coalesce(nullif(item->>'message_count','')::int, 0) as message_count
    from bot_settings, jsonb_array_elements(value_json) as item
    where key = 'SUPPORT_TICKETS'
),
numbered as (
    select
        *,
        row_number() over (partition by user_id order by created_at, id) as user_ticket_id_fixed
    from src
)
insert into support_tickets (id, user_id, tg_user_id, chat_id, username, status, user_ticket_id, created_at, updated_at, message_count)
select id, user_id, tg_user_id, chat_id, username, status, user_ticket_id_fixed, created_at, updated_at, message_count
from numbered
where id is not null
  and user_id is not null
  and tg_user_id is not null
  and chat_id is not null
on conflict (id) do update set
    user_id = excluded.user_id,
    tg_user_id = excluded.tg_user_id,
    chat_id = excluded.chat_id,
    username = excluded.username,
    status = excluded.status,
    user_ticket_id = excluded.user_ticket_id,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    message_count = excluded.message_count;

-- Support messages
insert into support_messages (ticket_id, sender, text, created_at)
select
    nullif(regexp_replace(item->>'ticket_id', '\\D', '', 'g'), '')::bigint as ticket_id,
    coalesce(nullif(item->>'sender',''), 'user') as sender,
    coalesce(item->>'text','') as text,
    coalesce(nullif(item->>'created_at','')::timestamptz, now()) as created_at
from bot_settings, jsonb_array_elements(value_json) as item
where key = 'SUPPORT_MESSAGES'
  and nullif(regexp_replace(item->>'ticket_id', '\\D', '', 'g'), '') is not null;

-- Reset sequences
select setval('support_tickets_id_seq', coalesce((select max(id) from support_tickets), 0), true);
select setval('support_messages_id_seq', coalesce((select max(id) from support_messages), 0), true);
select setval('referral_withdrawals_id_seq', coalesce((select max(id) from referral_withdrawals), 0), true);

commit;
