import copy
import json
from pathlib import Path
import tempfile
import unittest

from company_graph import build_graph
from company_graph.render import write_site

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/companies.json"


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(EXAMPLE.read_text())

    def test_same_name_is_not_an_identity_match(self):
        graph = build_graph(self.raw)
        self.assertEqual(graph["matches"][-1]["status"], "candidate")
        self.assertNotIn("unconfirmed directory", json.dumps(graph))

    def test_conflict_is_visible_but_not_selected(self):
        company = build_graph(self.raw)["nodes"][0]
        self.assertEqual([f["predicate"] for f in company["facts"]], ["description"])
        self.assertEqual(len(company["conflicts"][0]["candidates"]), 2)

    def test_editing_assumption_changes_result(self):
        self.raw["records"][4]["facts"][0]["value"]["value"] = "1000000"
        company = build_graph(self.raw)["nodes"][0]
        self.assertFalse(company["conflicts"])
        self.assertEqual(company["facts"][1]["value"]["value"], "1000000")

    def test_currency_difference_never_reconciles_as_equal(self):
        self.raw["records"][4]["facts"][0]["value"].update(value="1000000", currency="USD")
        self.assertEqual(len(build_graph(self.raw)["nodes"][0]["conflicts"]), 1)

    def test_zero_stays_zero(self):
        for i in (3, 4):
            self.raw["records"][i]["facts"][0]["value"]["value"] = "0"
        self.assertEqual(build_graph(self.raw)["nodes"][0]["facts"][1]["value"]["value"], "0")

    def test_private_fact_never_enters_any_export(self):
        secret = {"predicate": "internal_note", "value": {"kind": "text", "value": "private-canary"},
                  "visibility": "tenant_private", "permitted_uses": ["internal_analysis"]}
        self.raw["records"][0]["facts"].append(secret)
        graph = build_graph(self.raw)
        with tempfile.TemporaryDirectory() as folder:
            write_site(graph, folder)
            self.assertTrue(all("private-canary" not in p.read_text() for p in Path(folder).iterdir()))

    def test_display_without_redistribution_is_withheld(self):
        self.raw["records"][0]["facts"][0]["permitted_uses"] = ["display"]
        self.assertFalse(build_graph(self.raw)["nodes"][0]["facts"])

    def test_shared_address_does_not_prove_control(self):
        self.raw["relationships"][0]["attributes"]["control_basis"] = "shared_address"
        with self.assertRaises(ValueError):
            build_graph(self.raw)

    def test_future_observations_and_unknown_candidates_rejected(self):
        future = copy.deepcopy(self.raw)
        future["records"][0]["source"]["retrieved_at"] = "2027-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            build_graph(future)
        self.raw["records"][-1]["candidate_ids"] = ["missing"]
        with self.assertRaises(ValueError):
            build_graph(self.raw)

    def test_repeat_build_is_identical_and_render_is_escaped(self):
        self.raw["entities"][0]["name"] = '</script><img src=x onerror=alert(1)>'
        first = build_graph(self.raw)
        self.assertEqual(first, build_graph(self.raw))
        with tempfile.TemporaryDirectory() as folder:
            write_site(first, folder)
            page = (Path(folder) / 'be-0400000001.html').read_text()
            self.assertNotIn('</script><img', page)
            self.assertIn('\\u003c/script>', page)
            self.assertIn('&lt;img', page)

    def test_jsonld_relationships_resolve_to_visible_pages(self):
        graph = build_graph(self.raw)
        self.assertEqual(graph["nodes"][0]["jsonld"]["subOrganization"][0]["@id"], graph["nodes"][1]["jsonld"]["@id"])


if __name__ == "__main__":
    unittest.main()
