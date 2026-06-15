# 539 Daily Integrity Audit

- generated_at: 2026-06-16T07:24:31
- status: passed
- failed_count: 0

- PASS: draw_count_minimum / {'count': 5889, 'min_period': 96000001, 'max_period': 115000145, 'min_date': '2007-01-01', 'max_date': '2026-06-15'}
- PASS: latest_date_fresh / {'latest': '2026-06-15', 'expected': '2026-06-15'}
- PASS: no_duplicate_periods / []
- PASS: no_duplicate_dates / []
- PASS: no_invalid_draw_rows / []
- PASS: no_stale_pending_predictions / []
- PASS: recent_predictions_settled / [{'target_period': 115000140, 'status': 'settled', 'actual_period': 115000140, 'top5_hits': 2, 'top10_hits': 2, 'top15_hits': 2}, {'target_period': 115000141, 'status': 'settled', 'actual_period': 115000141, 'top5_hits': 0, 'top10_hits': 0, 'top15_hits': 0}, {'target_period': 115000142, 'status': 'settled', 'actual_period': 115000142, 'top5_hits': 1, 'top10_hits': 2, 'top15_hits': 3}, {'target_period': 115000143, 'status': 'settled', 'actual_period': 115000143, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 1}, {'target_period': 115000145, 'status': 'settled', 'actual_period': 115000145, 'top5_hits': 0, 'top10_hits': 2, 'top15_hits': 2}]
- PASS: analysis_matches_database / {'analysis': 115000145, 'database': 115000145}
- PASS: health_sync_passed / {'database_latest_period': 115000145, 'analysis_latest_period': 115000145, 'prediction_based_on_period': 115000145, 'status': 'synced'}
- PASS: history_has_latest_pending_or_settled / {'expected_target': 115000146}
- PASS: battle_report_mentions_latest / {'period': 115000145, 'draw_date': '2026-06-15'}
- PASS: battle_report_has_settlement_rows / settled and pending labels
- PASS: battle_report_has_active_mode / current_precision_stability_v35
- PASS: battle_report_has_explicit_dates / date labels