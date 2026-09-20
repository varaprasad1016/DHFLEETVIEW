"""DH FleetView overlay on the upstream Tacho Bridge App (run after every upstream sync).

    python tacho-bridge-app/scripts/apply-overlay.py tacho-bridge-app <version> "<updater public key>"

<version> is upstream's version plus a DH FleetView suffix, e.g. 0.8.0-rc.16-dh.1.
The public key is D:\DHFleetViewData\tacho\bridge\signing\updater.key.pub on the server
(its private half signs the installers; never commit it).

Keeps upstream's code and wire protocol intact (PC/SC cards, Lisle card rack,
per-card sessions) and changes only what ties the app to flespi: server address,
TLS, update source, bundle identity and wording.
"""
import json
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "D:/tools/wt-tba/tacho-bridge-app"
VERSION = sys.argv[2] if len(sys.argv) > 2 else "0.8.0-rc.16-dh.1"
PUBKEY = sys.argv[3] if len(sys.argv) > 3 else None
DEFAULT_HOST = "dhfleetview.co.uk:443"


def patch(rel, pairs, count=1):
    p = f"{ROOT}/{rel}"
    raw = open(p, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    s = raw.replace("\r\n", "\n")
    for a, b in pairs:
        if isinstance(a, re.Pattern):
            s, n = a.subn(b, s)
            assert n >= 1, (rel, a.pattern)
            continue
        assert s.count(a) >= 1, (rel, a[:90])
        s = s.replace(a, b)
    open(p, "w", encoding="utf-8", newline="").write(s.replace("\n", nl))


# ---- tauri.conf.json -------------------------------------------------------
p = f"{ROOT}/src-tauri/tauri.conf.json"
conf = json.load(open(p, encoding="utf-8"))
conf["productName"] = "DH FleetView Tacho Bridge"
conf["version"] = VERSION
conf["identifier"] = "com.dhfleetview.tachobridge"
conf["app"]["windows"][0]["title"] = "DH FleetView Tacho Bridge"
conf["plugins"]["updater"]["endpoints"] = ["https://dhfleetview.co.uk/tacho/bridge/latest.json"]
if PUBKEY:
    conf["plugins"]["updater"]["pubkey"] = PUBKEY
conf["bundle"]["targets"] = ["nsis"]
conf["bundle"]["publisher"] = "DH FleetView"
json.dump(conf, open(p, "w", encoding="utf-8", newline="\n"), indent=2)
open(p, "a", encoding="utf-8", newline="\n").write("\n")

# ---- package.json ------------------------------------------------------------
p = f"{ROOT}/package.json"
pkg = json.load(open(p, encoding="utf-8"))
pkg["version"] = VERSION
pkg["productName"] = "DH FleetView Tacho Bridge"
pkg["author"] = "DH FleetView"
json.dump(pkg, open(p, "w", encoding="utf-8", newline="\n"), indent=2)
open(p, "a", encoding="utf-8", newline="\n").write("\n")

# ---- Cargo.toml: version, repo, TLS for the MQTT client -------------------------
patch("src-tauri/Cargo.toml", [
    (re.compile(r'(?m)^version = "[^"]+"'), f'version = "{VERSION}"'),
    ('repository = "https://git.gurtam.net/shev/flespi_tca"', 'repository = "https://github.com/varaprasad1016/DHFLEETVIEW"'),
    ('authors = ["Shatilo Evgeny"]', 'authors = ["Shatilo Evgeny", "DH FleetView"]'),
    ('rumqttc = "0.25.1"', 'rumqttc = { version = "0.25.1", features = ["use-native-tls", "websocket"] }'),
])

# ---- MQTT client: HTTPS (websocket) by default, plain TLS on the secure port ----------
patch("src-tauri/src/mqtt.rs", [
    ('''    let mut mqtt_options = MqttOptions::new(client_id.into(), host, port);
    apply_mqtt_credentials(&mut mqtt_options);''', '''    // DH FleetView: both encrypted routes check the certificate against the
    // Windows trust store, so the sign-in and card traffic are never in clear.
    let mut mqtt_options = if port == MQTT_WSS_PORT {
        let url = format!("wss://{}{}", host, WSS_PATH);
        let mut options = MqttOptions::new(client_id.into(), url, port);
        options.set_transport(rumqttc::Transport::Wss(rumqttc::TlsConfiguration::default()));
        options
    } else {
        let mut options = MqttOptions::new(client_id.into(), host, port);
        if port == MQTT_TLS_PORT {
            options.set_transport(rumqttc::Transport::tls_with_config(
                rumqttc::TlsConfiguration::Native,
            ));
        }
        options
    };
    apply_mqtt_credentials(&mut mqtt_options);'''),
    ('''pub(crate) fn build_mqtt_client(''', '''/// DH FleetView: connections to this port are made over TLS.
pub(crate) const MQTT_TLS_PORT: u16 = 8883;

/// DH FleetView: the HTTPS port carries MQTT over a WebSocket. Hosting and depot
/// firewalls routinely allow nothing but 80 and 443, so this is the default: it
/// reaches the server from anywhere a browser can.
pub(crate) const MQTT_WSS_PORT: u16 = 443;
const WSS_PATH: &str = "/tacho/bridge/ws";

pub(crate) fn build_mqtt_client('''),
    ("the flespi broker allows one session per", "the server allows one session per"),
])

# ---- config: default server address + wording ------------------------------------
patch("src-tauri/src/config.rs", [
    ('''        ident: Some(generate_ident()),
        server: None,''', f'''        ident: Some(generate_ident()),
        // DH FleetView: new installs connect to our server out of the box.
        server: Some(ServerConfig {{
            host: DEFAULT_SERVER_HOST.to_string(),
            auth_enabled: None,
            username: None,
            password: None,
        }}),'''),
    ('''fn generate_default_config() -> ConfigurationFile {''', f'''/// DH FleetView server the app connects to by default (TLS).
pub const DEFAULT_SERVER_HOST: &str = "{DEFAULT_HOST}";

fn generate_default_config() -> ConfigurationFile {{'''),
    ("(flespi channels accept a token as the username,\n    /// password usually empty)", "(the DH FleetView bridge sign-in from the\n    /// Tachograph page)"),
    ("flespi identity", "server identity"),
    ('"FlespiToken"', '"BridgeUser"'),
    ("mqtt.flespi.io", "mqtt.example.com"),
])
patch("src-tauri/src/apdu_sniffer.rs", [("flespi", "the server")])
patch("src-tauri/src/updater.rs", [
    ('"https://github.com/flespi-software/Tacho-Bridge-App/releases/download/updater-beta/latest.json"',
     '"https://dhfleetview.co.uk/tacho/bridge/latest-beta.json"'),
])

# ---- UI wording ------------------------------------------------------------------
patch("src/components/ServerConfigDialog.vue", [
    ("(a flespi token\n            goes into the username)", "(the bridge sign-in\n            shown on the DH FleetView Tachograph page)"),
])
print("overlay ok", VERSION)
