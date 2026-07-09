use gremlinboard_widget_kit::{serve_stdio, RpcResult, WidgetService};
use serde_json::{json, Value};
use std::time::Instant;

struct TemplateWidget {
    started_at: Instant,
    started: bool,
    config: Value,
    refresh_count: u64,
}

impl TemplateWidget {
    fn new() -> Self {
        Self {
            started_at: Instant::now(),
            started: false,
            config: json!({}),
            refresh_count: 0,
        }
    }

    fn state(&self) -> Value {
        // Keep the shape stable. Blueprint bindings and generated renderers
        // depend on these paths staying predictable across refreshes.
        json!({
            "status": if self.started { "running" } else { "created" },
            "started": self.started,
            "uptime_seconds": self.started_at.elapsed().as_secs(),
            "refresh_count": self.refresh_count,
            "config": self.config.clone()
        })
    }
}

impl WidgetService for TemplateWidget {
    fn start(&mut self, config: Value) -> RpcResult {
        // The runtime sends the instance config on start. Store only what the
        // widget needs; stdout must stay reserved for JSON-RPC responses.
        self.started = true;
        self.config = config;
        Ok(self.state())
    }

    fn stop(&mut self) -> RpcResult {
        // The protocol loop writes this response, flushes stdout, then exits.
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
            "message": if self.started { "running" } else { "not started" }
        }))
    }

    fn get_state(&mut self) -> RpcResult {
        Ok(self.state())
    }

    fn refresh(&mut self, force: bool) -> RpcResult {
        // Use force for bypassing local caches when the widget has any.
        // This template has no cache, so it records the request and returns.
        if force {
            eprintln!("template widget received forced refresh");
        }
        self.refresh_count += 1;
        Ok(self.state())
    }

    fn set_config(&mut self, config: Value) -> RpcResult {
        self.config = config;
        Ok(json!({
            "configured": true
        }))
    }
}

fn main() {
    let mut service = TemplateWidget::new();
    if let Err(error) = serve_stdio(&mut service) {
        eprintln!("gremlinboard rust widget protocol error: {error}");
    }
}