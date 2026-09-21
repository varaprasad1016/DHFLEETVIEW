# Sending the camera setup commands

The platform queues the setup commands; something then has to collect them and
send them as text messages. The queue does not care what that something is.

**The chosen route: the Caburn SIM portal API.** The SIMs in these cameras come
from Caburn, whose portal can send texts over an API, so there is no handset to
keep charged and nothing to go wrong in a drawer. This is not built yet - it
needs the portal's API documentation and a key. When those arrive, the work is
one service that drains the same queue these endpoints already expose:

    claim:   GET  /api/dvr/outbox?limit=5      -> the messages waiting
    report:  POST /api/dvr/outbox/<id>         -> {"sent": true} or false

A message nobody reports on is offered again after five minutes, so a failed
send is never silently lost.

Until something is connected, queued commands simply wait, and the Camera setup
commands screen says so rather than letting a full queue look like a sent one.

## The fallback: a spare Android phone

Kept here because it needs no third party and can be stood up in ten minutes if
a camera is needed urgently. A spare handset with the DH Group SIM
() polls the queue and sends each message itself.

## What the phone needs to know

    Collect from:  https://dhfleetview.co.uk/tacho/api/dvr/outbox?limit=1
    Report to:     https://dhfleetview.co.uk/tacho/api/dvr/outbox/<id>
    Header:        X-Gateway-Key: <the key>

The key is the DVR_SMS_KEY line in C:\tachograph-server\.env on this server.
Read it there and type it into the phone; it is not repeated here, and it should
not be left in a note or a chat. Anyone holding it can send texts from that SIM.
To change it, edit that line, restart the tacho-api scheduled task, and re-enter
the new key on the phone.

## The flow, in Automate (LlamaLab - free, and enough blocks for this)

1. Install Automate from the Play Store. Allow it to send SMS when it asks.
2. New flow, then these blocks in a loop:

       Interval            every 1 minute
       HTTP Request        GET the collect URL above
                           Headers: X-Gateway-Key = the key above
                           Response body -> variable  body
       JSON Decode         body -> variable  queue
       Decision            queue["messages"] is empty?  -> back to Interval
       SMS Send            To:      queue["messages"][0]["to"]
                           Message: queue["messages"][0]["body"]
       HTTP Request        POST to the report URL with
                           queue["messages"][0]["id"] on the end,
                           header X-Gateway-Key, body: {"sent": true}
       Goto                Interval

3. Start the flow and leave the phone on charge. Turn battery optimisation off
   for Automate, or Android will stop it overnight.

MacroDroid works the same way if you prefer it: a Regular Interval trigger, an
HTTP Request action with the header, JSON parsed to a dictionary, then Send SMS.

## Checking it

Open Camera setup commands in the platform (Settings menu, administrators only),
pick a camera and send. The message should show as Sent within a minute or two.
If it stays on Sending, the phone has not collected it - check the flow is
running and the key matches. A message the phone claims but never reports is
offered again after five minutes, so nothing is lost if it drops off signal.

## The commands that are saved

    *admin,111111,SETPROTOCOL:protocol1=3,protocol2=4
    *admin,111111,SETNIP:1,109.228.53.195:9808;
    *admin,111111,SETNIP:2,139.159.218.255:6608;
    *GETSTATE4G
    *GETSTATEBASE

They are sent to the Mobile No. read off the camera's label, which is stored on
the vehicle when it is added. Edit them on the same page if the servers change.
