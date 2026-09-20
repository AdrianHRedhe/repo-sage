// Assertions for highlightCode in src/reposage/web/static/index.html,
// executed by tests/test_web_highlight.py via node.
//
// The page ships as one dependency-free HTML file with no build step and
// no JS test runner, and adding one for this is more machinery than the
// code under test. So this evaluates the page's own <script> with a
// stubbed DOM and asserts against the real function.

import { readFileSync } from "node:fs";
import assert from "node:assert";

const html = readFileSync("src/reposage/web/static/index.html", "utf8");
const script = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).join("\n");
const { highlightCode } = new Function(`
  const stubEl = new Proxy({}, { get: () => () => stubEl });
  const document = { getElementById: () => stubEl, addEventListener: () => {}, querySelector: () => stubEl, querySelectorAll: () => [] };
  const window = { addEventListener: () => {}, parent: { postMessage: () => {} }, location: { search: "" } };
  const localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  const fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ repos: [], sandbox: null }) });
  ${script}
  return { highlightCode };
`)();

const spans = (out, cls) => out.match(new RegExp(`<span class="${cls}">([\\s\\S]*?)</span>`, "g")) || [];

// --- the reported bug: Markdown highlighted as code
const md = "# RepoSage\n\nIt is not a real grammar, so don't expect type resolution. 10 per hour.";
const mdOut = highlightCode(md, "Markdown");
assert.strictEqual(spans(mdOut, "tok-comment").length, 0, "markdown heading must not be a comment");
assert.strictEqual(spans(mdOut, "tok-string").length, 0, "apostrophe must not open a string");
assert.strictEqual(spans(mdOut, "tok-keyword").length, 0, "prose must not be keyworded");
assert.strictEqual(spans(mdOut, "tok-number").length, 0, "prose numbers must not be tinted");
assert.ok(mdOut.includes("don&#39;t"), "prose is still escaped");
assert.ok(!mdOut.includes("<span"), "prose gets no markup at all");

// --- the same defect in CSS
const cssOut = highlightCode("#main {\n  color: #fff;\n}", "CSS");
assert.strictEqual(spans(cssOut, "tok-comment").length, 0, "CSS # is a selector/colour, not a comment");
const cssBlock = highlightCode("/* real */\n#a { color: red; }", "CSS");
assert.deepStrictEqual(spans(cssBlock, "tok-comment"), ['<span class="tok-comment">/* real */</span>']);

// --- languages where # IS a comment keep working
for (const lang of ["Python", "Shell", "bash", "Ruby"]) {
  const out = highlightCode("# a real comment\nx = 1", lang);
  assert.strictEqual(spans(out, "tok-comment").length, 1, `${lang} # comment preserved`);
}

// --- C-like languages, and the unknown-label fallback
for (const lang of ["Go", "JavaScript", "Rust", "some-unknown-lang"]) {
  const out = highlightCode('x := 1 // ok\n/* b */ f("hi")', lang);
  assert.strictEqual(spans(out, "tok-comment").length, 2, `${lang} slash+block comments`);
}
// ...and those must NOT treat # as a comment
assert.strictEqual(spans(highlightCode("a #b\nc", "Go"), "tok-comment").length, 0, "Go # is not a comment");

// --- SQL and HTML
assert.strictEqual(spans(highlightCode("-- note\nSELECT 1", "SQL"), "tok-comment").length, 1, "SQL -- comment");
assert.strictEqual(spans(highlightCode("<!-- x -->\n<p>", "HTML"), "tok-comment").length, 1, "HTML markup comment");

// --- JSON has no comment syntax; the empty alternation must not break the tokenizer
const jsonOut = highlightCode('{"a": 1, "b": "two"}', "json");
assert.strictEqual(spans(jsonOut, "tok-comment").length, 0, "JSON has no comments");
assert.strictEqual(spans(jsonOut, "tok-string").length, 3, "JSON strings still highlight");
assert.strictEqual(spans(jsonOut, "tok-number").length, 1, "JSON numbers still highlight");

// --- code highlighting itself is unchanged for the common case
const pyOut = highlightCode('def f():\n    return "x"  # c\n', "Python");
assert.strictEqual(spans(pyOut, "tok-keyword").length, 2, "def/return still keywords");
assert.strictEqual(spans(pyOut, "tok-string").length, 1);
assert.strictEqual(spans(pyOut, "tok-comment").length, 1);

// --- escaping is never lost, whatever the language
for (const lang of ["Python", "Markdown", "CSS", "json", ""]) {
  const out = highlightCode('<script>alert("x")</script>', lang);
  assert.ok(!out.includes("<script>"), `raw tag must stay escaped for ${lang}`);
}

console.log("all highlightCode assertions passed");
