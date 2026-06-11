# 539 Daily Integrity Audit

- generated_at: 2026-06-11T09:14:06
- status: passed
- failed_count: 0

- PASS: draw_count_minimum / {'count': 5885, 'min_period': 96000001, 'max_period': 115000141, 'min_date': '2007-01-01', 'max_date': '2026-06-10'}
- PASS: latest_date_fresh / {'latest': '2026-06-10', 'expected': '2026-06-10'}
- PASS: no_duplicate_periods / []
- PASS: no_duplicate_dates / []
- PASS: no_invalid_draw_rows / []
- PASS: no_stale_pending_predictions / []
- PASS: recent_predictions_settled / [{'target_period': 115000136, 'status': 'settled', 'actual_period': 115000136, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 3}, {'target_period': 115000137, 'status': 'settled', 'actual_period': 115000137, 'top5_hits': 1, 'top10_hits': 3, 'top15_hits': 4}, {'target_period': 115000138, 'status': 'settled', 'actual_period': 115000138, 'top5_hits': 0, 'top10_hits': 0, 'top15_hits': 0}, {'target_period': 115000139, 'status': 'settled', 'actual_period': 115000139, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 1}, {'target_period': 115000140, 'status': 'settled', 'actual_period': 115000140, 'top5_hits': 2, 'top10_hits': 2, 'top15_hits': 2}, {'target_period': 115000141, 'status': 'settled', 'actual_period': 115000141, 'top5_hits': 0, 'top10_hits': 0, 'top15_hits': 0}]
- PASS: analysis_matches_database / {'analysis': 115000141, 'database': 115000141}
- PASS: health_sync_passed / {'database_latest_period': 115000141, 'analysis_latest_period': 115000141, 'prediction_based_on_period': 115000141, 'status': 'synced'}
- PASS: history_has_latest_pending_or_settled / {'expected_target': 115000142}
- PASS: battle_report_mentions_latest / {'period': 115000141, 'draw_date': '2026-06-10'}
- PASS: battle_report_has_settlement_rows / settled and pending labels
- PASS: battle_report_has_active_mode / restored_20260604_hit4_v31
- PASS: battle_report_has_explicit_dates / date labels