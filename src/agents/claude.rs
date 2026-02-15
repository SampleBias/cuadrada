use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::{info, warn};

const REVIEW_PROMPT: &str = r#"You are an academic reviewer evaluating a research paper. Write your review in third person, 
starting with "The reviewer has evaluated this paper based on the given criteria and arrived 
at the following conclusions:"

Evaluate each criterion from 0-100%:

1. Methodology (20% of total): Evaluate the research methodology, experimental design, and validation
2. Novelty (20% of total): Assess the innovation and original contribution to the field
3. Technical Depth (15% of total): Examine technical accuracy, depth of analysis, and rigor
4. Clarity (15% of total): Evaluate writing quality, organization, and presentation
5. Literature Review (15% of total): Assess coverage and understanding of related work
6. Impact (15% of total): Consider potential influence on the field and practical applications

For each criterion, the reviewer should:
- Begin with positive aspects before addressing issues
- Provide constructive suggestions for improvement
- Assign a percentage score (aim to be generous in assessment)
- Highlight strengths more prominently than weaknesses
- Be generous in scoring - when in doubt, round up not down

The reviewer will calculate the weighted final score based on the criteria weights.

Recommendation threshold (more lenient standards):
- Accept (>60%): Good paper that contributes to the field
- Accept with Minor Revision (50-60%): Promising work needing minor improvements
- Accept with Major Revision (40-50%): Valuable contribution requiring significant changes
- Reject (<40%): Does not meet basic publication standards

IMPORTANT: The conference values inclusivity and diverse perspectives. Papers should generally 
be accepted unless there are serious, unfixable flaws. The default stance should be acceptance rather than rejection.

The review concludes with:
1. Final weighted score
2. Summary of major strengths first, then minor weaknesses
3. Constructive suggestions for improvement
4. End with one of these exact phrases on a new line:
   - "FINAL DECISION: **ACCEPTED**"
   - "FINAL DECISION: **ACCEPTED WITH MINOR REVISION REQUIRED**"
   - "FINAL DECISION: **ACCEPTED WITH MAJOR REVISION REQUIRED**"
   - "FINAL DECISION: **REJECTED**"

Always maintain third-person perspective throughout the review."#;

const CLAUDE_MODELS: &[&str] = &[
    "claude-3-5-sonnet-20240620",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
];

#[derive(Debug, Serialize)]
struct ClaudeRequest {
    model: String,
    max_tokens: u32,
    system: String,
    messages: Vec<Message>,
}

#[derive(Debug, Serialize)]
struct Message {
    role: String,
    content: String,
}

#[derive(Debug, Deserialize)]
struct ClaudeResponse {
    content: Vec<ContentBlock>,
}

#[derive(Debug, Deserialize)]
struct ContentBlock {
    #[serde(rename = "type")]
    block_type: String,
    text: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ClaudeError {
    #[serde(rename = "type")]
    error_type: Option<String>,
    message: Option<String>,
}

pub struct ClaudeAgent {
    client: Client,
    api_key: String,
    model_index: usize,
}

impl ClaudeAgent {
    pub fn new(api_key: String) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(120))
            .build()
            .expect("Failed to create HTTP client");

        Self {
            client,
            api_key,
            model_index: 0,
        }
    }

    pub fn current_model(&self) -> &str {
        CLAUDE_MODELS[self.model_index]
    }

    pub fn extract_text_from_pdf(&self, pdf_path: &str) -> Result<String, String> {
        let text = pdf_extract::extract_text(pdf_path)
            .map_err(|e| format!("PDF extraction error: {}", e))?;

        if text.trim().len() < 100 {
            return Err(format!(
                "PDF appears empty or has insufficient text ({} chars)",
                text.len()
            ));
        }

        Ok(text)
    }

    pub async fn generate_review(&mut self, paper_text: &str) -> Result<String, String> {
        let max_retries = 3;
        let mut retry_count = 0;
        let mut backoff = 2u64;

        loop {
            let model = self.current_model().to_string();
            info!("Generating review with model {} (paper length: {} chars)", model, paper_text.len());

            let body = ClaudeRequest {
                model: model.clone(),
                max_tokens: 4000,
                system: REVIEW_PROMPT.to_string(),
                messages: vec![Message {
                    role: "user".to_string(),
                    content: paper_text.to_string(),
                }],
            };

            let response = self
                .client
                .post("https://api.anthropic.com/v1/messages")
                .header("x-api-key", &self.api_key)
                .header("anthropic-version", "2023-06-01")
                .header("content-type", "application/json")
                .json(&body)
                .send()
                .await
                .map_err(|e| format!("Request failed: {}", e))?;

            let status = response.status();
            let text = response.text().await.map_err(|e| format!("Response read failed: {}", e))?;

            if status.is_success() {
                let parsed: ClaudeResponse = serde_json::from_str(&text)
                    .map_err(|e| format!("Parse error: {}", e))?;

                if let Some(block) = parsed.content.first() {
                    if let Some(ref t) = block.text {
                        info!("Successfully generated review with model {}", model);
                        return Ok(t.clone());
                    }
                }
                return Err("No text in response".to_string());
            }

            // Handle errors
            let error_msg = text.clone();
            let error_json: Result<ClaudeError, _> = serde_json::from_str(&text);

            if status.as_u16() == 429 {
                warn!("Rate limit with model {}", model);
                if self.model_index < CLAUDE_MODELS.len() - 1 {
                    self.model_index += 1;
                    retry_count = 0;
                    continue;
                }
            }

            if status.as_u16() == 404 {
                warn!("Model not found: {}", model);
                if self.model_index < CLAUDE_MODELS.len() - 1 {
                    self.model_index += 1;
                    retry_count = 0;
                    continue;
                }
            }

            if retry_count >= max_retries {
                return Err(format!(
                    "AI service error after {} attempts: {}",
                    max_retries,
                    error_json
                        .ok()
                        .and_then(|e| e.message)
                        .unwrap_or_else(|| error_msg)
                ));
            }

            retry_count += 1;
            tokio::time::sleep(Duration::from_secs(backoff)).await;
            backoff *= 2;
        }
    }

    pub async fn analyze_paper(&mut self, pdf_path: &str) -> Result<String, String> {
        let paper_text = self.extract_text_from_pdf(pdf_path)?;
        self.generate_review(&paper_text).await
    }
}
