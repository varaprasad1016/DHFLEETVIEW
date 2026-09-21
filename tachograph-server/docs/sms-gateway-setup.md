# Setting up the sending phone

The platform queues the camera setup commands; a spare Android phone with the
DH Group SIM () collects them and sends them as ordinary
text messages. Nothing else on the phone is touched, and the phone can only see
the queue - it has no login to the platform.

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
