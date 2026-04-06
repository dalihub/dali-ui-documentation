# Phase 3 완료 시점 코드 정합성 감사 보고서

> **감사 시점:** Phase 3 기능 구현 완료 후, Enhancing 작업 반영 직후  
> **감사 목적:** 설계 문서·Enhancing 계획서와 실제 소스 코드 간 정합성 전수 점검  
> **감사 대상:** `dali-doc-gen/src/` 전체, `config/`, `.github/workflows/`

---

## 분석 범위

| 분류 | 파일 |
|------|------|
| 설계 문서 | `dali_doc_system_plan.md`, `dali_doc_system_dev_plan.md` |
| 품질 강화 계획 | `devel-note/Enhancing/` 내 8개 문서 (ENH-01~08) |
| 소스 코드 | `pipeline.py`, `stage_a~d`, `feature_clusterer.py`, `taxonomy_reviewer.py`, `llm_client.py`, `md_renderer.py`, `sidebar_generator.py` |
| 설정 파일 | `config/repo_config.yaml`, `config/doc_config.yaml` |

---

## [기능 구현 현황]

### Phase 1~3 핵심 파이프라인 — 구현 완료 ✅

| 기능 | 구현 위치 | 상태 |
|------|-----------|------|
| venv 자동 생성 및 재실행 | `pipeline.py:20-29` | ✅ |
| `--mode full/update` 분기 | `pipeline.py:305-375` | ✅ |
| `--tier app/platform/all` 처리 | `pipeline.py:295` | ✅ |
| `--features`, `--limit` 디버그 플래그 | `pipeline.py:228-232` | ✅ |
| taxonomy 백업 → `.old` → diff 비교 | `pipeline.py:287-289` | ✅ |
| needs_regen / needs_patch 분류 및 연쇄 무효화 | `pipeline.py:117-218` | ✅ |
| `last_run_commits.json` 저장 | `pipeline.py:68-103` | ✅ |

### Enhancing 요구사항 — 이미 병합 완료 ✅

**ENH-05: `.notier` 버그 (Fix 1 & Fix 2)**
- Fix 1: `feature_clusterer.py:94-98` — tier 루트 파일(`label.h` → `"label"`) 파일명 stem 반환으로 수정됨
- Fix 2: `stage_c_writer.py:252-256` — `"uncategorized_ambiguous_root"` 예외 조건 추가됨

**ENH-06 FIX-0: taxonomy children 중복 제거**
- `sanitize_children()` 함수 `taxonomy_reviewer.py:72-79`, 호출 2곳(line 256, 370) 모두 적용됨

**ENH-06 FIX-1: 티어 인식 드래프트 아키텍처**
- `stage_c_writer.py:425-426` — `OUT_DRAFTS_DIR / args.tier` 서브디렉토리 출력
- `stage_d_validator.py:320-321` — `DRAFTS_DIR / args.tier` / `OUT_VALIDATED_DIR / args.tier` 경로 사용

**ENH-03: Fluent API Chaining 플래그**
- `stage_c_writer.py:285-296` — `chainable: true` 플래그 탐지 로직
- `stage_c_writer.py:689-706` — 체이닝 스타일 지시 프롬프트 주입

**ENH-02: Doxygen 컨텍스트 강화**
- `stage_c_writer.py:274-284` — `params`, `returns`, `notes`, `warnings`, `code_examples` 필드 모두 스펙에 포함됨

**ENH-04: Large Feature 롤링 정제**
- `run_rolling_refinement()` `stage_c_writer.py:136-192`
- 동적 재분할 로직(sub-chunk) 포함: `stage_c_writer.py:174-183`
- 설정: `doc_config.yaml:19-31` (`token_overflow` 섹션)

**ENH-01: feature_hints 주입 및 suppress_doc / merge_into 처리**
- `doc_config.yaml:9-17` — `view` feature에 Fluent API `extra_context` 정의
- `stage_c_writer.py:708-713` — 프롬프트 블록 조립
- `stage_c_writer.py:604-608`, `633-673` — suppress_doc / merge_into 처리

**ENH-07/08: Update 모드 안정화**
- `pipeline.py:282` — `diff_detector.py` 호출 추가 (ENH-07 Bug 1 수정)
- `pipeline.py:68-103` — `last_run_commits.json` 기반 diff 기준점 (ENH-07 Bug 5 수정)
- `stage_c_writer.py:317-363` — `build_change_summary()` 멤버 레벨 변경 요약 (ENH-07 Bug 4 수정)

---

## [불일치 및 오류]

### 🔴 Critical — 즉시 수정 필요

#### C-1. ENH-06 FIX-2 미구현: 패치 모드 changelog 섹션 억제

**문서 요구:** `enhancing_md_quality_implementation_plan.md` FIX-2 — 패치 프롬프트에 `"Do NOT add a changelog or 'API Updates' section"` 금지 규칙 명시 필요.

**실제 코드:** `stage_c_writer.py:366-399` `build_patch_prompt()` STRICT PATCHING RULES에 해당 제약 없음. 전체 `src/` 디렉토리 Grep 결과 관련 문자열 부재 확인.

**영향:** 패치 모드 실행 시 LLM이 자의적으로 "API Updates" / "What Changed" 섹션을 삽입해 문서 구조가 오염됨.

**수정 위치:** `stage_c_writer.py` `build_patch_prompt()` — STRICT PATCHING RULES 블록에 아래 항목 추가:
```
- Do NOT add any new top-level section such as 'API Updates', 'Changelog',
  'What Changed', or 'What's New'. Modify content only within existing sections.
```

---

#### C-2. Stage D retry 시 tier 필터 미적용

**실제 코드:** `stage_d_validator.py:206-241` `get_api_specs_for_retry()`에 `allowed_tiers` 파라미터 없음.

`stage_c_writer.py`의 `get_api_specs()`는 `allowed_tiers` 파라미터로 정확히 tier 필터링하지만, stage_d의 retry용 동일 함수에는 이 필터가 없음. ENH-06 FIX-1로 tier-aware 아키텍처를 도입했음에도 retry 경로에서 구멍이 발생.

**영향:** FAIL 판정 문서를 재생성할 때 app-guide에 devel-api/integration-api 내용이 포함될 수 있음 — 설계 원칙 위반.

**수정 위치:** `stage_d_validator.py` `get_api_specs_for_retry()` — `allowed_tiers` 파라미터 추가, `regenerate_failed_document()` → `main()` 호출 체인으로 `args.tier` 전달.

---

#### ~~C-3. Stage D retry 시 taxonomy를 빈 dict로 전달~~ — 오탐 (실제 문제 없음)

**재확인 결과:** `regenerate_failed_document()` 내부 [line 254-258]에서 파라미터로 받은 `taxonomy`를 사용하지 않고, **파일 경로(`TAXONOMY_PATH`)에서 직접 다시 로드**하는 구조임.

```python
def regenerate_failed_document(feat_name, blueprint, taxonomy, unverified_set, client):
    tax = {}
    if TAXONOMY_PATH.exists():
        with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
            tax = json.load(f)   # ← 전달받은 taxonomy 파라미터는 무시됨
```

호출부에서 `{}`를 전달해도 함수 내부에서 파일을 직접 읽으므로 taxonomy context는 정상적으로 조립됨. 파라미터 시그니처가 misleading하지만 동작에는 문제 없음.

---

### 🟡 Warning — 조기 수정 권장

#### W-1. patch 프롬프트에 `tier_context` 누락

**실제 코드:** `stage_c_writer.py:597-600`

```python
prompt = build_patch_prompt(
    feat_name, existing_draft, specs, change_summary, taxonomy_context, view_context
    # tier_context 파라미터 없음
)
```

Full 생성 모드와 달리 patch 프롬프트에 `tier_context`가 전달되지 않음. 패치 수행 중 tier 경계를 초과한 내용이 삽입될 수 있음.

**수정:** `build_patch_prompt()` 시그니처에 `tier_context` 파라미터 추가 후 프롬프트에 포함.

---

#### W-2. `--llm` 플래그가 `doc_config.yaml`을 영구 변경 (복원 로직 없음)

**실제 코드:** `pipeline.py:241-253`

```python
if original_llm_env != args.llm:
    doc_config["llm_environment"] = args.llm
    yaml.dump(doc_config, ...)   # 파일에 영구 기록
    # ❌ 파이프라인 완료/실패 후 original 값 복원 로직 없음
```

파이프라인이 중간 실패 또는 `SIGINT`로 종료될 경우, `doc_config.yaml`의 `llm_environment`가 변경된 채로 남아 다음 실행 시 의도와 다른 LLM 환경으로 실행됨.

**수정:** `try/finally` 블록으로 파이프라인 종료 시 `original_llm_env` 복원 보장.

---

#### W-3. Stage D `noise` 집합에 핵심 DALi 클래스 포함

**실제 코드:** `stage_d_validator.py:114-116`

```python
noise = {'Include', 'Note', 'Warning', 'View', 'Actor', 'True', ...}
```

`'View'`와 `'Actor'`가 noise로 분류되어 심볼 검증에서 제외됨. `Dali::Ui::View`나 `Dali::Actor`의 단독 클래스명 참조가 검증 대상에서 빠지므로, DALi의 핵심 객체에 대한 할루시네이션이 통과될 수 있음.

**수정:** `noise`에서 `'View'`, `'Actor'` 제거. C++ 예약어 및 Markdown 메타 키워드만 유지.

---

#### W-4. `--dry-run` 플래그 — 설계 문서에 있으나 코드에 미구현

`dali_doc_system_plan.md` 및 `README.md`에 `--dry-run` 옵션 언급됨.
`pipeline.py:223-236` argparse에 해당 플래그 정의 없음. 전체 소스에 미구현 확인.

---

#### W-5. `--llm` 플래그 — README 미문서화

`pipeline.py:233-235`에 `--llm internal|external` 플래그가 구현됨.
`README.md`에 해당 플래그가 문서화되지 않아 운영자가 인지하지 못할 가능성 있음.

---

## [개선 제안]

### 즉시 수정 항목 (5건)

| 우선순위 | 항목 | 수정 파일 | 난이도 |
|----------|------|-----------|--------|
| 1 | C-1: `build_patch_prompt()`에 changelog 금지 규칙 1줄 추가 | `stage_c_writer.py` | 낮음 |
| 2 | C-2: `get_api_specs_for_retry()`에 `allowed_tiers` 파라미터 추가 | `stage_d_validator.py` | 낮음 |
| 3 | C-3: retry 호출부에 `taxonomy` 객체 전달 | `stage_d_validator.py` | 낮음 |
| 4 | W-1: `build_patch_prompt()` 호출부에 `tier_context` 추가 | `stage_c_writer.py` | 낮음 |
| 5 | W-3: `noise` 집합에서 `'View'`, `'Actor'` 제거 | `stage_d_validator.py` | 낮음 |

### 리팩토링 포인트 (향후)

**R-1. `get_api_specs` 중복 제거**

`stage_c_writer.py`의 `get_api_specs()`와 `stage_d_validator.py`의 `get_api_specs_for_retry()`가 동일한 Doxygen 조회 로직을 중복 구현. 공통 유틸리티 모듈(`src/utils/spec_loader.py` 등)로 추출하여 `allowed_tiers`, `class_feature_map` 지원 통합 권장.

**R-2. `strip_markdown_wrapping()` 중복 제거**

동일 함수가 `stage_c_writer.py:301-315`와 `stage_d_validator.py:181-192`에 독립적으로 존재. `llm_client.py`로 이동하거나 공통 유틸로 추출 권장.

**R-3. `--dry-run` 플래그 구현**

`pipeline.py`에 `--dry-run` argparse 추가, `run_script()` 내부에서 실행 프린트만 하고 `subprocess.check_call`을 건너뛰는 모드 구현. CI 설정 검증 및 파이프라인 디버깅에 유용.

**R-4. `--llm` 플래그 `try/finally` 복원 및 README 문서화**

W-2 수정(복원 보장) + W-5 수정(README 추가) 병행.

**R-5. Stage B 프롬프트 범위 집중 규칙 검토 (ENH-06 FIX-3 미완)**

Stage C에는 `taxonomy_context`/`tier_context`로 범위 제약이 있으나, Stage B(TOC 설계 단계)에도 동일한 규칙 적용 여부 확인 필요. Stage B에서 잘못된 범위의 섹션이 설계되면 Stage C에서도 이미 오염된 상태로 시작됨.

**R-6. External LLM 모델명 유효성 검증**

`doc_config.yaml:46` — `gemini-3.1-flash-lite-preview`. `llm_client.py`에 `verify_model()` 헬스체크 단계를 추가하여 실제 API 호출 전 모델 유효성을 확인하는 구조 고려.

---

## 최종 요약표

| 항목 | 심각도 | 상태 |
|------|--------|------|
| C-1: patch 모드 changelog 섹션 억제 미구현 (ENH-06 FIX-2) | 🔴 Critical | 즉시 수정 필요 |
| C-2: stage_d retry tier 필터 미적용 | 🔴 Critical | 즉시 수정 필요 |
| ~~C-3: stage_d retry taxonomy 빈 dict 전달~~ | ~~🔴 Critical~~ | 오탐 — 함수 내부에서 파일 직접 로드하므로 실제 문제 없음 |
| W-1: patch 프롬프트에 `tier_context` 누락 | 🟡 Warning | 조기 수정 권장 |
| W-2: `--llm` 플래그 doc_config.yaml 복원 미비 | 🟡 Warning | 조기 수정 권장 |
| W-3: stage_d noise에 `View`/`Actor` 포함 | 🟡 Warning | 조기 수정 권장 |
| W-4: `--dry-run` 플래그 미구현 | 🟡 Warning | 향후 개선 |
| W-5: `--llm` 플래그 README 미문서화 | 🟡 Warning | 향후 개선 |
| R-1: `get_api_specs` 중복 코드 | 🟢 Info | 리팩토링 |
| R-2: `strip_markdown_wrapping` 중복 | 🟢 Info | 리팩토링 |
| R-3: `--dry-run` 구현 | 🟢 Info | 리팩토링 |
| R-4: `--llm` 복원 + README 보완 | 🟢 Info | 리팩토링 |
| R-5: Stage B 프롬프트 범위 규칙 (FIX-3) | 🟢 Info | 리팩토링 |
| R-6: LLM 모델 유효성 검증 | 🟢 Info | 리팩토링 |
| ENH-01~05 전체, ENH-06 FIX-0/FIX-1, ENH-07/08 | ✅ 완료 | — |
