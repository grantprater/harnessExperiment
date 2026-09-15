# HotpotQA Distractor Evaluation

- Model: `meta-llama/llama-3.1-8b-instruct` (temperature 0, via OpenRouter)
- Questions: 50 sampled with seed 0 from the first 100 validation rows
- Arms: full, route | prompt hash `6e1ba81064`
- Report generated: 2026-09-15 00:59 UTC from `results.jsonl`
- Decision rule (fixed before running): An arm is called better or worse than `full` only if the 95% paired bootstrap interval of its per-question F1 difference excludes 0. Otherwise: no detectable difference.

## Per-arm results

| Arm | Scored | Errors | Missing | EM | F1 | Answer format failures | Mean calls | Mean prompt tokens | Mean completion tokens |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| full | 50 | 0 | 0 | 0.600 | 0.714 | 23 | 1.00 | 1439 | 6 |
| route | 50 | 0 | 0 | 0.520 | 0.637 | 28 | 1.96 | 784 | 26 |

## Paired comparison against `full` (questions both arms completed)

| Arm | Paired n | Mean F1 diff | 95% CI | Mean EM diff | 95% CI | Verdict (decision rule) |
| :-- | --: | --: | :-- | --: | :-- | :-- |
| route | 50 | -0.077 | [-0.198, +0.040] | -0.080 | [-0.220, +0.060] | no detectable difference |

## Routing step (`route` arm)

- Replies naming no valid title (scored wrong, no answer call): 2/50
- Picked both gold documents: 29/50
- Mean gold-document recall: 0.730

## F1 by question type

| Arm | bridge | comparison |
| :-- | --: | --: |
| full | 0.677 (n=39) | 0.845 (n=11) |
| route | 0.612 (n=39) | 0.727 (n=11) |

## Per-question results

| Question id | Type | Gold | full prediction (EM) | route prediction (EM) |
| :-- | :-- | :-- | :-- | :-- |
| `5a8e1027554299653c1aa15f` | bridge | 2009 Big 12 Conference | 2009, Big 12 (0) | 2009, Big 12 (0) |
| `5adccd795542990d50227d2c` | bridge | Beijing | Beijing. (1) | Beijing (1) |
| `5ab96ab755429970cfb8eacd` | bridge | Max Martin, Savan Kotecha and… | Max Martin, Savan Kotecha, and Ilya Sal… (1) | Starsmith (0) |
| `5abd94525542992ac4f382d2` | bridge | YG Entertainment | YG Entertainment (1) | YG Entertainment (1) |
| `5a7cc50e554299452d57ba3e` | comparison | Letters to Cleo | Letters to Cleo (1) | 4 (0) |
| `5a8361b65542992ef85e22a0` | bridge | International Boxing Hall of … | IBF (0) | IBHOF (0) |
| `5a77152355429966f1a36c2e` | bridge | 821 | 821 (1) | There is no information in the provided… (0) |
| `5a77724455429972597f153e` | bridge | Indianapolis Motor Speedway | Indianapolis Motor Speedway (1) | Indianapolis Motor Speedway. (1) |
| `5a7571135542992d0ec05f98` | bridge | New York City | New York. (0) | New York City (1) |
| `5a7be2595542997c3ec972ac` | comparison | Adeline Virginia Woolf | Virginia Woolf (0) | Virginia Woolf (January 25, 1882) (0) |
| `5ab859a955429934fafe6d7b` | bridge | Phil Spector | Phil Spector (1) | Phil Spector (1) |
| `5a77cb335542997042120b3a` | bridge | John John Florence | John John Florence (1) | John Florence (0) |
| `5a828c8355429966c78a6a50` | bridge | Henry J. Kaiser | Henry J. Kaiser (1) | Henry J. Kaiser (1) |
| `5a80840f554299485f59863b` | bridge | Charmed | Charmed (1) | Charmed (1) |
| `5ab29c24554299449642c932` | comparison | yes | Yes (1) | Yes. (1) |
| `5a80721b554299485f5985ef` | bridge | World War II | World War II (1) | World War II (1) |
| `5ae5736e5542990ba0bbb2b3` | bridge | April 1, 1949 | April 1, 1949 (1) | April 1, 1949 (1) |
| `5ab3b0bf5542992ade7c6e39` | bridge | 1999 | 1999 (1) | There is not enough information in the … (0) |
| `5ae2dd2055429928c423950d` | bridge | Newport | Newport (1) | Newport. (1) |
| `5abc0a5d5542993f40c73c64` | comparison | no | No (1) | No (1) |
| `5aba7cfe554299232ef4a2fd` | bridge | Carabao Cup | Carabao Cup (1) | Carabao Cup (1) |
| `5a78bd9b554299078472774a` | bridge | British | British (1) | (none) (0) |
| `5ae0d4c9554299603e418468` | bridge | 1969 until 1974 | Nixon (0) | 1969-1974 (0) |
| `5a7a0e1e5542990783324e1a` | comparison | Scotch Collie | Scotch Collie. (1) | the Scotch Collie (1) |
| `5a88658955429938390d3f47` | bridge | Conscription | requiring only men to register for the … (0) | requiring only men to register for the … (0) |
| `5a8db19d5542994ba4e3dd00` | comparison | yes | Yes (1) | Yes (1) |
| `5ab2d3df554299194fa9352c` | bridge | sovereignty | Victory over Italy. (0) | sovereignty (1) |
| `5a85fb085542994775f606de` | bridge | Ronald Shusett | Francis Ford Coppola (0) | There is no information in the provided… (0) |
| `5a835478554299123d8c20ed` | bridge | 250 million | None (0) | There is no information in the provided… (0) |
| `5aba749055429901930fa7d8` | comparison | director | Director (1) | Cinematographer. (0) |
| `5ae73acb5542991e8301cc07` | bridge | Drifting | Drifting (1) | Drifting. (1) |
| `5a74106b55429979e288289e` | bridge | Mumbai | Kochi (0) | Mumbai (1) |
| `5adf37a95542995ec70e8f97` | bridge | 1838 | 1838 (1) | 1838 (1) |
| `5abfb3425542990832d3a1c0` | bridge | The Conversation | The Conversation (1) | The Conversation (1) |
| `5a7320565542991f9a20c61d` | bridge | Keith Bostic | Jerry Glanville (0) | No (0) |
| `5a80b3a9554299485f5986cc` | bridge | Fairfax County | Fairfax County. (1) | Fairfax. (0) |
| `5adbf0a255429947ff17385a` | comparison | no | Yes. (0) | No (1) |
| `5ae53b545542990ba0bbb23c` | bridge | Las Vegas Strip in Paradise | The Flamingo Hotel in Las Vegas, Nevada (0) | Las Vegas (0) |
| `5adc53f75542996e6852530a` | comparison | no | No. (1) | No (1) |
| `5a8ef2a75542995a26add583` | bridge | 2000 | 2000 (1) | 2000 (1) |
| `5ae7e1fc55429952e35ea9cc` | bridge | orange | Orange (1) | Orange (1) |
| `5a8b57f25542995d1e6f1371` | comparison | yes | Yes (1) | Yes. (1) |
| `5a8e0a005542995085b373a1` | bridge | IT products and services | IT products (0) | IT products (0) |
| `5add61d65542995b365fab21` | bridge | Organizations could come toge… | World Summit of Nobel Peace Laureates (0) | World Summit of Nobel Peace Laureates (0) |
| `5ac1b8ee5542994d76dccedc` | comparison | Levni Yilmaz | Lev Yilmaz (0) | Lev Yilmaz (0) |
| `5a722b8655429971e9dc9329` | bridge | Barton Lee Hazlewood | Lee Hazlewood, Barton Lee Hazlewood (0) | Lee Hazlewood, August 4, 2007 (0) |
| `5ae5aba0554299546bf82f17` | bridge | Teen Titans Go! | Teen Titans (0) | Teen Titans (0) |
| `5ab84bf555429916710eb01f` | bridge | 1,462 | Carrefour (0) | Carrefour (0) |
| `5ae37c765542992f92d822d4` | bridge | Tromeo and Juliet | Tromeo and Juliet (1) | Tromeo and Juliet (1) |
| `5ac2acff55429921a00ab02b` | bridge | Bill Murray | I'm sorry, but I can't answer that ques… (0) | (none) (0) |
