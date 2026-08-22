-- DealBench schema (SQLite).  Mirrors spec Section 7.
-- The live negotiation runs in memory (control/session_state.py); this is the
-- durable log so a session, its messages, and interventions survive a restart
-- and can be replayed / audited.

CREATE TABLE IF NOT EXISTS sessions (
  id                       TEXT PRIMARY KEY,
  title                    TEXT,
  currency                 TEXT,
  buyer_constraints        TEXT,   -- JSON: reservation_price, opening_offer, deadline, must_haves
  seller_constraints       TEXT,   -- JSON
  seller_reservation_price REAL,
  buyer_reservation_price  REAL,
  deadline_round           INTEGER,
  status                   TEXT,   -- active | agreed | walked_away | max_rounds
  final_price              REAL,
  created_at               TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id               TEXT REFERENCES sessions(id),
  round                    INTEGER,
  side                     TEXT,   -- buyer | seller
  source                   TEXT,   -- agent | human
  content                  TEXT,
  quoted_price             REAL,
  detected_tactic          TEXT,
  tactic_confidence        REAL,
  validator_price_ok       BOOLEAN,
  validator_leak_detected  BOOLEAN,
  backend                  TEXT,   -- openrouter | ollama | mock | human
  timestamp                TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interventions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT REFERENCES sessions(id),
  side         TEXT,
  action       TEXT,   -- take_over | return_to_ai
  round        INTEGER,
  timestamp    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_interventions_session ON interventions(session_id);
