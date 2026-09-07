-- Removes the 0,0 positions written by TaskCnmsSync for terminals that have
-- never reported to CNMS (BRP5G1 / 0442795034 since 2026-09-03).
-- RUN ONLY WITH THE SERVER STOPPED. Back up data/database.mv.db first.

-- 1. What is about to go
SELECT COUNT(*) AS junk_rows FROM tc_positions WHERE latitude = 0 AND longitude = 0;
SELECT deviceid, COUNT(*) AS rows_per_device
  FROM tc_positions WHERE latitude = 0 AND longitude = 0
  GROUP BY deviceid;

-- 2. Drop device pointers into those rows (no FK is declared, so a dangling
--    positionid would silently break the device in the UI).
UPDATE tc_devices SET positionid = NULL
  WHERE positionid IN (SELECT id FROM tc_positions WHERE latitude = 0 AND longitude = 0);
UPDATE tc_devices SET motionpositionid = NULL
  WHERE motionpositionid IN (SELECT id FROM tc_positions WHERE latitude = 0 AND longitude = 0);

-- 3. Events reference positions too
DELETE FROM tc_events
  WHERE positionid IN (SELECT id FROM tc_positions WHERE latitude = 0 AND longitude = 0);

-- 4. Delete the junk
DELETE FROM tc_positions WHERE latitude = 0 AND longitude = 0;

-- 5. Reclaim the file (H2 does not shrink on its own)
CHECKPOINT SYNC;

-- 6. Verify: expect 0
SELECT COUNT(*) AS remaining FROM tc_positions WHERE latitude = 0 AND longitude = 0;
