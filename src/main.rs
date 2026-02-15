mod agents;
mod config;
mod db;
mod pdf;
mod routes;
mod state;
mod storage;
mod templates;

use axum::{
    routing::{get, post},
    Router,
};
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "cuadrada=info,tower_http=info".into()),
        )
        .init();

    let config = config::Config::from_env()?;
    let config = Arc::new(config);

    crate::storage::ensure_dirs(&config.upload_folder, &config.results_folder)?;

    let pool = db::create_pool(&config.database_url).await?;
    db::run_migrations(pool.as_ref()).await?;

    let state = Arc::new(state::AppState {
        pool,
        config: config.clone(),
    });

    let app = Router::new()
        .route("/", get(routes::index))
        .route("/upload", post(routes::upload_handler))
        .route("/results/:submission_id", get(routes::view_results))
        .route("/api/status/:submission_id", get(routes::check_status))
        .route("/download/:filename", get(routes::download_file))
        .route("/download_certificate/:submission_id", get(routes::download_certificate))
        .route("/download_all/:submission_id", get(routes::download_all))
        .route("/retry_review/:submission_id/:reviewer_name", post(routes::retry_review))
        .nest_service("/static", tower_http::services::ServeDir::new("static"))
        .layer(TraceLayer::new_for_http())
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = format!("{}:{}", config.host, config.port);
    tracing::info!("Cuadrada listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
