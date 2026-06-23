# 539 Daily Integrity Audit

- generated_at: 2026-06-22T11:47:00
- status: passed
- failed_count: 0

- PASS: draw_count_minimum / {'count': 5894, 'min_period': 96000001, 'max_period': 115000150, 'min_date': '2007-01-01', 'max_date': '2026-06-20'}
- PASS: latest_date_fresh / {'latest': '2026-06-20', 'expected': '2026-06-20'}
- PASS: no_duplicate_periods / []
- PASS: no_duplicate_dates / []
- PASS: no_invalid_draw_rows / []
- PASS: no_stale_pending_predictions / []
- PASS: recent_predictions_settled / [{'target_period': 115000145, 'status': 'settled', 'actual_period': 115000145, 'top5_hits': 0, 'top10_hits': 2, 'top15_hits': 2}, {'target_period': 115000146, 'status': 'settled', 'actual_period': 115000146, 'top5_hits': 0, 'top10_hits': 2, 'top15_hits': 3}, {'target_period': 115000147, 'status': 'settled', 'actual_period': 115000147, 'top5_hits': 0, 'top10_hits': 1, 'top15_hits': 2}, {'target_period': 115000148, 'status': 'settled', 'actual_period': 115000148, 'top5_hits': 0, 'top10_hits': 0, 'top15_hits': 1}, {'target_period': 115000149, 'status': 'settled', 'actual_period': 115000149, 'top5_hits': 0, 'top10_hits': 0, 'top15_hits': 0}, {'target_period': 115000150, 'status': 'settled', 'actual_period': 115000150, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 1}]
- PASS: analysis_matches_database / {'analysis': 115000150, 'database': 115000150}
- PASS: health_sync_passed / {'database_latest_period': 115000150, 'analysis_latest_period': 115000150, 'prediction_based_on_period': 115000150, 'status': 'synced'}
- PASS: history_has_latest_pending_or_settled / {'expected_target': 115000151}
- PASS: battle_report_mentions_latest / {'period': 115000150, 'draw_date': '2026-06-20'}
- PASS: battle_report_has_settlement_rows / settled and pending labels
- PASS: battle_report_has_active_mode / current_precision_stability_v38_monthly_recall_soft_reentry
- PASS: battle_report_has_explicit_dates / date labels