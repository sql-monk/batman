CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS device (
  id TEXT PRIMARY KEY,
  name TEXT,
  ip TEXT,
  port INTEGER DEFAULT 80,
  fw TEXT,
  status TEXT DEFAULT 'discovered',   -- discovered | connected | unclaimed | manual
  first_seen INTEGER,
  last_seen INTEGER,
  sink_ok INTEGER DEFAULT 0,
  config_json TEXT
);

CREATE TABLE IF NOT EXISTS boot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  t_service INTEGER NOT NULL,
  uptime0 INTEGER NOT NULL,
  reset_reason INTEGER
);

CREATE TABLE IF NOT EXISTS sample (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  t INTEGER NOT NULL,
  seq INTEGER,
  uptime INTEGER,
  state TEXT,
  b1_u REAL, b1_i REAL, b1_t REAL, b1_soc REAL, b1_sw TEXT,
  b1_ah_in REAL, b1_ah_out REAL, b1_wh_in REAL, b1_wh_out REAL,
  b2_u REAL, b2_i REAL, b2_t REAL, b2_soc REAL, b2_sw TEXT,
  b2_ah_in REAL, b2_ah_out REAL, b2_wh_in REAL, b2_wh_out REAL,
  load_u REAL, load_i REAL,
  dps_uin REAL, dps_uout REAL, dps_iout REAL, dps_uset REAL, dps_iset REAL,
  dps_on INTEGER, dps_cc INTEGER, dps_prot INTEGER, dps_k INTEGER,
  rssi INTEGER,
  warn TEXT,
  raw TEXT
);
CREATE INDEX IF NOT EXISTS ix_sample_dev_t ON sample(device_id, t);

CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  t INTEGER NOT NULL,
  seq INTEGER,
  uptime INTEGER,
  event TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT,
  reason TEXT,
  data TEXT
);
CREATE INDEX IF NOT EXISTS ix_event_dev_t ON event(device_id, t);

CREATE TABLE IF NOT EXISTS gap (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  t_from INTEGER NOT NULL,
  t_to INTEGER,
  seq_from INTEGER,
  seq_to INTEGER,
  kind TEXT NOT NULL   -- no_data | seq_gap | reboot
);
CREATE INDEX IF NOT EXISTS ix_gap_dev ON gap(device_id, t_from);

CREATE TABLE IF NOT EXISTS agg_hour (
  device_id TEXT NOT NULL, bat INTEGER NOT NULL, t_start INTEGER NOT NULL,
  ah_in REAL, ah_out REAL, wh_in REAL, wh_out REAL,
  u_min REAL, u_max REAL, u_avg REAL, i_min REAL, i_max REAL,
  t_min REAL, t_max REAL, soc_min REAL, soc_max REAL,
  s_charge INTEGER, s_float INTEGER, s_idle INTEGER, s_fault INTEGER,
  samples INTEGER, gaps INTEGER, partial INTEGER DEFAULT 0,
  PRIMARY KEY (device_id, bat, t_start)
);

CREATE TABLE IF NOT EXISTS agg_day (
  device_id TEXT NOT NULL, bat INTEGER NOT NULL, t_start INTEGER NOT NULL,
  ah_in REAL, ah_out REAL, wh_in REAL, wh_out REAL,
  u_min REAL, u_max REAL, u_avg REAL, i_min REAL, i_max REAL,
  t_min REAL, t_max REAL, soc_min REAL, soc_max REAL,
  s_charge INTEGER, s_float INTEGER, s_idle INTEGER, s_fault INTEGER,
  samples INTEGER, gaps INTEGER, partial INTEGER DEFAULT 0,
  PRIMARY KEY (device_id, bat, t_start)
);

CREATE TABLE IF NOT EXISTS cycle (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL, bat INTEGER NOT NULL,
  t_start INTEGER NOT NULL, t_end INTEGER,
  ah_in REAL, ah_out REAL, wh_in REAL, wh_out REAL,
  eff REAL, duration_s INTEGER, end_reason TEXT, u_start REAL, i_tail REAL
);
CREATE INDEX IF NOT EXISTS ix_cycle_dev ON cycle(device_id, t_start);

CREATE TABLE IF NOT EXISTS notification (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  t INTEGER NOT NULL, device_id TEXT, kind TEXT NOT NULL, text TEXT, sent INTEGER DEFAULT 0
);

INSERT OR REPLACE INTO meta(key, value) VALUES ('schema', '1');
