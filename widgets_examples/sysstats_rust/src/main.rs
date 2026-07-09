use gremlinboard_widget_kit::{serve_stdio, RpcResult, WidgetService};
use serde_json::{json, Value};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

struct SysstatsRust {
    started_at: Instant,
    started: bool,
    config: Value,
    ticks: u64,
    last_refresh_unix: u64,
}

impl SysstatsRust {
    fn new() -> Self {
        Self {
            started_at: Instant::now(),
            started: false,
            config: json!({}),
            ticks: 0,
            last_refresh_unix: now_unix_seconds(),
        }
    }

    fn label(&self) -> String {
        self.config
            .get("label")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or("Rust process")
            .to_string()
    }

    fn note(&self) -> String {
        self.config
            .get("note")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or("std-only process telemetry")
            .to_string()
    }

    fn state(&self) -> Value {
        let uptime_seconds = self.started_at.elapsed().as_secs();
        let started_unix = self.last_refresh_unix.saturating_sub(uptime_seconds);
        json!({
            "status": if self.started { "running" } else { "created" },
            "status_label": if self.started { "running" } else { "created" },
            "label": self.label(),
            "note": self.note(),
            "uptime_seconds": uptime_seconds,
            "ticks": self.ticks,
            "current_unix": now_unix_seconds(),
            "started_unix": started_unix,
            "last_refresh_unix": self.last_refresh_unix,
            "details": {
                "process": "sysstats_rust",
                "source": "std",
                "config_label": self.label()
            }
        })
    }
}

impl WidgetService for SysstatsRust {
    fn start(&mut self, config: Value) -> RpcResult {
        self.started = true;
        self.config = config;
        self.last_refresh_unix = now_unix_seconds();
        Ok(self.state())
    }

    fn stop(&mut self) -> RpcResult {
        self.started = false;
        Ok(json!({
            "stopped": true
        }))
    }

    fn health(&mut self) -> RpcResult {
        Ok(json!({
            "status": if self.started { "running" } else { "created" },
            "healthy": self.started,
            "expired": false,
            "message": if self.started { "process telemetry active" } else { "not started" }
        }))
    }

    fn get_state(&mut self) -> RpcResult {
        Ok(self.state())
    }

    fn refresh(&mut self, force: bool) -> RpcResult {
        if force {
            eprintln!("sysstats_rust forced refresh");
        }
        self.ticks += 1;
        self.last_refresh_unix = now_unix_seconds();
        Ok(self.state())
    }

    fn set_config(&mut self, config: Value) -> RpcResult {
        self.config = config;
        Ok(json!({
            "configured": true
        }))
    }
}

fn now_unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0)
}

fn main() {
    let mut service = SysstatsRust::new();
    if let Err(error) = serve_stdio(&mut service) {
        eprintln!("sysstats_rust protocol error: {error}");
    }
}