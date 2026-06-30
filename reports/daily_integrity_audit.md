# 539 Daily Integrity Audit

- generated_at: 2026-06-30T13:46:37
- status: passed
- failed_count: 0

- PASS: draw_count_minimum / {'count': 5901, 'min_period': 96000001, 'max_period': 115000157, 'min_date': '2007-01-01', 'max_date': '2026-06-29'}
- PASS: latest_date_fresh / {'latest': '2026-06-29', 'expected': '2026-06-29'}
- PASS: no_duplicate_periods / []
- PASS: no_duplicate_dates / []
- PASS: no_invalid_draw_rows / []
- PASS: no_stale_pending_predictions / []
- PASS: recent_predictions_settled / [{'target_period': 115000152, 'status': 'settled', 'actual_period': 115000152, 'top5_hits': 0, 'top10_hits': 3, 'top15_hits': 3}, {'target_period': 115000153, 'status': 'settled', 'actual_period': 115000153, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 3}, {'target_period': 115000154, 'status': 'settled', 'actual_period': 115000154, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 1}, {'target_period': 115000155, 'status': 'settled', 'actual_period': 115000155, 'top5_hits': 1, 'top10_hits': 1, 'top15_hits': 2}, {'target_period': 115000156, 'status': 'settled', 'actual_period': 115000156, 'top5_hits': 0, 'top10_hits': 1, 'top15_hits': 2}, {'target_period': 115000157, 'status': 'settled', 'actual_period': 115000157, 'top5_hits': 1, 'top10_hits': 2, 'top15_hits': 3}]
- PASS: no_missing_recent_prediction_records / []
- PASS: latest_draw_has_settled_prediction_record / {'target_period': 115000157, 'status': 'settled', 'actual_period': 115000157, 'actual_date': '2026-06-29', 'top5_hits': 1, 'top10_hits': 2, 'top15_hits': 3}
- PASS: analysis_matches_database / {'analysis': 115000157, 'database': 115000157}
- PASS: health_sync_passed / {'database_latest_period': 115000157, 'analysis_latest_period': 115000157, 'prediction_based_on_period': 115000157, 'status': 'synced'}
- PASS: history_has_latest_pending_or_settled / {'expected_target': 115000158}
- PASS: battle_report_mentions_latest / {'period': 115000157, 'draw_date': '2026-06-29'}
- PASS: battle_report_has_settlement_rows / settled and pending labels
- PASS: battle_report_is_compact_precision_report / compact precision report labels
- PASS: battle_report_has_explicit_dates / date labels
- PASS: battle_report_has_low_probability_link / low probability page link
- PASS: battle_report_has_super_single_section / super single section
- PASS: battle_report_has_no_mojibake_question_marks / battle report must not contain mojibake question marks
- PASS: low_probability_page_exists / C:\Users\MSI\Documents\Codex\539PredictionSystem\reports\539低機率精準暫避.html
- PASS: low_probability_page_has_no_mojibake_question_marks / low probability page must not contain mojibake question marks
- PASS: low_probability_page_has_required_sections / low probability section labels