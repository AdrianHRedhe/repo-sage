// Assertions for highlightCode in src/reposage/web/static/index.html,
// executed by tests/test_web_highlight.py via node.
//
// The page ships as one dependency-free HTML file with no build step and
// no JS test runner, and adding one for this is more machinery than the
// code under test. So this evaluates the page's own <script> with a
// stubbed DOM and asserts against the real function.

import { readFileSync } from "node:fs";
import assert from "node:assert";

// Evaluating the page runs its bootstrap too - loadConfig/loadRepos/
// refreshSandboxStatus and the iframe-height IIFE - which is not what is
// under test here, so the stubs below are built so none of it can do
// anything: fetch returns a promise that never settles, so every
// bootstrap coroutine suspends at its first await and can neither touch
// the DOM further nor reject; window.self === window.top, so the iframe
// branch is skipped; and every DOM lookup returns a stub that accepts any
// property or call. Should page code fail anyway, name it for what it is -
// but only while the page is being evaluated. Node delivers a failed
// assertion in this module to `uncaughtException` as well (top-level await
// below makes module evaluation asynchronous), so past that point the
// error is simply reported as itself.
let evaluatingPage = true;
for (const event of ["unhandledRejection", "uncaughtException"]) {
  process.on(event, (err) => {
    if (evaluatingPage) console.error(`${event} from the page's own bootstrap, not from highlightCode:`);
    console.error(err);
    process.exit(1);
  });
}

const stubEl = new Proxy({}, { get: () => () => stubEl, set: () => true });
const stubDocument = {
  getElementById: () => stubEl,
  querySelector: () => stubEl,
  querySelectorAll: () => [],
  createElement: () => stubEl,
  addEventListener: () => {},
  documentElement: stubEl,
  body: stubEl,
};
const stubWindow = { addEventListener: () => {}, parent: { postMessage: () => {} }, location: { search: "" } };
stubWindow.self = stubWindow;
stubWindow.top = stubWindow;
const stubLocalStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const stubFetch = () => new Promise(() => {});
class StubResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const html = readFileSync("src/reposage/web/static/index.html", "utf8");
const script = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).join("\n");
const { highlightCode, renderAnswerMarkdown } = new Function(
  "document",
  "window",
  "localStorage",
  "fetch",
  "ResizeObserver",
  `${script}\nreturn { highlightCode, renderAnswerMarkdown };`,
)(stubDocument, stubWindow, stubLocalStorage, stubFetch, StubResizeObserver);
evaluatingPage = false;

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

// --- fence aliases pick the same comment syntax as the canonical name,
// so ```py neither loses its "#" comments nor eats "a // b" to end of line
for (const [alias, canonical] of [["py", "Python"], ["rb", "Ruby"], ["ps1", "powershell"], ["tf", "hcl"], ["htm", "HTML"]]) {
  const sample = "# c\nx = 1 // 2\n-- d\n<!-- e -->\n/* f */";
  assert.strictEqual(highlightCode(sample, alias), highlightCode(sample, canonical), `${alias} matches ${canonical}`);
}
const pyAliasOut = highlightCode("# a real comment\nq = a // b", "py");
assert.strictEqual(spans(pyAliasOut, "tok-comment").length, 1, "py has exactly the hash comment");
assert.ok(pyAliasOut.includes("// b"), "py floor division is not swallowed as a comment");

// --- a fence label naming an Object.prototype member is just an unknown
// label: it must not throw, and must not inherit some other comment set
for (const lang of ["constructor", "toString", "valueOf", "hasOwnProperty", "isPrototypeOf", "__proto__"]) {
  const out = highlightCode('x := 1 // ok\n/* b */ f("hi")\na #b', lang);
  assert.strictEqual(spans(out, "tok-comment").length, 2, `${lang} falls back to slash+block`);
}

// --- an unlabelled fence is code of unknown language, not prose
const bareOut = highlightCode('const x = 1; // ok\nreturn "s";', "");
assert.strictEqual(spans(bareOut, "tok-comment").length, 1, "unlabelled fence still gets comments");
assert.ok(spans(bareOut, "tok-keyword").length > 0, "unlabelled fence still gets keywords");

// --- escaping is never lost, whatever the language
for (const lang of ["Python", "Markdown", "CSS", "json", "", "constructor"]) {
  const out = highlightCode('<script>alert("x")</script>', lang);
  assert.ok(!out.includes("<script>"), `raw tag must stay escaped for ${lang}`);
}

// --- a fence label the fence pattern cannot match used to desynchronize
// the whole replace pass, leaking raw backticks and the next block's label
const answer = 'Here:\n\n```c++\nint a = 1;\n```\n\nThen:\n\n```python\nx = 1\n```\n';
const rendered = renderAnswerMarkdown(answer, []);
assert.ok(!rendered.includes("`"), "no backtick leaks out of a c++ fence");
assert.ok(rendered.includes('<div class="code-lang">c++</div>'), "c++ keeps its label");
assert.ok(rendered.includes('<div class="code-lang">python</div>'), "python keeps its label");
const bodies = [...rendered.matchAll(/<pre><code>([\s\S]*?)<\/code><\/pre>/g)].map((m) => m[1]);
assert.strictEqual(bodies.length, 2, "both blocks render as code");
assert.ok(bodies[0].includes("int a = "), "c++ body stays in its own block");
assert.ok(bodies[1].includes("x = "), "python body stays in its own block");
assert.ok(!bodies.some((b) => b.includes("Then:")), "prose between the blocks is not captured as code");
assert.ok(!bodies.some((b) => b.includes("python")), "no fence label leaks into a block body");

// --- labels arrive normalised, whatever spacing or attributes they carry
for (const label of ["Python", " python ", "python title=x"]) {
  const out = renderAnswerMarkdown("```" + label + "\n# c\nx = 1\n```\n", []);
  assert.ok(out.includes('<div class="code-lang">python</div>'), `"${label}" normalises to python`);
  assert.strictEqual(spans(out, "tok-comment").length, 1, `"${label}" gets Python comment syntax`);
}

// Let anything the page scheduled settle before reporting success, so a
// bootstrap failure is reported by the handlers above rather than landing
// after this line.
await new Promise((resolve) => setImmediate(resolve));

console.log("all highlightCode assertions passed");
