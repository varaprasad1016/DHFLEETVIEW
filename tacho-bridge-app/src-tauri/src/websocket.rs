//! WebSocket transport to the DHFleetView tachograph-server.
//!
//! This replaces the upstream per-card flespi MQTT transport with a single
//! multiplexed WebSocket that speaks the server's protocol (see the
//! tachograph-server `app/services/tba_bridge.py`):
//!
//! ```text
//! server -> TBA  {"type":"apdu_request","request_id","card_id","apdu":<hex>,"timeout_ms"}
//! TBA -> server  {"type":"apdu_response","request_id","card_id","sw1","sw2","data":<hex>}
//! TBA -> server  {"type":"status","tba_id","cards":[{"card_id","present","busy","atr"}]}
//! server -> TBA  {"type":"session_start","session_id","card_id"}
//! server -> TBA  {"type":"session_end","session_id","card_id"}
//! ```
//!
//! The TBA always dials out to the server (never listens). All PC/SC and card
//! logic in `smart_card.rs` is untouched — this module only moves bytes.

use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tauri::async_runtime;
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{connect_async, MaybeTlsStream, WebSocketStream};

use crate::config::{get_from_cache, CacheSection};
use crate::global_app_handle::app_emit_event;
use crate::smart_card::{find_card, finish_session, set_card_busy, snapshot_cards};

const HEARTBEAT_SECS: u64 = 30;
const RECONNECT_DELAY_INITIAL_SECS: u64 = 5;
const RECONNECT_DELAY_MAX_SECS: u64 = 300;

type Ws = WebSocketStream<MaybeTlsStream<TcpStream>>;

fn next_reconnect_delay(current: u64) -> u64 {
    current.saturating_mul(2).min(RECONNECT_DELAY_MAX_SECS)
}

/// Builds the WebSocket URL from the configured server host.
/// Accepts a bare `host:port` (defaults to `ws://`) or a full `ws://`/`wss://` URL.
fn ws_url() -> Option<String> {
    let host = get_from_cache(CacheSection::Server, "host");
    let host = host.trim();
    if host.is_empty() {
        return None;
    }
    if host.starts_with("ws://") || host.starts_with("wss://") {
        Some(host.to_string())
    } else {
        Some(format!("ws://{}", host))
    }
}

/// Main transport loop: connect, serve, reconnect with exponential backoff.
/// Runs for the lifetime of the app (spawned from `lib.rs`).
pub async fn run() {
    let mut delay = RECONNECT_DELAY_INITIAL_SECS;
    loop {
        let url = match ws_url() {
            Some(u) => u,
            None => {
                log::warn!("[WS] no server address configured yet; will retry");
                tokio::time::sleep(Duration::from_secs(delay)).await;
                delay = next_reconnect_delay(delay);
                continue;
            }
        };

        log::info!("[WS] connecting to {}", url);
        match connect_async(url.as_str()).await {
            Ok((ws, _resp)) => {
                log::info!("[WS] connected");
                delay = RECONNECT_DELAY_INITIAL_SECS;
                app_emit_event(true);
                if let Err(e) = serve(ws).await {
                    log::warn!("[WS] connection ended: {}", e);
                }
                app_emit_event(false);
            }
            Err(e) => {
                log::warn!("[WS] connect failed: {}", e);
                app_emit_event(false);
            }
        }

        tokio::time::sleep(Duration::from_secs(delay)).await;
        delay = next_reconnect_delay(delay);
    }
}

/// Handles one live connection until it closes or errors.
async fn serve(ws: Ws) -> Result<(), String> {
    let (mut write, mut read) = ws.split();

    // All outbound frames funnel through a single writer task.
    let (tx, mut rx) = mpsc::unbounded_channel::<String>();

    let writer = async_runtime::spawn(async move {
        while let Some(text) = rx.recv().await {
            if write.send(Message::Text(text)).await.is_err() {
                break;
            }
        }
    });

    // Periodic card-status heartbeat.
    let hb_tx = tx.clone();
    let heartbeat = async_runtime::spawn(async move {
        loop {
            let payload = build_status_message().await;
            if hb_tx.send(payload).is_err() {
                break;
            }
            tokio::time::sleep(Duration::from_secs(HEARTBEAT_SECS)).await;
        }
    });

    // Read loop.
    let result = loop {
        match read.next().await {
            Some(Ok(Message::Text(text))) => handle_message(&text, &tx).await,
            Some(Ok(Message::Close(_))) => break Ok(()),
            Some(Ok(_)) => {} // ping/pong/binary ignored
            Some(Err(e)) => break Err(e.to_string()),
            None => break Ok(()),
        }
    };

    heartbeat.abort();
    writer.abort();
    result
}

async fn handle_message(text: &str, tx: &mpsc::UnboundedSender<String>) {
    let msg: Value = match serde_json::from_str(text) {
        Ok(v) => v,
        Err(e) => {
            log::warn!("[WS] ignoring non-JSON message: {}", e);
            return;
        }
    };

    match msg.get("type").and_then(|v| v.as_str()) {
        Some("apdu_request") => {
            let request_id = str_field(&msg, "request_id");
            let card_id = str_field(&msg, "card_id");
            let apdu = str_field(&msg, "apdu");
            let tx = tx.clone();
            // Execute concurrently so a slow card cannot stall the read loop.
            async_runtime::spawn(async move {
                let response = execute_apdu(&request_id, &card_id, &apdu).await;
                let _ = tx.send(response);
            });
        }
        Some("session_start") => {
            let card_id = str_field(&msg, "card_id");
            log::info!("[WS] session_start card_id={}", card_id);
            set_card_busy(&card_id, true).await;
        }
        Some("session_end") => {
            let card_id = str_field(&msg, "card_id");
            log::info!("[WS] session_end card_id={}", card_id);
            finish_session(&card_id).await;
        }
        other => log::debug!("[WS] ignoring message type={:?}", other),
    }
}

/// Runs one APDU against the addressed card and formats the response frame.
async fn execute_apdu(request_id: &str, card_id: &str, apdu_hex: &str) -> String {
    let (sw1, sw2, data_hex) = match find_card(card_id).await {
        Some(card) => {
            let rapdu = card.send_apdu(apdu_hex, card_id).await;
            // Passive sniffer: extract plaintext EF data from SM'd responses.
            crate::apdu_sniffer::sniff(card_id, apdu_hex, &rapdu);
            parse_rapdu(&rapdu)
        }
        None => {
            log::warn!("[WS] apdu_request for unknown card_id={}", card_id);
            (0x6Au8, 0x82u8, String::new()) // 6A82: card/file not found
        }
    };

    json!({
        "type": "apdu_response",
        "request_id": request_id,
        "card_id": card_id,
        "sw1": sw1,
        "sw2": sw2,
        "data": data_hex,
    })
    .to_string()
}

/// Splits a response APDU (`data || SW1 || SW2`, hex) into (sw1, sw2, data-hex).
fn parse_rapdu(rapdu_hex: &str) -> (u8, u8, String) {
    match hex::decode(rapdu_hex.trim()) {
        Ok(bytes) if bytes.len() >= 2 => {
            let n = bytes.len();
            (bytes[n - 2], bytes[n - 1], hex::encode(&bytes[..n - 2]))
        }
        _ => (0x6F, 0x00, String::new()), // 6F00: technical problem
    }
}

async fn build_status_message() -> String {
    let tba_id = get_from_cache(CacheSection::Ident, "ident");
    let cards: Vec<Value> = snapshot_cards()
        .await
        .into_iter()
        .map(|(card_id, present, busy, atr)| {
            json!({ "card_id": card_id, "present": present, "busy": busy, "atr": atr })
        })
        .collect();
    json!({ "type": "status", "tba_id": tba_id, "cards": cards }).to_string()
}

fn str_field(msg: &Value, key: &str) -> String {
    msg.get(key).and_then(|v| v.as_str()).unwrap_or("").to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_rapdu_splits_sw_and_data() {
        assert_eq!(parse_rapdu("9000"), (0x90, 0x00, "".to_string()));
        assert_eq!(parse_rapdu("DEADBEEF9000"), (0x90, 0x00, "deadbeef".to_string()));
    }

    #[test]
    fn parse_rapdu_handles_short_or_bad_input() {
        assert_eq!(parse_rapdu(""), (0x6F, 0x00, "".to_string()));
        assert_eq!(parse_rapdu("zz"), (0x6F, 0x00, "".to_string()));
    }

    #[test]
    fn next_reconnect_delay_caps() {
        assert_eq!(next_reconnect_delay(5), 10);
        assert_eq!(next_reconnect_delay(200), RECONNECT_DELAY_MAX_SECS);
        assert_eq!(next_reconnect_delay(u64::MAX), RECONNECT_DELAY_MAX_SECS);
    }
}
