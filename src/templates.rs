use std::sync::OnceLock;
use tera::Tera;

static TERA: OnceLock<Tera> = OnceLock::new();

pub fn get_tera() -> &'static Tera {
    TERA.get_or_init(|| {
        let mut tera = Tera::default();
        let template_dir = std::path::Path::new("templates");
        if template_dir.exists() {
            tera.add_template_files(
                std::fs::read_dir(template_dir)
                    .unwrap()
                    .filter_map(Result::ok)
                    .filter(|e| e.path().extension().map_or(false, |ext| ext == "html"))
                    .map(|e| {
                        (
                            e.path()
                                .file_name()
                                .unwrap()
                                .to_str()
                                .unwrap()
                                .to_string(),
                            e.path(),
                        )
                    }),
            )
            .expect("Failed to load templates");
        }
        tera
    })
}
