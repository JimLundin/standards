use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};
use syn::ext::IdentExt as _;
use syn::{Attribute, Expr, ExprLit, Item, ItemMod, Lit, Meta};

use crate::decisions::{self, Function};

struct Module {
    path: PathBuf,
    dir: PathBuf,
}

pub fn measure(root: &Path) -> Vec<Value> {
    file(root, root, &parent(root))
}

fn parent(path: &Path) -> PathBuf {
    path.parent().map_or_else(PathBuf::new, Path::to_path_buf)
}

fn shown(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

fn file(root: &Path, path: &Path, dir: &Path) -> Vec<Value> {
    match parsed(path) {
        Ok(syntax) => decisions::functions(&syntax)
            .iter()
            .map(|function| record(root, path, function))
            .chain(
                modules(&syntax.items, dir, &parent(path))
                    .iter()
                    .flat_map(|module| file(root, &module.path, &module.dir)),
            )
            .collect(),
        Err(error) => vec![json!({
            "root": shown(root),
            "path": shown(path),
            "error": error,
        })],
    }
}

fn record(root: &Path, path: &Path, function: &Function) -> Value {
    json!({
        "root": shown(root),
        "path": shown(path),
        "function": function.name,
        "line": function.line,
        "decisions": function.decisions,
    })
}

fn parsed(path: &Path) -> Result<syn::File, String> {
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    syn::parse_file(&text)
        .map_err(|error| format!("line {}: {error}", error.span().start().line))
}

fn modules(items: &[Item], dir: &Path, base: &Path) -> Vec<Module> {
    items
        .iter()
        .filter_map(|item| match item {
            Item::Mod(module) if !decisions::is_test(&module.attrs) => {
                Some(module)
            }
            _ => None,
        })
        .flat_map(|module| declared(module, dir, base))
        .collect()
}

fn declared(module: &ItemMod, dir: &Path, base: &Path) -> Vec<Module> {
    let name = module.ident.unraw().to_string();
    match (&module.content, path_attribute(&module.attrs)) {
        (Some((_, items)), path) => {
            let inner = dir.join(path.unwrap_or(name));
            modules(items, &inner, &inner)
        }
        (None, Some(path)) => {
            let file = base.join(path);
            vec![Module {
                dir: parent(&file),
                path: file,
            }]
        }
        (None, None) => vec![located(&dir.join(name))],
    }
}

fn located(stem: &Path) -> Module {
    let flat = stem.with_extension("rs");
    let path = if flat.is_file() {
        flat
    } else {
        stem.join("mod.rs")
    };
    Module {
        path,
        dir: stem.to_path_buf(),
    }
}

fn path_attribute(attrs: &[Attribute]) -> Option<String> {
    attrs
        .iter()
        .find(|attr| attr.path().is_ident("path"))
        .and_then(|attr| match &attr.meta {
            Meta::NameValue(pair) => literal(&pair.value),
            _ => None,
        })
}

fn literal(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(text),
            ..
        }) => Some(text.value()),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::io;
    use std::path::Path;

    use serde_json::Value;

    use super::measure;

    const FILES: [(&str, &str); 10] = [
        (
            "src/main.rs",
            "mod a; mod b; #[path = \"other/c.rs\"] mod c;
             mod inline { mod d; #[path = \"e.rs\"] mod renamed; }
             mod r#broken; mod missing;
             #[cfg(test)] mod tests;
             fn main() { if a {} }",
        ),
        ("src/a.rs", "mod child; fn a() {}"),
        ("src/a/child.rs", "fn a_child() {}"),
        ("src/b/mod.rs", "mod child; fn b() {}"),
        ("src/b/child.rs", "fn b_child() {}"),
        ("src/other/c.rs", "mod child; fn c() {}"),
        ("src/other/child.rs", "fn c_child() {}"),
        ("src/inline/d.rs", "fn d() {}"),
        ("src/inline/e.rs", "fn e() {}"),
        ("src/broken.rs", "fn broken() -> {}"),
    ];

    fn text(record: &Value, key: &str) -> String {
        record[key].as_str().unwrap_or_default().to_owned()
    }

    fn found(root: &Path, record: &Value) -> (String, String) {
        let path = text(record, "path");
        let relative = path.trim_start_matches(&*root.to_string_lossy());
        let error = text(record, "error");
        let line = error.starts_with("line 1: ").then_some("syntax error");
        (
            relative.to_owned(),
            line.map_or_else(|| text(record, "function"), str::to_owned),
        )
    }

    fn walked(root: &Path) -> io::Result<Vec<(String, String)>> {
        FILES.iter().try_for_each(|(path, contents)| {
            let file = root.join(path);
            fs::create_dir_all(file.parent().unwrap_or(root))?;
            fs::write(file, contents)
        })?;
        let records = measure(&root.join("src/main.rs"));
        fs::remove_dir_all(root)?;
        Ok(records.iter().map(|record| found(root, record)).collect())
    }

    #[test]
    fn modules_are_followed_from_the_root() -> io::Result<()> {
        let root = std::env::temp_dir()
            .join(format!("rust-decisions-{}", std::process::id()));
        let expected = [
            ("/src/main.rs", "main"),
            ("/src/a.rs", "a"),
            ("/src/a/child.rs", "a_child"),
            ("/src/b/mod.rs", "b"),
            ("/src/b/child.rs", "b_child"),
            ("/src/other/c.rs", "c"),
            ("/src/other/child.rs", "c_child"),
            ("/src/inline/d.rs", "d"),
            ("/src/inline/e.rs", "e"),
            ("/src/broken.rs", "syntax error"),
            ("/src/missing/mod.rs", ""),
        ]
        .map(|(path, name)| (path.to_owned(), name.to_owned()));
        assert_eq!(walked(&root)?, expected);
        Ok(())
    }
}
