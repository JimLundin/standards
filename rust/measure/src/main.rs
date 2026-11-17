mod decisions;
mod modules;

use std::env;
use std::io::{self, Write as _};
use std::path::Path;
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut out = io::stdout().lock();
    env::args_os()
        .skip(1)
        .flat_map(|root| modules::measure(Path::new(&root)))
        .try_for_each(|record| writeln!(out, "{record}"))
        .map_or(ExitCode::FAILURE, |()| ExitCode::SUCCESS)
}
