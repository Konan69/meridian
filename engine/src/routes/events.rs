use axum::{
    extract::State,
    response::sse::{Event, Sse},
};
use std::sync::Arc;
use std::time::Duration;
use tokio_stream::StreamExt;

use crate::AppState;

/// GET /events — SSE stream of protocol metrics, updated every second
pub async fn event_stream(
    State(state): State<Arc<AppState>>,
) -> Sse<impl tokio_stream::Stream<Item = Result<Event, std::convert::Infallible>>> {
    let stream = tokio_stream::wrappers::IntervalStream::new(tokio::time::interval(Duration::from_secs(1)))
        .map(move |_| {
            let metrics: Vec<_> = state
                .protocols
                .iter()
                .map(|(_, adapter)| adapter.metrics())
                .collect();

            let sessions_count = state.sessions.lock().unwrap().len();

            let data = serde_json::json!({
                "type": "metrics_update",
                "protocols": metrics,
                "active_sessions": sessions_count,
                "timestamp": chrono::Utc::now().to_rfc3339(),
            });

            Ok(Event::default().data(data.to_string()))
        });

    Sse::new(stream).keep_alive(
        axum::response::sse::KeepAlive::new()
            .interval(Duration::from_secs(15))
            .text("ping"),
    )
}
