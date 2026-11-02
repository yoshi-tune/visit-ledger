# 分析の報告の基準（docs/DESIGN.md §8 の「仕上がりの基準」）

- `/mnt/session/outputs/report.json` があり、`report_schema.json` の形に合っている
- `reconciliation` に、CSV から数え直した来店・来店未記録の件数と、`funnel.json` との一致・食い違いが書かれている
- `observations` のすべてに、分子・分母・集計の条件、根拠のスクリプトの名前（`step_NN`）が付いている。その名前のスクリプトが `/workspace/steps/` にある
- `first_view`（最初の見立て）と `revised_view`（集計を重ねた後の見立て）が書かれ、その間にどの集計で何が分かったかが `steps` に書かれている
- 観測（台帳の数字で言えること）・仮説（言い切らない）・追加で確かめること が分かれている。仮説を観測として書いていない
- 「来店未記録」を「来なかった」と書いていない。施策が来店を「生んだ」と書いていない。予算の配分を勧めていない
- `next_action` は店全体で1つで、手間・見る数字・比べる相手と期間・仮置きの目標が書かれている
- 名前・電話などの個人情報、仮の番号以外の識別子が出ていない
- 文章は日本語で、店長が読んで分かる言葉になっている
- 短く書かれている：検算が一致した時、`reconciliation.summary` は1〜2文で、`funnel.json` の数字を書き直していない（`differences` は本当の食い違いだけ。無ければ空）。`observations` は8件まで、`hypotheses` は3件まで、`to_check` は4件まで、`steps` は2〜4件。`finding`・`decision`・見立ては、それぞれ3文まで
