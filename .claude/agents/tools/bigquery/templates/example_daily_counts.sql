-- description: EXAMPLE / PLACEHOLDER - delete this file once you have added a real
--   template. It references a table that does not exist, so running it will fail
--   with "Not found"; it is here to show the conventions, not to be run.
-- params:
--   dataset_table: STRING - unused here, kept to show a STRING parameter
--   start_date: DATE - first day of the window, inclusive
--   end_date: DATE - last day of the window, inclusive
--   statuses: ARRAY<STRING> - status values to keep (pass a list)
--
-- Conventions this file demonstrates:
--   1. Every value is a @named parameter. Never paste values into the SQL.
--   2. The file name (without .sql) is the template name: "example_daily_counts".
--   3. This header is optional. A bare .sql file with @params works exactly as well.
--   4. Filter on the partition column so the cost guard does not stop the query.

SELECT
  DATE(created_at) AS day,
  status,
  COUNT(*) AS row_count
FROM `replace_me_dataset.replace_me_table`
WHERE DATE(created_at) BETWEEN @start_date AND @end_date
  AND status IN UNNEST(@statuses)
  AND @dataset_table IS NOT NULL  -- placeholder use of the STRING parameter
GROUP BY day, status
ORDER BY day, status
