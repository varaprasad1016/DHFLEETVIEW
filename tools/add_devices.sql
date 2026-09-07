-- Add 3 CNMS-linked vehicles: name = registration, cmsv9DeviceId = the ID label.
-- Granted to admin (user 2, admin@dhfleetview.co.uk). All admins see them anyway.
INSERT INTO tc_devices (id, name, uniqueid, category, attributes, phone) VALUES
 (68, 'G11JHL', '0442795040', 'truck', '{"cmsv9DeviceId":"0442795040"}', '07940732225'),
 (69, 'G12JHL', '0442795039', 'truck', '{"cmsv9DeviceId":"0442795039"}', '07940732231'),
 (70, 'G14PRB', '0442795038', 'truck', '{"cmsv9DeviceId":"0442795038"}', '07940732127');

INSERT INTO tc_user_device (userid, deviceid) VALUES
 (2, 68), (2, 69), (2, 70);

CHECKPOINT SYNC;

SELECT id, name, uniqueid, category, attributes, phone FROM tc_devices WHERE id IN (68, 69, 70);
SELECT userid, deviceid FROM tc_user_device WHERE deviceid IN (68, 69, 70);
