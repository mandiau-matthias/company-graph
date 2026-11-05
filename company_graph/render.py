"""A static, inspectable demonstration of the public graph. No external assets."""
import html
import json
from pathlib import Path


CSS = """
:root{color-scheme:light;font-family:system-ui,sans-serif;color:#24212c;background:#f6f4f0}
*{box-sizing:border-box}body{margin:0}main{max-width:1100px;margin:auto;padding:48px 24px}
a{color:#6644bb}a:focus-visible,summary:focus-visible{outline:3px solid #8b68d5;outline-offset:4px}
h1{font-size:clamp(2.4rem,7vw,4.8rem);letter-spacing:-.06em;line-height:1.05;max-width:850px}
h2{font-size:1.7rem}p{line-height:1.65;max-width:760px}.eyebrow{color:#6644bb;letter-spacing:.12em;font-size:.8rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(290px,100%),1fr));gap:18px}
.card{background:white;border:1px solid #ddd7e6;border-radius:16px;padding:24px;margin:16px 0;overflow-wrap:anywhere}
.warn{border-left:4px solid #a45a22}.stat{font-size:2rem;font-weight:700}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem;background:#f4f1f8;padding:16px;border-radius:8px}
summary{cursor:pointer;padding:12px 0;font-weight:600}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px 8px;border-bottom:1px solid #ddd;vertical-align:top}
small{color:#655d71}.edges{padding:0;list-style:none}.edges li{padding:16px;background:#ebe5f6;margin-bottom:8px;border-radius:12px}.tag{font-size:.8rem;padding:4px 8px;border-radius:8px;background:#eee8f8}
"""


def esc(value):
    return html.escape(str(value), quote=True)


def document(title, body, markup=None):
    structured = "" if markup is None else '<script type="application/ld+json">' + json.dumps(markup, ensure_ascii=False).replace("<", "\\u003c") + '</script>'
    return f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style>{structured}<body><main><p class="eyebrow">AUTOMATRON / COMPANY GRAPH</p>{body}</main></body></html>'


def write_site(graph, directory):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n")
    markup = {"@context": "https://schema.org", "@graph": [n["jsonld"] for n in graph["nodes"]]}
    (out / "organizations.jsonld").write_text(json.dumps(markup, indent=2, ensure_ascii=False) + "\n")
    cards = []
    names = {n["id"]: n["name"] for n in graph["nodes"]}
    for node in graph["nodes"]:
        filename = node["url"].rsplit("/", 1)[-1]
        fact_count, conflict_count = len(node["facts"]), len(node["conflicts"])
        counts = f'{fact_count} published fact{"" if fact_count == 1 else "s"} · {conflict_count} conflict{"" if conflict_count == 1 else "s"}'
        cards.append(f'<article class="card"><span class="tag">{esc(node["country"])} · {esc(node["registry_number"])}</span><h2><a href="{esc(filename)}">{esc(node["name"])}</a></h2><p>{counts}</p><p>Open the record and follow its evidence.</p></article>')
        facts = []
        for fact in node["facts"]:
            value = fact["value"]
            shown = f'{value["value"]} {value.get("currency") or value.get("unit") or ""}'
            facts.append(f'<article class="card"><h2>{esc(fact["predicate"].replace("_", " "))}</h2><p class="stat">{esc(shown)}</p><p>{esc(fact["evidence_status"])} · {esc(fact["source"]["source_system"])} · period {esc(value.get("period_end") or "not specified")}</p><details><summary>Inspect this fact and its source</summary><pre>{esc(json.dumps(fact, indent=2, ensure_ascii=False))}</pre></details></article>')
        conflicts = ''.join(f'<article class="card warn"><h2>{esc(c["predicate"])} needs review</h2><p>This field is withheld from selected facts. {esc(c["reason"])}.</p><details><summary>Compare public observations</summary><pre>{esc(json.dumps(c["candidates"], indent=2))}</pre></details></article>' for c in node["conflicts"])
        body = f'<a href="index.html">← All companies</a><h1>{esc(node["name"])}</h1><p>Fictional company · {esc(node["country"])} registry {esc(node["registry_number"])}</p>{"".join(facts)}{conflicts}'
        outgoing = [e for e in graph["edges"] if e["from_subject"]["subject_id"] == node["id"]]
        body += ''.join(f'<article class="card"><h2>{esc(e["kind"].replace("_", " "))} {esc(names[e["to_subject"]["subject_id"]])}</h2><details><summary>Inspect relationship evidence</summary><pre>{esc(json.dumps(e, indent=2))}</pre></details></article>' for e in outgoing)
        body += f'<details class="card"><summary>Structured data for this page</summary><pre>{esc(json.dumps(node["jsonld"], indent=2))}</pre></details>'
        (out / filename).write_text(document(node["name"], body, {"@context": "https://schema.org", **node["jsonld"]}))
    edges = ''.join(f'<li>{esc(names[e["from_subject"]["subject_id"]])} <strong>→ {esc(e["kind"].replace("_", " "))} →</strong> {esc(names[e["to_subject"]["subject_id"]])}</li>' for e in graph["edges"])
    rows = ''.join(f'<tr><td>{esc(m["source"])}</td><td>{esc(m["record"])}</td><td>{esc(m["status"])}</td></tr>' for m in graph["matches"])
    body = f'<h1>One company.<br>Several sources.<br>Every fact traceable.</h1><p>Three fictional companies, overlapping records and a deliberate disagreement. Explore which facts can be published, which identities need review, and why.</p><p><a href="graph.json">Download the graph</a> · <a href="organizations.jsonld">Open the JSON-LD</a> · <a href="https://github.com/mandiau-matthias/company-graph">Run it with your records</a></p><div class="grid">{"".join(cards)}</div><h2>Evidence-backed relationships</h2><ul class="edges">{edges}</ul><section class="card"><h2>How the records matched</h2><p>A similar name alone stays a candidate. Exact matches use the supplied registry catalogue.</p><table><thead><tr><th>Source</th><th>Record</th><th>Decision</th></tr></thead><tbody>{rows}</tbody></table></section><p><small>Sample snapshot: {esc(graph["as_of"])}. All companies and observations are fictional. The library processes supplied evidence; it does not verify registry truth or promise search rankings.</small></p>'
    (out / "index.html").write_text(document("Company Graph · Automatron", body))
