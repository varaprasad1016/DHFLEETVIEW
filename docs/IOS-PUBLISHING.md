# Publishing DH FleetView to the App Store

One-time setup so that every push to `main` uploads a build to TestFlight, the
way pushes already upload to Google Play.

You need no Mac. The build runs on a GitHub-hosted macOS runner. Every command
below runs in Git Bash on Windows.

## What "auto-publish" can and cannot mean on iOS

Google Play accepts an upload straight into a **production draft** that you roll
out with a button. Apple requires human review of every version before it
reaches the App Store, so there is no equivalent draft.

The closest safe equivalent, and what this sets up:

| | Android | iOS |
|---|---|---|
| Every push to `main` | uploads to Play, production draft | uploads to **TestFlight** |
| Goes live when | you roll out the draft | you submit for review and Apple approves |

Builds appear in TestFlight within about 10–30 minutes of the workflow finishing,
after Apple finishes processing. Promote one to the App Store from App Store
Connect when you want a release. Automating the review submission is possible
but a bad idea: a bad build then reaches customers with nobody having looked.

## Step 1 — Register the App ID

<https://developer.apple.com/account/resources/identifiers/list>

**Identifiers → + → App IDs → App**

- Description: `DH FleetView`
- Bundle ID: **Explicit**, `com.dhgroup.fleetview`
- Capabilities: tick only what the app actually uses. Push notifications are
  already in the project, so tick **Push Notifications**.

## Step 2 — Team ID (already done)

The Team ID for the paid account is **`ZAWG6D59DU`**, and
`traccar-manager/ios/Runner.xcodeproj/project.pbxproj` has been updated to
match. It previously held `YW49KTJKFW`, from an earlier free or personal team.

Nothing to do here unless the membership changes. If it ever does, update that
file **and** the `APPLE_TEAM_ID` secret together.

Both, because Xcode resolves build settings by precedence and a value set on
the target wins over one supplied by the CI configuration. Setting only the
secret would leave the archive signed with whatever `project.pbxproj` says, and
the failure is a signing error that never names the team as the cause.

Confirm at any time under **Membership details** at
<https://developer.apple.com/account>.

## Step 3 — Create the App Store Connect record

<https://appstoreconnect.apple.com/apps> → **+ → New App**

- Platform: iOS
- Name: `DH FleetView` (must be unique across the whole App Store)
- Primary language: English (UK)
- Bundle ID: pick `com.dhgroup.fleetview`
- SKU: anything internal and stable, e.g. `dhfleetview-ios`

**Do this before the first upload.** Uploads to an app record that does not
exist are rejected.

## Step 4 — Create a distribution certificate

Apple signs with a certificate whose private key never leaves your control, so
you generate the key, ask Apple to certify it, then bundle both into a `.p12`.

In Git Bash, in a directory you will delete afterwards:

```bash
# 1. Private key and certificate signing request
openssl genrsa -out ios_distribution.key 2048
openssl req -new -key ios_distribution.key -out ios_distribution.csr \
  -subj "//emailAddress=you@dhgroup.co.uk\CN=DH FleetView Distribution\C=GB"
```

The doubled slash and backslashes are not a typo. Git Bash rewrites anything
that looks like a Unix path into a Windows one, so the ordinary
`-subj "/emailAddress=...`" silently becomes a filename and openssl rejects it.
This form survives that. In PowerShell or on Linux, use the normal
`"/emailAddress=.../CN=.../C=GB"`.

Upload `ios_distribution.csr` at
<https://developer.apple.com/account/resources/certificates/add> →
**Apple Distribution** → download `distribution.cer`.

```bash
# 2. Combine Apple's certificate with your private key
openssl x509 -in distribution.cer -inform DER -out distribution.pem -outform PEM
openssl pkcs12 -export -inkey ios_distribution.key -in distribution.pem \
  -out ios_distribution.p12 -name "DH FleetView Distribution"
```

It asks for an export password. Choose a strong one and keep it — it becomes
the `IOS_DIST_CERT_PASSWORD` secret.

Verify the key and the request belong together before uploading anything:

```bash
diff <(openssl req -in ios_distribution.csr -noout -pubkey) \
     <(openssl rsa -in ios_distribution.key -pubout) && echo "matched"
```

**Back up `ios_distribution.p12` and its password somewhere safe**, such as a
password manager. Losing it is recoverable (revoke and reissue) but you get
only three distribution certificates, and revoking one invalidates builds
signed with it.

## Step 5 — Create the provisioning profile

<https://developer.apple.com/account/resources/profiles/add>

**App Store Connect** distribution → App ID `com.dhgroup.fleetview` → select the
distribution certificate from step 4 → name it `DH FleetView App Store` →
download the `.mobileprovision`.

## Step 6 — Create an App Store Connect API key

This is what uploads the build. It replaces an Apple ID password and works with
two-factor authentication, which app-specific passwords increasingly do not.

<https://appstoreconnect.apple.com/access/integrations/api> → **Team Keys → +**

- Name: `GitHub Actions`
- Access: **App Manager**

Download the `.p8`. **Apple lets you download it exactly once.** Note the
**Key ID** and, at the top of the page, the **Issuer ID**.

## Step 7 — Add the GitHub secrets

<https://github.com/varaprasad1016/DHFLEETVIEW/settings/secrets/actions>

Base64-encode the two binary files first, on one line:

```bash
base64 -w0 ios_distribution.p12 > p12.txt
base64 -w0 DH_FleetView_App_Store.mobileprovision > profile.txt
```

| Secret | Value |
|---|---|
| `APPLE_TEAM_ID` | `ZAWG6D59DU` |
| `IOS_DIST_CERT_P12` | contents of `p12.txt` |
| `IOS_DIST_CERT_PASSWORD` | the export password from step 4 |
| `IOS_PROVISIONING_PROFILE` | contents of `profile.txt` |
| `APPSTORE_ISSUER_ID` | Issuer ID from step 6 |
| `APPSTORE_KEY_ID` | Key ID from step 6 |
| `APPSTORE_PRIVATE_KEY` | the **whole** `.p8` file, including the `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----` lines |

Then delete the working directory:

```bash
cd .. && rm -rf <that directory>
```

Nothing from steps 4–6 belongs in the repository. The `.gitignore` does not
cover these filenames, so do not create them inside the checkout.

## Step 8 — Run it

**Actions → Build Mobile Apps → Run workflow.**

The iOS job reports which path it took in its log:

- *"Signing secrets present; building a signed .ipa"* — everything is wired up
- *"Signing secrets absent; building unsigned"* — a secret is missing or misspelled

The workflow degrades gracefully on purpose: before the secrets exist it still
produces an unsigned `.ipa` artifact, so it never blocks the rest of the build.

## Build numbers

Every store upload needs a build number higher than the last one accepted, and
`pubspec.yaml` pins `1.0.3+4`. That is right for local builds and wrong for CI:
a second push would re-upload the same number and be rejected by both stores.

The workflow therefore overrides it with `github.run_number + 100`. The offset
clears the numbers already used by hand. Consequences worth knowing:

- **Build numbers are now CI-managed.** Bumping `+4` in `pubspec.yaml` changes
  nothing about what CI uploads. Bump the *version* (`1.0.3`) there when you
  want a new user-visible version; the build number takes care of itself.
- Do not lower `BUILD_NUMBER_OFFSET`, and do not reset the repository's run
  counter. Both stores refuse a build number they have seen before, permanently.

## Renewals

| Expires | What happens | Fix |
|---|---|---|
| Distribution certificate, 1 year | builds fail to sign | repeat steps 4, 5, 7 |
| Provisioning profile, 1 year | builds fail to sign | repeat steps 5, 7 |
| App Store Connect API key | never, unless revoked | — |
| Apple Developer Program, 1 year | apps are **removed from the App Store** | renew before it lapses |

Put a calendar reminder eleven months out. A lapsed membership takes the app
down; an expired certificate only breaks the build.

## Troubleshooting

**"No signing certificate iOS Distribution found"** — `IOS_DIST_CERT_P12` is
missing, was not base64-encoded on one line (`base64 -w0`), or
`IOS_DIST_CERT_PASSWORD` is wrong.

**"Provisioning profile doesn't match the bundle identifier"** — the profile was
created for a different App ID. It must be `com.dhgroup.fleetview` exactly.

**"No profiles for 'com.dhgroup.fleetview' were found"** — the App ID in step 1
was never registered, or the profile in step 5 was not downloaded after it.

**Export fails on `method: app-store-connect`** — that spelling needs Xcode
15.3+. If the runner image is older, change it to `app-store` in the workflow's
*Write export options* step.

**Upload rejected, "redundant binary"** — that build number was already
uploaded. Re-run the workflow; the run number will have advanced.

**Upload succeeds but nothing appears in TestFlight** — Apple is still
processing. Give it 30 minutes. If it never appears, check the email on the
Apple ID: processing failures are reported there, not in App Store Connect.

**First TestFlight build asks for export compliance** — the app uses HTTPS, so
answer that it uses only standard encryption. To stop being asked, add to
`traccar-manager/ios/Runner/Info.plist`:

```xml
<key>ITSAppUsesNonExemptEncryption</key>
<false/>
```

## Also needed before the App Store, not before TestFlight

Apple rejects submissions missing these, so do them before you submit rather
than discovering them in review:

- A privacy policy URL that resolves
- **App Privacy** answers in App Store Connect. The app collects location, which
  must be declared along with whether it is linked to identity
- Screenshots for 6.7" and 5.5" iPhones
- A location-permission justification, since the app requests background
  location. Say plainly that it is a commercial fleet-tracking app for vehicles
  operated by the account holder. Vague answers here are a common rejection
