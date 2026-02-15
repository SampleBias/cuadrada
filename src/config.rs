use std::path::PathBuf;

#[derive(Clone)]
pub struct Config {
    pub database_url: String,
    pub claude_api_key: String,
    pub upload_folder: PathBuf,
    pub results_folder: PathBuf,
    pub host: String,
    pub port: u16,
}

impl Config {
    pub fn from_env() -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        dotenvy::dotenv().ok();

        let database_url = std::env::var("DATABASE_URL")
            .unwrap_or_else(|_| "postgres://cuadrada:cuadrada_dev@localhost:5432/cuadrada".to_string());

        let claude_api_key = std::env::var("CLAUDE_API_KEY")
            .map_err(|_| "CLAUDE_API_KEY must be set")?;

        let base_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let upload_folder = base_dir.join(
            std::env::var("UPLOAD_FOLDER").unwrap_or_else(|_| "uploads".to_string())
        );
        let results_folder = base_dir.join(
            std::env::var("RESULTS_FOLDER").unwrap_or_else(|_| "results".to_string())
        );

        let host = std::env::var("HOST").unwrap_or_else(|_| "0.0.0.0".to_string());
        let port: u16 = std::env::var("PORT")
            .unwrap_or_else(|_| "5001".to_string())
            .parse()
            .unwrap_or(5001);

        Ok(Self {
            database_url,
            claude_api_key,
            upload_folder,
            results_folder,
            host,
            port,
        })
    }
}
