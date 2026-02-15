mod models;

pub use models::*;

use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;

pub type DbPool = Arc<PgPool>;

pub async fn create_pool(database_url: &str) -> Result<DbPool, sqlx::Error> {
    let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect(database_url)
        .await?;

    Ok(Arc::new(pool))
}

pub async fn run_migrations(pool: &PgPool) -> Result<(), sqlx::Error> {
    sqlx::migrate!("./migrations").run(pool).await
}

pub async fn create_submission(
    pool: &PgPool,
    submission_id: &str,
    paper_title: &str,
    filename: &str,
    file_path: &str,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO submissions (submission_id, paper_title, filename, file_path, processing_complete, all_accepted)
        VALUES ($1, $2, $3, $4, false, false)
        "#,
    )
    .bind(submission_id)
    .bind(paper_title)
    .bind(filename)
    .bind(file_path)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn get_submission(
    pool: &PgPool,
    submission_id: &str,
) -> Result<Option<Submission>, sqlx::Error> {
    sqlx::query_as::<_, Submission>(
        "SELECT * FROM submissions WHERE submission_id = $1",
    )
    .bind(submission_id)
    .fetch_optional(pool)
    .await
}

pub async fn get_review_results(
    pool: &PgPool,
    submission_id: &str,
) -> Result<std::collections::HashMap<String, serde_json::Value>, sqlx::Error> {
    let rows = sqlx::query_as::<_, ReviewResult>(
        "SELECT * FROM review_results WHERE submission_id = $1 ORDER BY reviewer_name",
    )
    .bind(submission_id)
    .fetch_all(pool)
    .await?;

    let mut map = std::collections::HashMap::new();
    for r in rows {
        // Note: filename omitted - per-review PDFs not generated; full review shown in page
        let value = serde_json::json!({
            "decision": r.decision,
            "summary": r.summary.unwrap_or_default(),
            "full_review": r.full_review.unwrap_or_default(),
            "model_used": r.model_used,
            "model_downgraded": false
        });
        map.insert(r.reviewer_name, value);
    }
    Ok(map)
}
