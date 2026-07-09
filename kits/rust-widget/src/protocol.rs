use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

pub type RpcResult = Result<Value, RpcError>;

#[derive(Debug, Clone)]
pub struct RpcError {
    pub code: i64,
    pub message: String,
    pub data: Option<Value>,
}

impl RpcError {
    pub fn new(code: i64, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            data: None,
        }
    }

    pub fn with_data(code: i64, message: impl Into<String>, data: Value) -> Self {
        Self {
            code,
            message: message.into(),
            data: Some(data),
        }
    }

    pub fn invalid_params(message: impl Into<String>) -> Self {
        Self::new(-32602, message)
    }

    fn method_not_found(method: &str) -> Self {
        Self::with_data(
            -32601,
            "method not found",
            json!({
                "method": method
            }),
        )
    }
}

pub trait WidgetService {
    fn start(&mut self, config: Value) -> RpcResult;
    fn stop(&mut self) -> RpcResult;
    fn health(&mut self) -> RpcResult;
    fn get_state(&mut self) -> RpcResult;
    fn refresh(&mut self, force: bool) -> RpcResult;
    fn set_config(&mut self, config: Value) -> RpcResult;
}

pub fn serve_stdio<S: WidgetService>(service: &mut S) -> io::Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    serve(stdin.lock(), &mut stdout, service)
}

pub fn serve<R, W, S>(reader: R, writer: &mut W, service: &mut S) -> io::Result<()>
where
    R: BufRead,
    W: Write,
    S: WidgetService,
{
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }

        let mut should_exit = false;
        let response = match serde_json::from_str::<Value>(&line) {
            Ok(request) => dispatch_request(service, request, &mut should_exit),
            Err(error) => jsonrpc_error(Value::Null, -32700, "parse error", Some(json!({
                "message": error.to_string()
            }))),
        };

        serde_json::to_writer(&mut *writer, &response)?;
        writer.write_all(b"\n")?;
        writer.flush()?;

        if should_exit {
            break;
        }
    }

    Ok(())
}

fn dispatch_request<S: WidgetService>(service: &mut S, request: Value, should_exit: &mut bool) -> Value {
    let request_id = request.get("id").cloned().unwrap_or(Value::Null);

    if request.get("jsonrpc") != Some(&Value::String("2.0".to_string())) {
        return jsonrpc_error(request_id, -32600, "invalid request", None);
    }

    let method = match request.get("method").and_then(Value::as_str) {
        Some(method) => method,
        None => return jsonrpc_error(request_id, -32600, "invalid request", None),
    };

    let params = request.get("params").cloned().unwrap_or_else(|| json!({}));
    let result = match method {
        "start" => service.start(params.get("config").cloned().unwrap_or(Value::Null)),
        "stop" => {
            let result = service.stop();
            *should_exit = result.is_ok();
            result
        }
        "health" => service.health(),
        "get_state" => service.get_state(),
        "refresh" => service.refresh(params.get("force").and_then(Value::as_bool).unwrap_or(false)),
        "set_config" => service.set_config(params.get("config").cloned().unwrap_or(Value::Null)),
        unknown => Err(RpcError::method_not_found(unknown)),
    };

    match result {
        Ok(value) => json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": value
        }),
        Err(error) => jsonrpc_error(request_id, error.code, &error.message, error.data),
    }
}

fn jsonrpc_error(id: Value, code: i64, message: &str, data: Option<Value>) -> Value {
    let mut error = json!({
        "code": code,
        "message": message
    });

    if let Some(data) = data {
        if let Some(error_object) = error.as_object_mut() {
            error_object.insert("data".to_string(), data);
        }
    }

    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": error
    })
}