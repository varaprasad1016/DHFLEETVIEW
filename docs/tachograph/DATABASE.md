# Tachograph Database

## Migrations

`schema/changelog-6.16.0.xml` created the module's first tables; `changelog-6.17.0.xml` added file
metadata, job progress, company-card identity, delivery and audit. Both are included from
`changelog-master.xml`.

## A trap worth knowing about

The storage layer writes a zero identifier as SQL `NULL` for **any column whose name ends in
`Id`** (`QueryBuilder.setObject`, which passes `nullIfZero` for those). So a column like `groupid`
or `userid` must be nullable whenever zero is a legitimate value — and it often is: group zero
means "every vehicle on the server", and user zero means "the server did this, not a person".

A `NOT NULL` constraint on such a column does not enforce anything useful; it just makes the
zero case impossible to save. `changelog-6.17` drops that constraint from
`tc_tachograph_bridges.groupid` for exactly this reason.

## Tables

### tc_tachograph_configurations
One row per device. `deviceid` UNIQUE, `enabled`, `driverdownloadenabled`,
`vehicledownloadenabled`, `driverdownloadintervaldays` (28), `vehicledownloadintervaldays` (90),
`lastdriverdownload`, `lastvehicledownload`, `nextdriverdownload`, `nextvehicledownload`,
`createdat`, `updatedat`.

The `next*` columns are the compliance clock and drive the scheduler.

### tc_tachograph_download_jobs
`deviceid`, `requestedby`, `downloadtype` (DRIVER/VEHICLE), `requestedfrom`, `requestedto`,
`status`, `progress`, `progressdetail`, `retrycount`, `clienttype`, `cancelrequested`, `bridgeid`,
`queuedat`, `startedat`, `attemptstartedat`, `completedat`, `failedat`, `nextretryat`,
`errorcode`, `errormessage`, `fileid`, `createdat`, `updatedat`.

Statuses: `QUEUED`, `WAITING_FOR_DEVICE`, `WAITING_FOR_BRIDGE`, `REQUESTING`, `DOWNLOADING`,
`PROCESSING`, `COMPLETED`, `FAILED`, `CANCELLED`.

Indexes on `deviceid`, `status`, `nextretryat`.

`progress` and `progressdetail` are written as a download runs, which is what lets the web app show
movement on a transfer that takes half an hour. `cancelrequested` is how a cancel reaches a job
that is already executing.

### tc_tachograph_files
`downloadjobid`, `deviceid`, `groupid`, `filename`, `filetype`, `filesize`, `sha256`,
`storagepath`, `validationstatus`, `validationmessage`, `downloadedat`, `processedat`, `createdat`,
and the fields read out of the DDD itself: `vehicleregistration`, `vehicleidentification`,
`vehicleunitserial`, `cardnumber`, `periodfrom`, `periodto`, `generation`, `blocks`, `clienttype`.

Indexes on `deviceid`, `downloadjobid`, `sha256`.

`sha256` is recorded when the vehicle produced the bytes and is returned in the `X-File-SHA256`
header on every retrieval, so a recipient can confirm nothing altered them.

### tc_tachograph_bridges
`bridgeid` UNIQUE, `groupid` (nullable, see above), `name`, `status`, `tokenhash`, `readerstatus`,
`cardstatus`, `cardidentifier`, `cardtype`, `cardholder`, `cardissuer`, `cardvalidityfrom`,
`cardvalidityto`, `cardcheckedat`, `cardcheckerror`, `hostname`, `softwareversion`,
`lastheartbeat`, `registeredat`, `lastseenat`, `pairingcodehash`, `pairingcodeexpiresat`.

`tokenhash` and `pairingcodehash` are SHA-256 digests and are never serialised by the API.

### tc_tachograph_forward_targets
`groupid` (nullable), `name`, `provider` (CONVEY/GENERIC), `transport` (SFTP/HTTPS), `enabled`,
`host`, `port`, `username`, `secret`, `remotepath`, `url`, `hostkey`, `filenamepattern`,
`forwarddriver`, `forwardvehicle`, `laststatus`, `lastmessage`, `lastattemptat`, `lastsuccessat`,
`createdat`, `updatedat`.

`secret` is AES-GCM ciphertext under a key derived from `tacho.forward.secret`, which lives in the
configuration file. Reading this table alone does not yield usable bureau credentials.

### tc_tachograph_forwards
One row per file per target. `fileid`, `targetid`, `deviceid`, `status`, `attempts`, `remotename`,
`errorcode`, `errormessage`, `queuedat`, `nextattemptat`, `lastattemptat`, `completedat`,
`createdat`, `updatedat`.

Statuses: `QUEUED`, `SENDING`, `DELIVERED`, `FAILED`, `CANCELLED`. Indexed on
(`status`, `nextattemptat`) for the delivery worker and on `fileid` for the file detail view.

This table is the evidence that a legally required file reached where it had to, which is the
question an audit actually asks.

### tc_tachograph_audit
`userid` (nullable), `deviceid` (nullable), `action`, `detail`, `actor`, `createdat`.
Indexed on `createdat` and `deviceid`.

`actor` records who acted when it was not a logged-in user: `scheduler`, `system`, or a bridge id.

### tc_tachograph_auth_sessions
From 6.16, retained for the auth-session audit trail. `downloadjobid`, `bridgeid`, `status`,
`resultcode`, `resultmessage`, `requestedat`, `startedat`, `completedat`, `expiresat`.

## Retention

Nothing here is deleted automatically. Operators must keep tachograph data for a year, so file
deletion is an explicit administrator action.
