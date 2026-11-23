mod decisions;
mod modules;

use std::env;
use std::io::{self, Write as _};
use std::path::Path;
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut out = io::stdout().lock();
    if env::args_os()
        .nth(1)
        .is_some_and(|first| first == "--version")
    {
        return writeln!(out, "rust-decisions {}", env!("CARGO_PKG_VERSION"))
            .map_or(ExitCode::FAILURE, |()| ExitCode::SUCCESS);
    }
    env::args_os()
        .skip(1)
        .flat_map(|root| modules::measure(Path::new(&root)))
        .try_for_each(|record| writeln!(out, "{record}"))
        .map_or(ExitCode::FAILURE, |()| ExitCode::SUCCESS)
}
