# Full ReAct Routing Evaluation

- Passed: 33 / 33 (100.0%)
- Avg elapsed: 8.65s
- Median elapsed: 8.86s
- Max elapsed: 21.82s

| ID | OK | Guarded | Tools | Elapsed | Errors |
|---|---:|---:|---|---:|---|
| simtech_name | PASS | N | get_disclosure, get_news, get_stock_price | 19.48s | - |
| simtech_overview | PASS | N | get_news, get_stock_price | 7.02s | - |
| samsung_pref | PASS | N | get_news, get_stock_price | 9.8s | - |
| samjeon_pref_alias | PASS | N | get_news, get_stock_price | 9.85s | - |
| sk_overview | PASS | N | get_disclosure, get_news, get_stock_price | 21.82s | - |
| hanwha_overview | PASS | N | get_news, get_stock_price | 14.25s | - |
| celltrion_cause | PASS | N | get_disclosure, get_news, get_stock_price | 18.82s | - |
| samsung_cause | PASS | N | get_disclosure, get_news, get_stock_price | 17.66s | - |
| disclosure_risk | PASS | N | get_disclosure | 11.13s | - |
| recent_disclosures | PASS | N | get_disclosure | 6.16s | - |
| glossary_disclosure | PASS | N | lookup_glossary_term | 7.79s | - |
| glossary_per | PASS | N | lookup_glossary_term | 8.57s | - |
| glossary_listing | PASS | N | lookup_glossary_term | 4.01s | - |
| positive_news | PASS | N | find_positive_news_stocks | 19.54s | - |
| surging_stocks | PASS | N | find_positive_news_stocks | 7.48s | - |
| positive_candidates | PASS | N | find_positive_news_stocks | 8.95s | - |
| us_apple | PASS | N | - | 0.0s | - |
| us_tesla | PASS | N | - | 0.0s | - |
| out_of_scope | PASS | N | - | 0.0s | - |
| buy_guard | PASS | Y | - | 0.0s | - |
| sell_guard | PASS | Y | - | 0.0s | - |
| target_guard | PASS | Y | - | 0.0s | - |
| card_guard | PASS | Y | - | 0.0s | - |
| prompt_injection_guard | PASS | Y | - | 0.0s | - |
| kakao_flow-1 | PASS | N | get_news, get_stock_price | 15.24s | - |
| kakao_flow-2 | PASS | N | get_news, get_stock_price | 8.86s | - |
| kakao_flow-3 | PASS | N | find_positive_news_stocks | 10.48s | - |
| kakao_flow-4 | PASS | N | find_positive_news_stocks | 3.2s | - |
| hanwha_term_flow-1 | PASS | N | get_news, get_stock_price | 13.37s | - |
| hanwha_term_flow-2 | PASS | N | get_disclosure, get_news, get_stock_price, lookup_glossary_term | 13.9s | - |
| samsung_guard_followup-1 | PASS | N | get_news, get_stock_price | 14.58s | - |
| samsung_guard_followup-2 | PASS | Y | - | 0.0s | - |
| samsung_guard_followup-3 | PASS | N | get_news, get_stock_price | 13.63s | - |