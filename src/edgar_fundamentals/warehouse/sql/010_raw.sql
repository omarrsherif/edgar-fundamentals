-- Raw layer: the Parquet staging files exposed inside the warehouse.
-- sub/tag/pre are small enough to materialise; num (36M rows) stays a view over Parquet so the
-- warehouse file does not store every fact twice (fact_financial_facts holds the modelled subset).
CREATE OR REPLACE TABLE raw_sub AS SELECT * FROM read_parquet(${pq_sub}, union_by_name = true);
CREATE OR REPLACE TABLE raw_tag AS SELECT * FROM read_parquet(${pq_tag}, union_by_name = true);
CREATE OR REPLACE TABLE raw_pre AS SELECT * FROM read_parquet(${pq_pre}, union_by_name = true);
CREATE OR REPLACE VIEW raw_num AS SELECT * FROM read_parquet(${pq_num}, union_by_name = true);
