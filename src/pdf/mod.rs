// Certificate PDF generation
// Uses genpdf - requires Liberation or similar fonts in standard paths
use genpdf::*;
use std::path::Path;

pub fn generate_certificate(paper_title: &str, output_path: &Path) -> Result<(), String> {
    // Try common font paths - genpdf needs actual font files for metrics
    let font_paths = [
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/TTF",
        "/System/Library/Fonts/Supplemental",
        "/Library/Fonts",
    ];

    let font_family = font_paths
        .iter()
        .find(|p| std::path::Path::new(p).exists())
        .and_then(|path| {
            ["LiberationSans", "DejaVuSans", "Arial"]
                .iter()
                .find_map(|name| genpdf::fonts::from_files(*path, name, None).ok())
        })
        .ok_or_else(|| {
            "No suitable fonts found. Install: apt install fonts-liberation".to_string()
        })?;

    let mut doc = genpdf::Document::new(font_family);
    doc.set_title("Certificate of Acceptance");

    let mut decorator = genpdf::SimplePageDecorator::new();
    decorator.set_margins(10);
    doc.set_page_decorator(decorator);

    let title_style = genpdf::style::Style::new().with_font_size(24);
    doc.push(genpdf::elements::Paragraph::new("Certificate of Acceptance").styled(title_style));

    let title = if paper_title.len() > 80 {
        format!("{}...", &paper_title[..80])
    } else {
        paper_title.to_string()
    };
    doc.push(genpdf::elements::Paragraph::new(&title));
    doc.push(genpdf::elements::Break::new(0.5));
    doc.push(genpdf::elements::Paragraph::new(
        "has successfully passed Cuadrada's AI-powered peer review process",
    ));
    doc.push(genpdf::elements::Break::new(0.5));

    let date = chrono::Utc::now().format("%B %d, %Y").to_string();
    let id = output_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .replace("_certificate", "");

    doc.push(genpdf::elements::Paragraph::new(format!("Date: {}", date)));
    doc.push(genpdf::elements::Paragraph::new(format!("Certificate ID: {}", id)));

    doc.render_to_file(output_path).map_err(|e| e.to_string())
}
