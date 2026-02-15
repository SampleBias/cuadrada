use axum::{
    extract::{Path, State},
    response::IntoResponse,
};
use std::io::Write;
use std::sync::Arc;

use crate::state::AppState;

pub async fn download_file(
    State(state): State<Arc<AppState>>,
    Path(filename): Path<String>,
) -> impl IntoResponse {
    if filename.contains("..") || filename.is_empty() {
        return axum::response::Redirect::to("/").into_response();
    }

    let results_path = state.config.results_folder.join(&filename);
    if results_path.exists() {
        match std::fs::read(&results_path) {
            Ok(content) => {
                let mime = mime_guess::from_path(&filename)
                    .first_raw()
                    .unwrap_or("application/octet-stream");
                return axum::response::Response::builder()
                    .header("Content-Type", mime)
                    .header(
                        "Content-Disposition",
                        format!("attachment; filename=\"{}\"", filename),
                    )
                    .body(axum::body::Body::from(content))
                    .unwrap()
                    .into_response();
            }
            Err(_) => {}
        }
    }

    axum::response::Redirect::to("/").into_response()
}

pub async fn download_certificate(
    State(state): State<Arc<AppState>>,
    Path(submission_id): Path<String>,
) -> impl IntoResponse {
    let submission = match crate::db::get_submission(state.pool.as_ref(), &submission_id).await {
        Ok(Some(s)) => s,
        _ => return axum::response::Redirect::to("/").into_response(),
    };

    let cert_filename = match submission.certificate_filename {
        Some(f) => f,
        None => return axum::response::Redirect::to("/").into_response(),
    };

    let cert_path = state.config.results_folder.join(&cert_filename);
    if !cert_path.exists() {
        return axum::response::Redirect::to("/").into_response();
    }

    let content = match std::fs::read(&cert_path) {
        Ok(c) => c,
        Err(_) => return axum::response::Redirect::to("/").into_response(),
    };

    let paper_title = submission
        .paper_title
        .unwrap_or_else(|| "Research_Paper".to_string());
    let download_name = format!("{}_Certificate.pdf", paper_title.replace(' ', "_"));

    axum::response::Response::builder()
        .header("Content-Type", "application/pdf")
        .header(
            "Content-Disposition",
            format!("attachment; filename=\"{}\"", download_name),
        )
        .body(axum::body::Body::from(content))
        .unwrap()
        .into_response()
}

pub async fn download_all(
    State(state): State<Arc<AppState>>,
    Path(submission_id): Path<String>,
) -> impl IntoResponse {
    let submission = match crate::db::get_submission(state.pool.as_ref(), &submission_id).await {
        Ok(Some(s)) => s,
        _ => return axum::response::Redirect::to("/").into_response(),
    };

    let mut zip_data = Vec::new();
    {
        let mut zip = zip::ZipWriter::new(std::io::Cursor::new(&mut zip_data));
        let options = zip::write::FileOptions::default().unix_permissions(0o644);

        if let Some(ref cert_filename) = submission.certificate_filename {
            let cert_path = state.config.results_folder.join(cert_filename);
            if cert_path.exists() {
                if let Ok(content) = std::fs::read(&cert_path) {
                    let _ = zip.start_file(cert_filename, options);
                    let _ = zip.write_all(&content);
                }
            }
        }

        let _ = zip.finish();
    }

    let download_name = format!(
        "{}_All_Reviews.zip",
        submission
            .paper_title
            .unwrap_or_else(|| "Research_Paper".to_string())
            .replace(' ', "_")
    );

    axum::response::Response::builder()
        .header("Content-Type", "application/zip")
        .header(
            "Content-Disposition",
            format!("attachment; filename=\"{}\"", download_name),
        )
        .body(axum::body::Body::from(zip_data))
        .unwrap()
        .into_response()
}
