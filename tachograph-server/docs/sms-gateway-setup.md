# Sending the camera setup commands

The platform queues the setup commands; something then has to collect them and
send them as text messages. The queue does not care what that something is.

**The chosen route: the Caburn Insight portal API.** The SIMs in these cameras
come from Caburn (CSL Group), whose Insight portal can send texts to its own
SIMs, so there is no handset to keep charged. The sending side is built: the
server drains the queue itself and posts each message to the provider. All that
is left is to tell it where to post, which is done in C:\tachograph-server\.env:

    SMS_URL=              the provider's send-message endpoint
    SMS_METHOD=POST       whatever the endpoint expects
    SMS_AUTH_HEADER=      the header the key goes in, e.g. Authorization
    SMS_AUTH_VALUE=       the key itself, e.g. "Bearer abc123"
    SMS_CONTENT_TYPE=application/json
    SMS_BODY_TEMPLATE={"to": "{to}", "message": "{text}"}

{to} and {text} are filled in per message; the rest is copied from the
provider's documentation. A form-style provider takes a template like
`to={to}&text={text}` with SMS_CONTENT_TYPE set to
application/x-www-form-urlencoded. Restart the tacho-api task after editing.

Nothing sends while SMS_URL is empty, which is how the server ships: the queue
simply waits. Once it is set, the server checks the queue every twenty seconds,
sends up to five at a time, and records against each message whatever reference
the provider gives back - or, on a refusal, the provider's own words, so
"SIM not active" reaches the office screen intact. A message claimed but never
finished is retried after five minutes.

**Before switching it on, clear out any test messages.** Everything queued goes
out the moment a provider is configured, including anything addressed to a
number typed in by mistake.

## The fallback: a spare Android phone

Kept here because it needs no third party. A spare handset polls the same queue
and sends each message itself; the endpoints below are what it uses, and they
are unchanged by the above.

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
