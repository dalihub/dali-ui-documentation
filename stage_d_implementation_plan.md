# Stage D — Hallucination Validator Implementation Plan

## 목표

생성된 Markdown 초안에서 **존재하지 않는 API 이름이 언급됐는지 자동으로 검증**하고,
통과/경고/실패 판정을 내린 뒤 통과 문서만 다음 단계(Phase 3 렌더링)로 넘기는 품질 게이트.

---

## 배경 / 문제

Stage C가 Markdown을 작성할 때 ANTI-HALLUCINATION 규칙을 프롬프트에 명시했지만,
LLM이 실제로 존재하지 않는 클래스·메서드 이름을 만들어내는 경우는 여전히 발생할 수 있습니다.
Stage D는 이를 정적으로 검출하는 마지막 안전망 레이어입니다.

---

## 동작 흐름

```
cache/markdown_drafts/*.md
         ↓
[Stage D] stage_d_validator.py
 1. Markdown에서 C++ 심볼 추출 (코드 블록 내 식별자)
 2. parsed_doxygen DB에서 심볼 존재 확인
 3. 검증 점수 산출 및 Pass/Warn/Fail 판정
 4. LLM 보조 검증 (Fail 문서만 선택적으로)
         ↓
cache/validation_report/stage_d_report.json   ← 전체 결과
cache/validated_drafts/  ← Pass/Warn 문서만 복사
```

---

## 검증 판정 기준

| 판정 | 기준 | 다음 단계 |
|---|---|---|
| **PASS** | 검출된 심볼의 ≥70%가 Doxygen DB에 실존 | validated_drafts/ 복사 |
| **WARN** | 50–69% 일치, 미확인 심볼이 일부 존재 | 복사하되 report에 경고 태깅 |
| **FAIL** | <50% 일치, 심각한 할루시네이션 의심 | 복사 불가, LLM 재검증 필요 |

---

## 제안 파일 구조

```
src/02_llm/stage_d_validator.py    [NEW]
cache/validation_report/
  └── stage_d_report.json          [생성]
cache/validated_drafts/            [생성]
  └── actors.md, ...               [PASS/WARN 문서]
```

---

## Proposed Changes

### [NEW] `src/02_llm/stage_d_validator.py`

핵심 로직:

**① C++ 심볼 추출기**
- Markdown의 코드 블록(` ``` `) 내용 파싱
- `Dali::`, `Ui::` 네임스페이스 패턴 및 `ClassName::MethodName` 형식의 심볼 추출
- 인라인 backtick(`` `ClassName` ``) 내의 식별자도 추출

**② Doxygen DB 조회**
- `cache/parsed_doxygen/*.json`을 로드해 전체 `compounds` + `members` 이름 집합 구축
- 추출된 각 심볼을 집합에서 fuzzy 포함 검색 (전체 네임스페이스 or 단순 이름 모두 허용)

**③ 점수 산출**
```python
score = verified_count / total_extracted_symbols
```

**④ 선택적 LLM 재검증 (FAIL 문서)**
- FAIL 판정 문서에 대해 LLM에게 구체적으로 "어느 심볼이 잘못됐는지" 지적하도록 요청
- 보고서에 LLM 코멘트 포함

**⑤ 결과 보고서 & 복사**
- `stage_d_report.json`: 문서별 score, verdict, flagged_symbols 목록
- `validated_drafts/`: PASS/WARN 파일만 복사

---

### `scripts/run_extract_all.sh` [MODIFY]

Stage C 이후, Stage E 이전에 Stage D 추가:

```bash
# Stage D: Hallucination 검증
python src/02_llm/stage_d_validator.py

# Stage E는 validated_drafts/ 기반으로 Index 생성
python src/03_render/index_generator.py
```

### `src/03_render/index_generator.py` [MODIFY]

- 입력 디렉터리를 `markdown_drafts/` → `validated_drafts/`로 변경
- 단, WARN 파일도 Index에 포함하되 경고 뱃지 표시

---

## Verification Plan

```bash
# 단독 실행 테스트
python src/02_llm/stage_d_validator.py

# 리포트 확인
cat cache/validation_report/stage_d_report.json | python3 -m json.tool | head -60

# validated_drafts 확인
ls cache/validated_drafts/
```

---

*작성: 2026-04-01 | 다음: 승인 후 즉시 구현 진행*
