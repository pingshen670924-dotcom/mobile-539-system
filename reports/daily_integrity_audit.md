# 539 Daily Integrity Audit

- generated_at: 2026-06-29T10:34:56
- status: passed
- failed_count: 0

- PASS: draw_count_minimum / {'count': 5900, 'min_period': 96000001, 'max_period': 115000156, 'min_date': '2007-01-01', 'max_date': '2026-06-27'}
- PASS: latest_date_fresh / {'latest': '2026-06-27', 'expected': '2026-06-27'}
- PASS: no_duplicate_periods / []
- PASS: no_duplicate_dates / []
- PASS: no_invalid_draw_rows / []
- PASS: no_stale_pending_predictions / []
- PASS: recent_predictions_settled / [{'target_period': 115000151, 'status': 'settled', 'actual_period': 115000151, 'top5_hits': 2, 'top10_hits': 3, 'top15_hits': 4}, {'target_period': 115000152, 'status': 'settled', 'actual_period': 115000152, 'top5_hits': 0, 'top10_hits': 3, 'top15_hits': 3}, {'target_period': 115000153, 'status': 'settled', 'actual_period': 115000153, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 3}, {'target_period': 115000154, 'status': 'settled', 'actual_period': 115000154, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 1}, {'target_period': 115000155, 'status': 'settled', 'actual_period': 115000155, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 2}]
- PASS: analysis_matches_database / {'analysis': 115000156, 'database': 115000156}
- PASS: health_sync_passed / {'database_latest_period': 115000156, 'analysis_latest_period': 115000156, 'prediction_based_on_period': 115000156, 'status': 'synced'}
- PASS: history_has_latest_pending_or_settled / {'expected_target': 115000157}
- PASS: battle_report_mentions_latest / {'period': 115000156, 'draw_date': '2026-06-27'}
- PASS: battle_report_has_settlement_rows / settled and pending labels
- PASS: battle_report_has_active_mode / current_precision_stability_v44_micro_confidence_short_packs
- PASS: battle_report_has_explicit_dates / date labels