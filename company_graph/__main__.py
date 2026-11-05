import argparse
import json
from .pipeline import build_graph
from .render import write_site


def main():
    parser = argparse.ArgumentParser(description="Build a company knowledge graph from supplied records.")
    parser.add_argument("input", help="Normalized JSON input, see examples/companies.json")
    parser.add_argument("--out", default="output")
    parser.add_argument("--base-url", default="https://example.test/companies")
    args = parser.parse_args()
    with open(args.input) as handle:
        graph = build_graph(json.load(handle), args.base_url)
    write_site(graph, args.out)
    print(f'{len(graph["nodes"])} companies; {len(graph["edges"])} relationships; {len(graph["review"])} identity reviews. Open {args.out}/index.html')


if __name__ == "__main__":
    main()
