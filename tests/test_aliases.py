from __future__ import annotations

import duckdb

from edgar_fundamentals import config
from edgar_fundamentals.warehouse import aliases


def test_alias_yaml_is_consistent():
    assert aliases.check_aliases() == []


def test_every_metric_has_datatype_and_tags():
    cfg = config.load_yaml("aliases.yaml")
    for metric, spec in cfg["metrics"].items():
        assert spec["datatype"] in {"monetary", "shares", "perShare", "pure"}, metric
        assert spec["tags"], metric
        assert spec.get("description"), metric


def test_no_tag_maps_to_two_metrics_except_combined_concepts():
    seen = {}
    for metric, tag, taxonomy, priority, datatype, stmt in aliases.alias_rows():
        key = (taxonomy, tag)
        if key in seen and not tag.endswith("BasicAndDiluted"):
            raise AssertionError(f"{tag} mapped to {seen[key]} and {metric}")
        seen[key] = metric


def test_priorities_are_contiguous_per_metric():
    by_metric: dict[str, list[int]] = {}
    for metric, tag, taxonomy, priority, datatype, stmt in aliases.alias_rows():
        by_metric.setdefault(metric, []).append(priority)
    for metric, ps in by_metric.items():
        assert sorted(ps) == list(range(1, len(ps) + 1)), metric


def test_dei_prefix_parsed_into_taxonomy():
    rows = [r for r in aliases.alias_rows() if r[1] == "EntityCommonStockSharesOutstanding"]
    assert rows and rows[0][2] == "dei"


def test_parse_formula():
    assert aliases.parse_formula("+revenue -cost_of_revenue") == [(1, "revenue"), (-1, "cost_of_revenue")]


def test_alias_table_and_sic_map_load():
    con = duckdb.connect(":memory:")
    aliases.create_alias_table(con)
    aliases.create_sic_table(con)
    assert con.execute("SELECT count(*) FROM alias_map").fetchone()[0] > 30
    # Apple: SIC 3571 -> Manufacturing / Industrial Machinery & Equipment
    div, ind = con.execute("SELECT division, industry FROM sic_sector_map WHERE 3571 BETWEEN sic_from AND sic_to").fetchone()
    assert div == "Manufacturing" and "Machinery" in ind
    assert con.execute("SELECT count(*) FROM financial_sic_ranges WHERE 6022 BETWEEN sic_from AND sic_to").fetchone()[0] == 1


def test_sic_ranges_do_not_overlap():
    con = duckdb.connect(":memory:")
    aliases.create_sic_table(con)
    n = con.execute("""SELECT count(*) FROM sic_sector_map a JOIN sic_sector_map b
                       ON a.major_group < b.major_group AND a.sic_from <= b.sic_to AND b.sic_from <= a.sic_to""").fetchone()[0]
    assert n == 0
