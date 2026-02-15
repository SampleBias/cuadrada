use axum::{
    extract::{Path, State},
    response::{Html, IntoResponse, Redirect},
    Form,
};
use serde::Deserialize;
use std::sync::Arc;
use tera::{Context, Tera};

use crate::db::{create_submission, get_review_results, get_submission};
use crate::state::AppState;
use crate::storage::generate_submission_id;

pub async fn index(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    let mut ctx = Context::new();
    render_template(&state, "index.html", ctx).await
}

#[derive(Deserialize)]
pub struct UploadForm {
    paper_title: Option<String>,
}

pub async fn upload_handler(
    State(state): State<Arc<AppState>>,
    mut multipart: axum::extract::Multipart,
) -> impl IntoResponse {
    let mut paper_title = String::new();
    let mut paper_data: Option<Vec<u8>> = None;
    let mut filename = String::new();

    while let Ok(Some(field)) = multipart.next_field().await {
        let name = field.name().unwrap_or("").to_string();
        if name == "paper_title" {
            if let Ok(text) = field.text().await {
                paper_title = text;
            }
        } else if name == "paper" {
            if let Ok(data) = field.bytes().await {
                paper_data = Some(data.to_vec());
            }
            filename = field.file_name().unwrap_or("paper.pdf").to_string();
        }
    }

    let paper_data = match paper_data {
        Some(d) if !d.is_empty() => d,
        _ => return Redirect::to("/").into_response(),
    };

    if !filename.to_lowercase().ends_with(".pdf") {
        return Redirect::to("/").into_response();
    }

    let submission_id = generate_submission_id();
    let upload_path = state
        .config
        .upload_folder
        .join(format!("{}_{}", submission_id, filename));

    if std::fs::write(&upload_path, &paper_data).is_err() {
        return Redirect::to("/").into_response();
    }

    let title = if paper_title.trim().is_empty() {
        filename.replace(".pdf", "")
    } else {
        paper_title.trim().to_string()
    };

    if let Err(e) = create_submission(
        state.pool.as_ref(),
        &submission_id,
        &title,
        &filename,
        upload_path.to_str().unwrap_or(""),
    )
    .await
    {
        tracing::error!("Failed to create submission: {}", e);
        return Redirect::to("/").into_response();
    }

    // Spawn background review processing
    let pool = state.pool.clone();
    let config = state.config.clone();
    let sub_id = submission_id.clone();
    let path = upload_path.clone();
    tokio::spawn(async move {
        if let Err(e) = process_reviews_background(pool, config, sub_id, path, title, filename).await
        {
            tracing::error!("Background review failed: {}", e);
        }
    });

    Redirect::to(&format!("/results/{}", submission_id)).into_response()
}

async fn process_reviews_background(
    pool: crate::db::DbPool,
    config: Arc<crate::config::Config>,
    submission_id: String,
    upload_path: std::path::PathBuf,
    paper_title: String,
    filename: String,
) -> Result<(), String> {
    let reviewers = ["Reviewer 1", "Reviewer 2", "Reviewer 3"];
    let path_str = upload_path.to_str().ok_or("Invalid path")?;

    let mut all_accepted = true;

    for reviewer_name in reviewers {
        let mut agent = crate::agents::ClaudeAgent::new(config.claude_api_key.clone());

        match agent.analyze_paper(path_str).await {
            Ok(review_text) => {
                let decision = crate::agents::determine_decision(&review_text);
                let decision_str = &decision.decision;
                if decision_str != "ACCEPTED" {
                    all_accepted = false;
                }

                let summary = decision.summary.clone();
                let full_review = decision.full_review.clone();

                let _ = sqlx::query(
                    r#"
                    INSERT INTO review_results (submission_id, reviewer_name, decision, summary, full_review, model_used)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    "#,
                )
                .bind(&submission_id)
                .bind(reviewer_name)
                .bind(decision_str)
                .bind(&summary)
                .bind(&full_review)
                .bind(agent.current_model())
                .execute(pool.as_ref())
                .await;
            }
            Err(e) => {
                all_accepted = false;
                let _ = sqlx::query(
                    r#"
                    INSERT INTO review_results (submission_id, reviewer_name, decision, summary, full_review)
                    VALUES ($1, $2, 'ERROR', $3, $4)
                    "#,
                )
                .bind(&submission_id)
                .bind(reviewer_name)
                .bind(&e)
                .bind(&e)
                .execute(pool.as_ref())
                .await;
            }
        }
    }

    let certificate_filename = if all_accepted {
        let cert_name = format!("{}_certificate.pdf", submission_id);
        let cert_path = config.results_folder.join(&cert_name);
        if crate::pdf::generate_certificate(&paper_title, &cert_path).is_ok() {
            Some(cert_name)
        } else {
            None
        }
    } else {
        None
    };

    sqlx::query(
        r#"
        UPDATE submissions 
        SET processing_complete = true, all_accepted = $2, certificate_filename = $3
        WHERE submission_id = $1
        "#,
    )
    .bind(&submission_id)
    .bind(all_accepted)
    .bind(&certificate_filename)
    .execute(pool.as_ref())
    .await
    .map_err(|e| e.to_string())?;

    Ok(())
}

pub async fn view_results(
    State(state): State<Arc<AppState>>,
    Path(submission_id): Path<String>,
) -> impl IntoResponse {
    let submission = match get_submission(state.pool.as_ref(), &submission_id).await {
        Ok(Some(s)) => s,
        _ => return Redirect::to("/").into_response(),
    };

    let results = match get_review_results(state.pool.as_ref(), &submission_id).await {
        Ok(r) => r,
        Err(_) => return Redirect::to("/").into_response(),
    };

    let mut ctx = Context::new();
    ctx.insert("submission_id", &submission_id);
    ctx.insert("results", &results);
    ctx.insert("all_accepted", &submission.all_accepted);
    ctx.insert("has_accepted", &submission.all_accepted);
    ctx.insert(
        "certificate_filename",
        &submission.certificate_filename.unwrap_or_default(),
    );
    ctx.insert("processing", &!submission.processing_complete);

    render_template(&state, "results.html", ctx).await
}

pub async fn check_status(
    State(state): State<Arc<AppState>>,
    Path(submission_id): Path<String>,
) -> impl IntoResponse {
    let submission = match get_submission(state.pool.as_ref(), &submission_id).await {
        Ok(Some(s)) => s,
        Ok(None) => {
            return axum::Json(serde_json::json!({
                "status": "not_found",
                "message": "Review not found."
            }))
            .into_response()
        }
        Err(_) => {
            return axum::Json(serde_json::json!({
                "status": "error",
                "message": "Database error."
            }))
            .into_response()
        }
    };

    if !submission.processing_complete {
        return axum::Json(serde_json::json!({
            "status": "processing",
            "message": "Review is still being processed."
        }))
        .into_response();
    }

    let results = match get_review_results(state.pool.as_ref(), &submission_id).await {
        Ok(r) => r,
        Err(_) => {
            return axum::Json(serde_json::json!({
                "status": "error",
                "message": "Failed to load results."
            }))
            .into_response()
        }
    };

    axum::Json(serde_json::json!({
        "status": "complete",
        "results": results,
        "all_accepted": submission.all_accepted,
        "certificate_filename": submission.certificate_filename
    }))
    .into_response()
}

pub async fn retry_review(
    State(state): State<Arc<AppState>>,
    Path((submission_id, reviewer_name)): Path<(String, String)>,
) -> impl IntoResponse {
    axum::Json(serde_json::json!({
        "success": false,
        "error": "Retry not yet implemented in Rust version"
    }))
}

async fn render_template(state: &AppState, name: &str, ctx: Context) -> Html<String> {
    let tera = crate::templates::get_tera();
    let rendered = tera
        .render(name, &ctx)
        .unwrap_or_else(|_| format!("Template error: {}", name));
    Html(rendered)
}
