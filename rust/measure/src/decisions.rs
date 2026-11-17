use std::mem::discriminant;

use proc_macro2::{Delimiter, Group, TokenStream, TokenTree};
use syn::parse::Parser as _;
use syn::punctuated::Punctuated;
use syn::visit::{self, Visit};
use syn::{
    Attribute, BinOp, Block, Expr, ExprBinary, ExprForLoop, ExprIf, ExprMatch,
    ExprWhile, File, Ident, ImplItemFn, Item, ItemFn, ItemImpl, ItemMod, Local,
    Macro, PatGuard, Stmt, Token, TraitItemFn,
};

#[derive(Debug, PartialEq, Eq)]
pub struct Function {
    pub name: String,
    pub line: usize,
    pub decisions: usize,
}

pub fn functions(file: &File) -> Vec<Function> {
    let mut found = Functions::default();
    found.visit_file(file);
    found.0
}

pub fn is_test(attrs: &[Attribute]) -> bool {
    attrs
        .iter()
        .any(|attr| is_test_attribute(attr) || is_cfg_test(attr))
}

fn is_test_attribute(attr: &Attribute) -> bool {
    attr.path()
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "test")
}

fn is_cfg_test(attr: &Attribute) -> bool {
    attr.path().is_ident("cfg")
        && attr
            .parse_args::<Ident>()
            .is_ok_and(|ident| ident == "test")
}

#[derive(Default)]
struct Functions(Vec<Function>);

impl<'ast> Visit<'ast> for Functions {
    fn visit_item_fn(&mut self, item: &'ast ItemFn) {
        if !is_test(&item.attrs) {
            self.0.push(measured(&item.sig.ident, &item.block));
            visit::visit_item_fn(self, item);
        }
    }

    fn visit_impl_item_fn(&mut self, item: &'ast ImplItemFn) {
        if !is_test(&item.attrs) {
            self.0.push(measured(&item.sig.ident, &item.block));
            visit::visit_impl_item_fn(self, item);
        }
    }

    fn visit_trait_item_fn(&mut self, item: &'ast TraitItemFn) {
        if let Some(block) = &item.default
            && !is_test(&item.attrs)
        {
            self.0.push(measured(&item.sig.ident, block));
            visit::visit_trait_item_fn(self, item);
        }
    }

    fn visit_item_mod(&mut self, item: &'ast ItemMod) {
        if !is_test(&item.attrs) {
            visit::visit_item_mod(self, item);
        }
    }

    fn visit_item_impl(&mut self, item: &'ast ItemImpl) {
        if !is_test(&item.attrs) {
            visit::visit_item_impl(self, item);
        }
    }
}

fn measured(name: &Ident, block: &Block) -> Function {
    Function {
        name: name.to_string(),
        line: name.span().start().line,
        decisions: counted(|counter| counter.visit_block(block)),
    }
}

#[derive(Default)]
struct Counter(usize);

fn counted(visit: impl FnOnce(&mut Counter)) -> usize {
    let mut counter = Counter::default();
    visit(&mut counter);
    counter.0
}

impl<'ast> Visit<'ast> for Counter {
    fn visit_expr_if(&mut self, expr: &'ast ExprIf) {
        self.0 += 1;
        visit::visit_expr_if(self, expr);
    }

    fn visit_expr_match(&mut self, expr: &'ast ExprMatch) {
        self.0 += usize::from(expr.arms.len() > 1);
        visit::visit_expr_match(self, expr);
    }

    fn visit_pat_guard(&mut self, pat: &'ast PatGuard) {
        self.0 += 1;
        visit::visit_pat_guard(self, pat);
    }

    fn visit_expr_for_loop(&mut self, expr: &'ast ExprForLoop) {
        self.0 += 1;
        visit::visit_expr_for_loop(self, expr);
    }

    fn visit_expr_while(&mut self, expr: &'ast ExprWhile) {
        self.0 += 1;
        visit::visit_expr_while(self, expr);
    }

    fn visit_local(&mut self, local: &'ast Local) {
        self.0 += usize::from(
            local
                .init
                .as_ref()
                .is_some_and(|init| init.diverge.is_some()),
        );
        visit::visit_local(self, local);
    }

    fn visit_expr_binary(&mut self, expr: &'ast ExprBinary) {
        self.0 += usize::from(begins_sequence(expr));
        visit::visit_expr_binary(self, expr);
    }

    fn visit_item(&mut self, _item: &'ast Item) {}

    fn visit_macro(&mut self, mac: &'ast Macro) {
        self.0 += in_macro(&mac.tokens);
    }
}

const fn is_logical(op: &BinOp) -> bool {
    matches!(op, BinOp::And(_) | BinOp::Or(_))
}

fn begins_sequence(expr: &ExprBinary) -> bool {
    is_logical(&expr.op) && !continues(&expr.left, &expr.op)
}

fn continues(left: &Expr, op: &BinOp) -> bool {
    matches!(left, Expr::Binary(inner)
        if discriminant(&inner.op) == discriminant(op))
}

fn in_macro(tokens: &TokenStream) -> usize {
    Punctuated::<Expr, Token![,]>::parse_terminated
        .parse2(tokens.clone())
        .map_or_else(
            |_| in_groups(tokens.clone()),
            |exprs| {
                exprs
                    .iter()
                    .map(|expr| counted(|counter| counter.visit_expr(expr)))
                    .sum()
            },
        )
}

fn in_groups(tokens: TokenStream) -> usize {
    tokens
        .into_iter()
        .map(|tree| match tree {
            TokenTree::Group(group) => in_group(&group),
            _ => 0,
        })
        .sum()
}

fn in_group(group: &Group) -> usize {
    statements(group).map_or_else(
        || in_groups(group.stream()),
        |stmts| {
            stmts
                .iter()
                .map(|stmt| counted(|counter| counter.visit_stmt(stmt)))
                .sum()
        },
    )
}

fn statements(group: &Group) -> Option<Vec<Stmt>> {
    (group.delimiter() == Delimiter::Brace)
        .then(|| Block::parse_within.parse2(group.stream()).ok())
        .flatten()
}

#[cfg(test)]
mod tests {
    use super::{Function, functions};

    type Measured = Result<Vec<(String, usize)>, String>;

    fn measure(source: &str) -> Measured {
        syn::parse_file(source)
            .map(|file| {
                functions(&file)
                    .into_iter()
                    .map(
                        |Function {
                             name, decisions, ..
                         }| (name, decisions),
                    )
                    .collect()
            })
            .map_err(|error| error.to_string())
    }

    fn one(source: &str) -> Result<Vec<usize>, String> {
        measure(&format!("fn f() {{ {source} }}")).map(|found| {
            found.into_iter().map(|(_, decisions)| decisions).collect()
        })
    }

    #[test]
    fn written_control_flow_counts() {
        assert_eq!(one("if a { b }"), Ok(vec![1]));
        assert_eq!(one("if a { b } else if c { d } else { e }"), Ok(vec![2]));
        assert_eq!(one("if let Some(x) = a { x }"), Ok(vec![1]));
        assert_eq!(one("match a { 0 => b, _ => c }"), Ok(vec![1]));
        assert_eq!(one("match a { 0 => b, 1 => c, _ => d }"), Ok(vec![1]));
        assert_eq!(one("match a { x if x > 1 => b, _ => c }"), Ok(vec![2]));
        assert_eq!(one("for x in a { b(x); }"), Ok(vec![1]));
        assert_eq!(one("while a { b(); }"), Ok(vec![1]));
        assert_eq!(one("while let Some(x) = a.pop() { b(x); }"), Ok(vec![1]));
        assert_eq!(one("let Some(x) = a else { return };"), Ok(vec![1]));
    }

    #[test]
    fn logical_operators_count_once_per_sequence() {
        assert_eq!(one("a && b && c"), Ok(vec![1]));
        assert_eq!(one("a || b || c"), Ok(vec![1]));
        assert_eq!(one("a && b || c"), Ok(vec![2]));
        assert_eq!(one("a || b && c"), Ok(vec![2]));
        assert_eq!(one("if let Some(x) = a && x > 1 { b }"), Ok(vec![2]));
        assert_eq!(one("a & b | c == d"), Ok(vec![0]));
    }

    #[test]
    fn desugaring_does_not_count() {
        assert_eq!(one("a()?.b().await?; c.await"), Ok(vec![0]));
        assert_eq!(one("loop { a(); }"), Ok(vec![0]));
        assert_eq!(one("match a { b => c }"), Ok(vec![0]));
        assert_eq!(one("return a; break; continue;"), Ok(vec![0]));
        assert_eq!(one("let x = a;"), Ok(vec![0]));
    }

    #[test]
    fn closures_and_async_blocks_belong_to_their_function() {
        assert_eq!(one("a.filter(|x| if x { b } else { c })"), Ok(vec![1]));
        assert_eq!(
            one("Box::pin(async move { if a { b.await } else { 0 } })"),
            Ok(vec![1])
        );
    }

    #[test]
    fn macros_count_only_the_code_written_in_them() {
        assert_eq!(one("tracing::info!(value, \"seen\");"), Ok(vec![0]));
        assert_eq!(one("info!(target: \"t\", ?x, \"seen\");"), Ok(vec![0]));
        assert_eq!(
            one("println!(\"{}\", if a { b } else { c });"),
            Ok(vec![1])
        );
        assert_eq!(one("assert!(a && b);"), Ok(vec![1]));
        assert_eq!(one("vec![a.then(|| b)]"), Ok(vec![0]));
        assert_eq!(
            one("tokio::select! { x = a.recv() => x, y = b => y }"),
            Ok(vec![0])
        );
        assert_eq!(
            one("tokio::select! { x = a => { if x { b } }, else => {} }"),
            Ok(vec![1])
        );
        assert_eq!(one("m!(a => [{ for x in y {} }])"), Ok(vec![1]));
        assert_eq!(one("json!({ \"a\": 1 })"), Ok(vec![0]));
        assert_eq!(
            one("macro_rules! m { ($x:expr) => { if $x {} } }"),
            Ok(vec![0])
        );
    }

    #[test]
    fn every_function_is_measured_on_its_own() {
        assert_eq!(
            measure(
                "fn outer() { fn inner() { if a {} } if b {} }
                 struct S;
                 impl S { fn method(&self) { for x in y {} } }
                 trait T { fn provided() { while a {} } fn required(); }
                 mod m { fn nested() {} }"
            ),
            Ok(vec![
                ("outer".to_owned(), 1),
                ("inner".to_owned(), 1),
                ("method".to_owned(), 1),
                ("provided".to_owned(), 1),
                ("nested".to_owned(), 0),
            ])
        );
    }

    #[test]
    fn tests_are_not_measured() {
        assert_eq!(
            measure(
                "#[test] fn a() {}
                 #[tokio::test] async fn b() {}
                 #[cfg(test)] mod tests { fn c() {} }
                 #[cfg(test)] impl S { fn d() {} }
                 trait T { #[cfg(test)] fn e() {} }
                 struct S;
                 impl S { #[cfg(test)] fn f() {} }
                 #[cfg(not(test))] fn g() {}"
            ),
            Ok(vec![("g".to_owned(), 0)])
        );
    }

    #[test]
    fn functions_report_the_line_of_their_name() {
        let file = syn::parse_file("\n\nfn first() {}\nfn\nsecond() {}");
        assert_eq!(
            file.map(|syntax| functions(&syntax))
                .map_err(|error| error.to_string()),
            Ok(vec![
                Function {
                    name: "first".to_owned(),
                    line: 3,
                    decisions: 0
                },
                Function {
                    name: "second".to_owned(),
                    line: 5,
                    decisions: 0
                },
            ])
        );
    }
}
