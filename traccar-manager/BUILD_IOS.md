# Building the iOS App (${title})

The iOS project in `ios/` is fully branded and ready to build — but iOS builds **require a Mac with Xcode**. This project is the same Flutter app as the Android version: a WebView that loads the ${title} web app.

## What's already done

- App name **${title}** (`Info.plist` → `CFBundleDisplayName` / `CFBundleName`)
- Bundle ID **`com.dhgroup.fleetview`**
- App icons regenerated to match Android: indigo→violet gradient with the white pin badge (all sizes)
- App Transport Security allows cleartext HTTP (`NSAllowsArbitraryLoads`) so the app can load your `http://` server
- Camera / Face ID / Location usage descriptions present
- First-run default server URL is `http://localhost:8082` on iOS (simulator reaches the host Mac directly)

## Prerequisites on the Mac

1. **macOS** (current stable) + **Xcode** (latest, from the App Store) — open Xcode once to accept the license
2. **Flutter SDK** (same version as this project: `3.47.x` stable) — `brew install --cask flutter` or from flutter.dev
3. **CocoaPods** — `sudo gem install cocoapods`
4. An **Apple Developer account** ($99/yr) to install on a real device or publish

## Steps

```bash
# 1. Get the code
git clone https://github.com/varaprasad1016/DHFLEETVIEW.git
cd DHFLEETVIEW/traccar-manager

# 2. Get dependencies
flutter pub get

# 3. Run on the iOS Simulator (no signing needed)
open -a Simulator
flutter run -d ios

# 4. Or build the archive for App Store / TestFlight / ad-hoc
flutter build ipa --release
```

The unsigned/adhoc build lands in `build/ios/archive/`.

## Signing & distribution

1. In Xcode, open `ios/Runner.xcworkspace`
2. Select the **Runner** target → **Signing & Capabilities**
3. Choose your **Team** (your Apple Developer account) — Xcode will create the provisioning profile for bundle ID `com.dhgroup.fleetview`
4. `flutter build ipa --release` produces the archive; upload via **Xcode → Organizer → Distribute App** (App Store / TestFlight) or export an ad-hoc `.ipa` for direct installs

## Notes

- **Real device:** the app loads the server URL from the first-run screen. Use your server's LAN/public IP (e.g. `http://192.168.x.x:8082`) — `localhost` only works on the simulator.
- **Push notifications / Firebase were removed** — no `GoogleService-Info.plist` is needed.
- Deployment target is iOS 13+ (podfile default); adjust in Xcode if you need older.
