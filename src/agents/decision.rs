use regex::Regex;
use std::collections::HashMap;

pub fn determine_decision(review_text: &str) -> DecisionResult {
    let review_upper = review_text.to_uppercase();
    let review_lower = review_text.to_lowercase();

    let (decision, is_accepted) = if Regex::new(r"FINAL DECISION:\s*\*\*ACCEPTED\*\*")
        .unwrap()
        .is_match(&review_upper)
    {
        ("ACCEPTED".to_string(), true)
    } else if Regex::new(r"FINAL DECISION:\s*\*\*ACCEPTED WITH (MINOR|MAJOR) REVISION")
        .unwrap()
        .is_match(&review_upper)
    {
        ("REVISION".to_string(), false)
    } else if Regex::new(r"FINAL DECISION:\s*\*\*REJECTED\*\*")
        .unwrap()
        .is_match(&review_upper)
    {
        ("REJECTED".to_string(), false)
    } else if (review_lower.contains("accepted") && !review_lower.contains("rejected"))
        || review_lower.contains("recommend publication")
    {
        ("ACCEPTED".to_string(), true)
    } else if review_lower.contains("revision")
        || review_lower.contains("revise")
        || review_lower.contains("improvements needed")
    {
        ("REVISION".to_string(), false)
    } else if review_lower.contains("reject") {
        ("REJECTED".to_string(), false)
    } else {
        ("REVISION".to_string(), false)
    };

    let summary = review_text
        .split("\n\n")
        .next()
        .unwrap_or(review_text)
        .to_string();
    let truncated_summary = if summary.len() > 300 {
        format!("{}...", &summary[..300])
    } else {
        summary
    };

    let full_review = if review_text.len() > 1000 {
        format!("{}...", &review_text[..1000])
    } else {
        review_text.to_string()
    };

    DecisionResult {
        decision,
        summary: truncated_summary,
        full_review,
        accepted: is_accepted,
    }
}

#[derive(Debug)]
pub struct DecisionResult {
    pub decision: String,
    pub summary: String,
    pub full_review: String,
    pub accepted: bool,
}
