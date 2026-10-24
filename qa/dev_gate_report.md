# Dev gate

This file is written by `backend/tests/test_dev_gate.py`. The questions were hashed in `qa/DEV_GATE.sha256` before the gate was fit. The sealed conversations were not used to choose the threshold.

Dev set: 110 questions, 80 that the help center can answer, 26 absent topics, 4 constraint caveats.

Precision is correct quotes divided by quotes the gate was willing to state. Recall is correct quotes divided by questions the help center can answer. A false answer is a confident or hedged quote of the wrong section, a quote on an absent topic, or a quote that states a forbidden fact. A partial reply that says the section does not cover the constraint and hands off is not counted as an answer. The cap is 1% of dev questions.

A logistic regression on the same features (cross-encoder score, rank margin, RRF agreement, heading overlap, token overlap, cosine, and a duration flag) reached 48/80 correct with 1 false answer at its best point under that cap. The probabilities were compressed, so the shipped gate is the decision rule below, fit on this dev set.

| Gate | Precision | Recall | Correct | False answers | False-answer rate |
| --- | --- | --- | --- | --- | --- |
| Fixed cross-encoder cutoff | 95.6% | 53.8% | 43/80 | 2 | 1.8% |
| Calibrated decision rule | 100.0% | 65.0% | 52/80 | 0 | 0.0% |

Hedged replies among the dev questions: 1. A hedge quotes the section, says the match is uncertain, and offers a person. It counts as an answer in the table above, and the product metrics do not count it as a clean deflection.

## Rule

Answer when the cross-encoder score is at least 1, or when BM25 and dense search agree the section is in the top 3 and the margin, overlap, and score clear the fitted floors, or when the heading matches and those floors clear, or when a duration question lands on a passage that states a duration. Otherwise hedge only when the margin and overlap still show the section standing apart. Otherwise abstain.

## Misses

- `a002` level none article None: 
- `a003` level none article None: 
- `a004` level none article None: 
- `a005` level none article None: 
- `a006` level none article None: 
- `a007` level none article None: 
- `a009` level none article None: 
- `a011` level none article None: 
- `a012` level none article None: 
- `a013` level none article None: 
- `a015` level none article None: 
- `a018` level none article None: 
- `a021` level none article None: 
- `a023` level none article None: 
- `a026` level none article None: 
- `a031` level none article None: 
- `a032` level none article None: 
- `a035` level partial article return-window: The help center doesn't cover breakage. The closest section says: "Delivered orders can be returned within 30 days of the delivery date. The 30 days are counted
- `a037` level none article None: 
- `a039` level none article None: 
- `a042` level none article None: 
- `a044` level none article None: 
- `a053` level none article None: 
- `a056` level none article None: 
- `a061` level none article None: 
- `a062` level none article None: 
- `a065` level none article None: 
- `a078` level answer article pantry-subscription: Here is what the help center says. "Hale Pantry is a monthly or annual shipment of pantry staples. The monthly plan is $34 and the annual plan is $348." [Hale P

## False answers

- None.
