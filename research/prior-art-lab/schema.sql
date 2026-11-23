-- One event with a fixed number of seats, and one row per seat taken.
CREATE TABLE events (
    id       int PRIMARY KEY,
    capacity int NOT NULL
);

CREATE TABLE reservations (
    id       bigserial PRIMARY KEY,
    event_id int NOT NULL REFERENCES events (id),
    student  int NOT NULL
);

INSERT INTO events (id, capacity) VALUES (1, 10);
