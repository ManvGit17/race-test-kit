-- The demo shop: events with a fixed number of seats, and who holds them.
-- Simplified from festrush-ticketing: no orders, holds, expiry or payments.

CREATE TABLE IF NOT EXISTS shop_events (
    id       int PRIMARY KEY,
    capacity int NOT NULL CHECK (capacity >= 0),
    -- Used only by atomic_update: seats claimed so far, kept next to the capacity.
    claimed  int NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS shop_reservations (
    id       bigserial PRIMARY KEY,
    event_id int NOT NULL REFERENCES shop_events (id),
    student  int NOT NULL,
    UNIQUE (event_id, student)
);

-- Used only by skip_locked: one row per seat, taken by pointing it at a reservation.
CREATE TABLE IF NOT EXISTS shop_seats (
    id             bigserial PRIMARY KEY,
    event_id       int NOT NULL REFERENCES shop_events (id),
    reservation_id bigint REFERENCES shop_reservations (id)
);

CREATE INDEX IF NOT EXISTS shop_seats_free ON shop_seats (event_id) WHERE reservation_id IS NULL;

-- Orders that can be paid or cancelled, once (the interleave scenario).
CREATE TABLE IF NOT EXISTS shop_orders (
    id     int PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('pending', 'paid', 'cancelled')),
    amount int NOT NULL
);

-- Money taken. No foreign key and no unique key on purpose: the broken versions must be able
-- to write the duplicates the tests look for.
CREATE TABLE IF NOT EXISTS shop_charges (
    id              bigserial PRIMARY KEY,
    order_id        int NOT NULL,
    amount          int NOT NULL,
    idempotency_key text
);

-- The fix for duplicate payments: the key is claimed by inserting it, which only one
-- transaction can do.
CREATE TABLE IF NOT EXISTS shop_idempotency_keys (
    key       text PRIMARY KEY,
    charge_id bigint
);

-- A balance topped up by many requests at once (the lost_update scenario).
CREATE TABLE IF NOT EXISTS shop_wallets (
    id      int PRIMARY KEY,
    balance int NOT NULL
);
