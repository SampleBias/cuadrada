use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

#[derive(Debug, FromRow, Serialize, Deserialize)]
pub struct Submission {
    pub id: i32,
    pub submission_id: String,
    pub paper_title: Option<String>,
    pub filename: Option<String>,
    pub file_path: String,
    pub created_at: DateTime<Utc>,
    pub processing_complete: bool,
    pub all_accepted: bool,
    pub error: Option<String>,
    pub certificate_filename: Option<String>,
}

#[derive(Debug, FromRow, Serialize, Deserialize)]
pub struct ReviewResult {
    pub id: i32,
    pub submission_id: String,
    pub reviewer_name: String,
    pub decision: String,
    pub summary: Option<String>,
    pub full_review: Option<String>,
    pub model_used: Option<String>,
    pub file_url: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReviewResultDisplay {
    pub decision: String,
    pub summary: String,
    pub full_review: String,
    pub model_used: Option<String>,
    pub model_downgraded: bool,
}
