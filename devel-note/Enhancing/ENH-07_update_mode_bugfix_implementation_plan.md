# Enhancing Update Mode — Implementation Plan

## 배경 및 목적

현재 `--mode update` 파이프라인에는 다음 두 가지 버그와 세 가지 설계 한계가 존재한다.

**버그**
1. `diff_detector.py`가 `pipeline.py`에서 호출되지 않아 `changed_apis.json`이 갱신되지 않음 → API 변경 감지(needs_patch) 전혀 동작하지 않음
2. needs_regen과 needs_patch가 동시에 발생할 때, Stage B가 `stage_b_blueprints.json`을 regen 대상만으로 덮어써 patch 대상의 blueprint가 사라짐 → patch 모드 silently 실패

**설계 한계**
3. 변경 감지를 git diff(파일 레벨)로 수행하여 라이선스 수정, `#include` 추가 등 API와 무관한 변경도 추적됨
4. `changed_apis.json`이 class 단위로만 기록되어 어떤 멤버가 바뀌었는지 Stage C 패치 프롬프트에 전달할 수 없음
5. diff 기준이 `HEAD~5`로 하드코딩되어 실제 마지막 파이프라인 실행 이후의 변경만 추적하지 못함

이 문서는 위 5가지 문제를 해결하기 위한 수정 계획을 기술한다.

---

## 수정 항목 개요

| ID | 문제 | 수정 파일 | 난이도 |
|----|------|-----------|--------|
| FIX-1 | diff 기준을 "마지막 실행 커밋"으로 변경 | `pipeline.py`, `diff_detector.py` | 낮음 |
| FIX-2 | git diff → parsed_doxygen JSON 비교로 교체 | `diff_detector.py` | 중간 |
| FIX-3 | `changed_apis.json` 포맷을 멤버 레벨로 확장 | `diff_detector.py`, `pipeline.py` | 중간 |
| FIX-4 | `pipeline.py`에 diff 실행 단계 추가 | `pipeline.py` | 낮음 |
| FIX-5 | Stage B blueprints merge 저장 | `stage_b_mapper.py` | 낮음 |

---

## FIX-1: diff 기준을 "마지막 실행 커밋"으로 변경

### 문제

`diff_detector.py`의 `--from-commit` 기본값이 `HEAD~5`로 하드코딩되어 있다.
파이프라인 실행 주기와 git 커밋 빈도가 다르면 정확한 범위를 추적하지 못한다.

### 해결 방법

`pipeline.py`가 실행 완료 시 각 repo의 현재 `HEAD` 커밋 해시를 `cache/last_run_commits.json`에 저장한다.
다음 `--mode update` 실행 시 이 파일을 읽어 `--from-commit` 인자로 사용한다.

### 변경 파일

**`pipeline.py`**
- 실행 완료 직전에 `save_last_run_commits()` 함수 호출
  - 각 repo 경로에서 `git rev-parse HEAD` 실행
  - 결과를 `cache/last_run_commits.json`에 저장
- `--mode update` 진입 시 `load_last_run_commits()`로 파일 로드
  - 파일이 없으면 fallback으로 `HEAD~5` 사용 (최초 실행 호환성)
  - 로드 성공 시 각 패키지별 커밋 해시를 diff_detector에 전달

**`diff_detector.py`**
- `--from-commit` 인자를 패키지별로 개별 지정할 수 있도록 인터페이스 변경
  - 기존: 단일 `--from-commit` 값이 전체 패키지에 적용
  - 변경: `--from-commits` JSON 문자열 인자 추가 (패키지별 커밋 지정)
  - 하위 호환: `--from-commit`이 있으면 기존 방식 그대로 동작

### 저장 포맷

```json
// cache/last_run_commits.json
{
  "dali-core":    "a1b2c3d4e5f6",
  "dali-adaptor": "b2c3d4e5f6a1",
  "dali-ui":      "c3d4e5f6a1b2",
  "saved_at":     "2026-04-02T10:00:00Z"
}
```

---

## FIX-2: git diff → parsed_doxygen JSON 비교로 교체

### 문제

현재 `diff_detector.py`는 git diff로 변경된 파일 경로를 추출한 후, `parsed_doxygen/*.json`과 파일명을 매칭한다.
이 방식은 **파일 내 어떤 줄이 바뀌었는지를 보지 않기 때문에** 다음 변경도 "API 변경"으로 오탐한다.

- 파일 최상단 라이선스 헤더 수정
- `#include` 추가/삭제
- 함수 내부 구현 주석 변경 (`//`, `/* */`)

반면 Doxygen이 파싱하는 정보(API 시그니처, `@brief`, `@param`, `@return`, `@note` 등)가 바뀔 때만 추적하고 싶다.

### 해결 방법

git diff를 통한 소스 파일 비교를 **parsed_doxygen JSON 비교로 교체**한다.

Doxygen parser는 소스 코드에서 API 관련 정보만 추출하여 JSON을 생성한다.
따라서 두 시점의 JSON을 비교하면 Doxygen에 영향을 주는 변경만 자동으로 필터링된다.

**동작 흐름**

```
[pipeline.py --mode update]
  1. doxygen_parser.py 실행 전에 기존 parsed_doxygen/*.json 백업
     cache/parsed_doxygen/dali-core.json → cache/parsed_doxygen/dali-core.json.old

  2. doxygen_parser.py 실행 → 새로운 parsed_doxygen/*.json 생성

  3. diff_detector.py 실행
     → *.json.old 와 *.json 을 compound/member 레벨로 비교
     → 변경/추가/삭제된 멤버 목록 추출
     → cache/changed_apis.json 저장
```

### 비교 로직

각 compound(class)에 대해 다음 필드를 비교한다:

- `brief` (클래스 설명 변경)
- `members[].name` (멤버 추가/삭제)
- `members[].brief` (멤버 설명 변경)
- `members[].signature` (파라미터/반환 타입 변경)
- `members[].params` (파라미터 설명 변경)
- `members[].returns` (반환값 설명 변경)
- `members[].notes`, `members[].warnings`, `members[].deprecated`

비교 대상에서 **제외**하는 필드:
- `file` (파일 경로는 내용 변경과 무관)
- `id` (Doxygen 내부 식별자)

### 변경 파일

**`pipeline.py`**
- `--mode update` 흐름에서 `doxygen_parser.py` 실행 직전에 JSON 백업 로직 추가

**`diff_detector.py`**
- 기존 git diff 기반 로직 제거
- `*.json.old` vs `*.json` 비교 로직으로 교체
- 비교 결과를 FIX-3의 새 포맷으로 저장

---

## FIX-3: changed_apis.json 포맷을 멤버 레벨로 확장

### 문제

현재 포맷은 변경된 클래스 이름만 기록한다.
Stage C 패치 프롬프트가 "이 클래스가 바뀌었다"는 것만 알고 **무엇이 바뀌었는지** 알 수 없어 정밀한 패치가 불가능하다.

### 새 포맷

```json
{
  "dali-core": [
    {
      "class": "Dali::Actor",
      "api_tier": "public-api",
      "class_brief_changed": false,
      "changed_members": [
        {
          "name": "SetPosition",
          "change_type": "modified",
          "old_brief": "Sets the position of the actor.",
          "new_brief": "Sets the position of the actor in world space.",
          "old_signature": "void SetPosition(float x, float y)",
          "new_signature": "void SetPosition(float x, float y, float z = 0.0f)"
        },
        {
          "name": "GetParent",
          "change_type": "added",
          "new_brief": "Returns the parent of this actor.",
          "new_signature": "Actor GetParent() const"
        }
      ],
      "removed_members": [
        { "name": "SetPositionInheritanceMode" }
      ]
    }
  ],
  "dali-adaptor": [],
  "dali-ui": []
}
```

`change_type` 값:
- `"modified"` — 기존 멤버의 시그니처 또는 Doxygen 주석 변경
- `"added"` — 신규 추가된 멤버
- `"removed"` — 삭제된 멤버 (`removed_members` 배열에 별도 기록)

### Stage C 패치 프롬프트 개선

`build_patch_prompt()`가 새 포맷을 받으면 다음과 같이 구체적인 지시를 포함할 수 있다:

```
[CHANGED API SPECIFICATIONS]
Class: Dali::Actor

Modified:
  - SetPosition: signature changed
      old: void SetPosition(float x, float y)
      new: void SetPosition(float x, float y, float z = 0.0f)
    brief updated: "...in world space" 추가

Added:
  - GetParent: Returns the parent of this actor.

Removed:
  - SetPositionInheritanceMode: 삭제됨 — 관련 설명 및 코드 예제 제거할 것
```

---

## FIX-4: pipeline.py에 diff 실행 단계 추가

### 문제

`pipeline.py`의 `--mode update` 흐름에서 `diff_detector.py`가 호출되지 않는다.
`changed_apis.json`이 갱신되지 않으므로 `compute_incremental_targets()`의 needs_patch 분류가 항상 빈 집합을 반환한다.

### 해결 방법

`pipeline.py`의 `--mode update` Phase 0에 다음 순서로 실행 추가:

```
[기존]
doxygen_parser.py
callgraph_parser.py
feature_clusterer.py

[변경 후]
# parsed_doxygen JSON 백업 (FIX-2용)
backup_parsed_doxygen()

doxygen_parser.py      ← 새 JSON 생성

# diff 실행 (새 JSON vs 백업 JSON 비교)
diff_detector.py       ← changed_apis.json 생성

callgraph_parser.py
feature_clusterer.py
```

`--mode full`에서는 diff_detector.py를 실행하지 않는다 (전체 재생성이므로 불필요).

---

## FIX-5: Stage B blueprints merge 저장

### 문제

`stage_b_mapper.py`를 `--features view`로 실행하면 `stage_b_blueprints.json`이 view 항목만으로 완전히 덮어써진다.
이후 Stage C가 `--patch --patch-features animation`으로 실행될 때 animation의 blueprint를 찾지 못해 패치가 silently 건너뛰어진다.

### 해결 방법

`stage_b_mapper.py`에서 `--features`로 일부 feature만 처리할 때, 저장 전에 기존 `stage_b_blueprints.json`을 로드하여 처리된 feature 항목만 교체(upsert)한 후 저장한다.

**변경 로직 (stage_b_mapper.py)**

```python
# 저장 시점 (기존)
with open(OUT_BLUEPRINTS_PATH, "w") as f:
    json.dump(feature_list, f)   # feature_list = 처리된 것만

# 저장 시점 (변경 후, --features 사용 시)
if args.features:
    # 기존 blueprints 로드
    existing = {}
    if OUT_BLUEPRINTS_PATH.exists():
        for item in json.load(open(OUT_BLUEPRINTS_PATH)):
            existing[item["feature"]] = item

    # 처리된 feature를 upsert
    for item in feature_list:
        existing[item["feature"]] = item

    merged = list(existing.values())
else:
    merged = feature_list

with open(OUT_BLUEPRINTS_PATH, "w") as f:
    json.dump(merged, f)
```

`--features` 미사용(전체 실행) 시에는 기존처럼 전체 덮어쓰기 유지.

---

## 수정 후 --mode update 전체 흐름

```
[Phase 0] 코드 추출
  1. repo_manager.py              — 최신 코드 pull
  2. doxygen_runner.py (×3)       — Doxygen XML 재생성
  backup_parsed_doxygen()         — 기존 JSON → *.json.old 백업  ← NEW
  3. doxygen_parser.py            — 새 JSON 생성
  4. diff_detector.py             — *.json.old vs *.json 비교 → changed_apis.json  ← NEW
  5. callgraph_parser.py
  6. feature_clusterer.py

[Phase 1] Taxonomy
  backup_taxonomy()               — feature_taxonomy.json → .old 백업 (기존)
  7. taxonomy_reviewer.py         — 새 taxonomy 생성

[Phase 2] 증분 분류
  compute_incremental_targets()
    → needs_regen: taxonomy 구조 변경된 feature
    → needs_patch: API/Doxygen 변경된 feature

  [needs_regen]
  8. stage_a_classifier.py
  9. stage_b_mapper.py --features <regen>   ← merge 저장으로 patch blueprint 보존 (FIX-5)
  10. stage_c_writer.py --features <regen>  — 전체 재작성
  11. stage_d_validator.py

  [needs_patch]
  12. stage_c_writer.py --patch --patch-features <patch>  — 기존 문서 보존+변경분만 업데이트
  13. stage_d_validator.py

[Phase 3] 렌더링
  14. md_renderer.py --tier <tier>
  15. sidebar_generator.py --tier <tier>

[완료]
  save_last_run_commits()         — 현재 HEAD 해시 저장  ← NEW
```

---

## 수정 대상 파일 및 작업 요약

| 파일 | 작업 내용 |
|------|-----------|
| `src/pipeline.py` | ① update 시 parsed_doxygen 백업 추가<br>② diff_detector.py 호출 추가<br>③ last_run_commits.json 저장/로드 로직 추가 |
| `src/00_extract/diff_detector.py` | ① git diff 로직 제거<br>② parsed_doxygen *.json.old vs *.json 비교 로직으로 교체<br>③ changed_apis.json 포맷을 멤버 레벨로 확장<br>④ --from-commits 패키지별 커밋 인자 추가 (last_run_commits 연동) |
| `src/02_llm/stage_b_mapper.py` | ① --features 사용 시 기존 blueprints.json upsert 저장으로 변경 |
| `src/02_llm/stage_c_writer.py` | ① build_patch_prompt()가 새 changed_apis.json 멤버 레벨 포맷을 받아 구체적 지시 생성하도록 개선 |

---

## 기대 효과

| 항목 | 수정 전 | 수정 후 |
|------|---------|---------|
| diff 기준 | 항상 최근 5커밋 | 마지막 파이프라인 실행 이후 변경분만 |
| 변경 감지 정밀도 | 파일 레벨 (라이선스/include 오탐 포함) | Doxygen 영향 변경만 (API 시그니처 + doc 주석) |
| changed_apis.json 상세도 | class 이름만 | 변경/추가/삭제된 멤버 상세 정보 포함 |
| needs_patch 동작 | 항상 비어있음 (diff_detector 미호출) | 정상 분류 및 실행 |
| regen+patch 동시 발생 | patch blueprint 소실 → silently 실패 | blueprints merge 저장으로 정상 동작 |
| patch 프롬프트 품질 | "이 클래스가 바뀌었다"만 전달 | 어떤 멤버가 어떻게 바뀌었는지 구체적 전달 |
