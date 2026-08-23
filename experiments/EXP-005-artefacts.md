# EXP-005 artefact manifest

라벨과 프롬프트는 저장소 밖에 있다 — 작업 산출물이고 제3자 제품명을 담는다.
그래서 저장소가 계보를 증명하지 못한다는 지적이 감사 F4 였다. 해시를 여기 남긴다.

기록 시각: 2026-08-23T04:07:37Z
위치: C:/Users/Admin/work/label/

| 파일 | 크기 | SHA-256 |
|---|---:|---|
| `matches-all.csv` | 135,924 | `6c68946173a4759863772eb25727f8a5f43a508e4ceeaf137bd986d48df73cc3` |
| `exp005/prompt-sku.txt` | 1,091 | `ad5b1c65acbfb1afd7d01fb7ba05e4de7aa6493bfcca34bc808be63200e79d64` |
| `exp005/prompt-line.txt` | 1,229 | `36aad72440eaca4f0e3598c85fa76e72b7280485234c5f762d2a963f840f1ec3` |
| `exp005/labelled-sku.csv` | 137,798 | `9fb81a9b78b86a3f4128bcd77ca862747b25efee0f0695cd2a463bfc591dbf4c` |
| `exp005/labelled-line.csv` | 137,801 | `206855920e2f90f16772182268ec8fc1572544907f44148d61df7ead7f5c649f` |
| `exp005/disagreement.csv` | 32,861 | `00cafc0fbd8ddf068cd842bf476eeeb9db386ae0dcbc2a56537cd9529777106c` |

라벨 생성: `claude -p --model sonnet`, 점수를 제거한 입력, 배치당 50쌍, 26배치.
`sonnet` alias 가 가리킨 immutable revision 은 고정하지 않았다 — 감사가 지적한 재현 한계다.
