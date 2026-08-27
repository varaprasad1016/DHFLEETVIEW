# Tachograph Database

## Migration

`schema/changelog-6.16.0.xml` (included from `changelog-master.xml`).

## Tables

### tc_tachograph_configurations
One row per device.
`deviceid` UNIQUE, `enabled`, `driverdownloadenabled`, `vehicledownloadenabled`,
`driverdownloadintervaldays` (default 28), `vehicledownloadintervaldays` (default 90),
`lastdriverdownload`, `lastvehicledownload`, `nextdriverdownload`, `nextvehicledownload`,
`createdat`, `updatedat`.

### tc_tachograph_download_jobs
`deviceid`, `requestedby`, `downloadtype` (DRIVER/VEHICLE), `requestedfrom/to`,
`status` (QUEUED, WAITING_FOR_DEVICE, WAITING_FOR_BRIDGE, REQUESTING, DOWNLOADING,
PROCESSING, COMPLETED, FAILED, CANCELLED), `progress`, `retrycount`,
`queuedat`, `startedat`, `completedat`, `failedat`, `nextretryat`,
`errorcode`, `errormessage`, `fileid`, `createdat`, `updatedat`.

Indexes: `deviceid`, `status`, `nextretryat`.

### tc_tachograph_files
`downloadjobid`, `deviceid`, `filename`, `filetype`, `filesize`, `sha256`,
`storagepath`, `validationstatus` (PENDING/VALID/INVALID),
`downloadedat`, `processedat`, `createdat`.
Indexes: `deviceid`, `downloadjobid`.

### tc_tachograph_bridges
`bridgeid` UNIQUE, `groupid`, `name`, `status` (ONLINE/OFFLINE),
`tokenhash`, `readerstatus`, `cardstatus`, `cardidentifier`, `cardtype`,
`cardvalidityto`, `softwareversion`, `lastheartbeat`, `registeredat`,
`lastseenat`, `pairingcodehash`, `pairingcodeexpiresat`.

### tc_tachograph_auth_sessions
`downloadjobid`, `bridgeid`, `status` (PENDING/IN_PROGRESS/COMPLETED/FAILED/EXPIRED),
`resultcode`, `resultmessage`, `requestedat`, `startedat`, `completedat`, `expiresat`.

## Naming

All tables use the existing `tc_` prefix and Liquibase conventions (`changelog-*.xml`).
