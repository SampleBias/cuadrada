use std::path::PathBuf;
use uuid::Uuid;
use chrono::Utc;

pub fn generate_submission_id() -> String {
    format!(
        "{}_{}",
        Utc::now().format("%Y%m%d"),
        Uuid::new_v4().to_string()[..8].to_string()
    )
}

pub fn ensure_dirs(upload_folder: &PathBuf, results_folder: &PathBuf) -> std::io::Result<()> {
    std::fs::create_dir_all(upload_folder)?;
    std::fs::create_dir_all(results_folder)?;
    Ok(())
}
