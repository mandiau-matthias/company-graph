# Company Graph

**[Explore the fictional company graph](https://mandiau-matthias.github.io/company-graph/)** · [Inspect the input](examples/companies.json)

Turn overlapping company records into a knowledge graph with traceable facts, explicit conflicts, and company pages with JSON-LD.

Canal Works has two reported revenue figures: **€1,000,000 and €1,300,000** for the same period. The example preserves both observations and withholds the selected revenue until the conflict is resolved. A directory entry with a similar name remains a candidate instead of silently joining the company.

## Try it

Python 3.11 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m company_graph examples/companies.json --out output
open output/index.html
```

On Linux or Windows, open `output/index.html` in your browser. Dependencies need an initial download. Processing the supplied records makes no network requests and needs no database, account, or model.

Change the directory's revenue from `1300000` to `1000000` in `examples/companies.json` and rerun. The conflict disappears and the supported value becomes visible. Changing it to `0` in both records preserves a real zero.

## Supply your records

The JSON contains a trusted `entities` catalogue, timestamped `records` from your sources, and explicit `relationships`. Each record supplies registry identifiers, a source reference, and typed facts. Facts retain currency, period, accounting scope, evidence status and publication permissions. The sample uses three fictional source systems and invented company records.

```python
from company_graph import build_graph

graph = build_graph(your_normalized_input, base_url="https://your.example/companies")
```

Outputs are `graph.json`, `organizations.jsonld`, an overview, and one HTML page per company. The public graph excludes private evidence, unapproved redistribution, unresolved identity facts and withdrawn observations. Financial conflicts stay visible only to the extent their candidate evidence is public. Supply public record identifiers: the match log includes source and record IDs, never private fact payloads.

The current JSON-LD maps organization identity, supported descriptions and declared parent relationships. Full financial observations remain in the graph and visible evidence panels. It does not turn a valuation into an unsupported schema.org property or infer a narrower business type from an industry code.

## Where this comes from

I built the underlying contracts at Upswitch. This release extracts its provider-independent identity resolution, evidence assertions and reconciliation, then adds a standalone pipeline, static viewer and fictional examples. [Source versions and hashes](SOURCE.json) preserve attribution. The original enrichment reference layer was separate from production wiring; this package does not reproduce the entire Upswitch platform or imply that it caused a measured SEO result.

Extraction changes: the public entry point rejects duplicate source observations, filters exports, and treats incompatible currencies/units/period starts as a conflict. The library validates identifier formats and matches within your catalogue; it does not prove that a registry number or supplied fact is authentic. Live data adapters and licensed datasets are not included. Supply data you may use and publish. Structured markup does not guarantee indexing or rankings.

## Checks and contributions

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover ambiguous identities, conflicting facts, currencies, zero values, private-data exclusion, source timing, relationship evidence, repeatable output, HTML escaping, and linked structured data. A useful contribution is a small fictional example that produces an incorrect merge, reconciliation or public export.
