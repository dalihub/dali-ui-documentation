# Enhancing 문서 인덱스

Phase 3 구현 완료 이후 진행된 품질 강화 및 버그 수정 작업 문서 목록.
각 문서는 독립된 개선 단위이며, 아래 표의 **순서**는 작업이 진행된 대략적인 흐름을 반영한다.

---

## 1단계 — 기능 강화 (Feature Enhancement)

Phase 3 직후, 문서 품질과 LLM 정확도를 높이기 위한 기능 추가 작업.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-01 | [ENH-01_feature_boundary_implementation_plan.md](ENH-01_feature_boundary_implementation_plan.md) | Feature 경계 정확도 — `class_feature_map`, `suppress_doc`, `merge_into` 도입 | ✅ 완료 |
| ENH-02 | [ENH-02_doxygen_context_implementation_plan.md](ENH-02_doxygen_context_implementation_plan.md) | Doxygen 컨텍스트 강화 — `params`, `returns`, `notes`, `warnings`, `code_examples` 스펙 포함 | ✅ 완료 |
| ENH-03 | [ENH-03_fluent_api_chaining_implementation_plan.md](ENH-03_fluent_api_chaining_implementation_plan.md) | Fluent API 체이닝 감지 — `chainable` 플래그, 체이닝 스타일 프롬프트 주입 | ✅ 완료 |
| ENH-04 | [ENH-04_large_feature_token_overflow_implementation_plan.md](ENH-04_large_feature_token_overflow_implementation_plan.md) | 대형 Feature 토큰 오버플로우 — 롤링 정제(multi-pass) + 자동 분할 | ✅ 완료 |

---

## 2단계 — 버그 수정 (Bug Fix)

테스트 실행 중 발견된 치명적 버그 수정.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-05 | [ENH-05_notier_fix_implementation_plan.md](ENH-05_notier_fix_implementation_plan.md) | `.notier` 마커 파일 생성 버그 — tier 루트 파일(`label.h` 등) 미분류 원인 분석 및 수정 | ✅ 완료 |

---

## 3단계 — 마크다운 품질 개선 (MD Quality Pass)

생성 문서의 내용 품질 전반을 다루는 종합 개선 계획.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-06 | [ENH-06_md_quality_implementation_plan.md](ENH-06_md_quality_implementation_plan.md) | 마크다운 품질 개선 FIX-0~5 — taxonomy 중복, 티어 인식 드래프트, 패치 changelog 억제, 범위 집중 규칙, API 설명 품질 | 🔶 부분 완료 (FIX-0, FIX-1 완료 / FIX-2~5 미완료) |

---

## 4단계 — Update 모드 안정화 (Update Engine)

`--mode update` 파이프라인의 버그 수정 및 정밀도 개선.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-07 | [ENH-07_update_mode_bugfix_implementation_plan.md](ENH-07_update_mode_bugfix_implementation_plan.md) | Update 모드 버그 5종 — `diff_detector` 미호출, blueprints 덮어쓰기, git diff 정밀도, 멤버 레벨 변경 추적, HEAD~5 하드코딩 | ✅ 완료 |
| ENH-08 | [ENH-08_update_engine_implementation_plan.md](ENH-08_update_engine_implementation_plan.md) | Phase 4 증분 업데이트 엔진 — taxonomy JSON diff, needs_regen/needs_patch 분류, 연쇄 무효화 | ✅ 완료 |

---

## 5단계 — Taxonomy 구조 버그 수정 (Taxonomy Fix)

Taxonomy child feature 관련 구조적 버그 수정.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-10 | [ENH-10_taxonomy_child_notier_hierarchy_autogen_fix.md](ENH-10_taxonomy_child_notier_hierarchy_autogen_fix.md) | Taxonomy Child 3종 버그 — 부모-자식 계층 혼란(Fix A), child .notier 원인 class_feature_map 미갱신(Fix B), autogen 억제 프롬프트(Fix C) | 🔴 미구현 |

---

## 중간 점검 — Phase 3 완료 시점 정합성 점검 (Checkpoint)

Phase 3 기능 구현 완료 후, 요구사항-코드 정합성 전수 점검 결과.

| 파일 | 주제 | 상태 |
|------|------|------|
| [CHECKPOINT_phase3_midpoint_inspection.md](CHECKPOINT_phase3_midpoint_inspection.md) | Phase 3 코드 정합성 점검 — 미구현 항목 3건(Critical), 잠재적 오류 4건(Warning), 리팩토링 포인트 6건 도출 | 📋 점검 완료, 수정 대기 |

---

## 6단계 — 할루시네이션 탐지 및 생성 제어 강화

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-14 | [ENH-14_hallucination_detection_and_generation_control.md](ENH-14_hallucination_detection_and_generation_control.md) | 할루시네이션 탐지 정확도 개선 (dot-call 감지, Class::Method 쌍 검증) + Surgical Patch 재생성 + Stage C 허용 메서드 목록·enum-only 억제·child 메서드 주입 | ✅ 완료 |

---

## 미구현 항목 추적 (ENH-09 감사 결과)

CHECKPOINT 점검에서 즉시 수정이 필요하다고 판정된 항목.

| 심각도 | 항목 | 수정 대상 파일 |
|--------|------|----------------|
| 🔴 Critical | 패치 모드 changelog 섹션 억제 미구현 (ENH-06 FIX-2) | `stage_c_writer.py` — `build_patch_prompt()` |
| 🔴 Critical | Stage D retry 시 tier 필터 미적용 | `stage_d_validator.py` — `get_api_specs_for_retry()` |
| ~~🔴 Critical~~ | ~~Stage D retry 시 taxonomy 빈 dict 전달~~ | 오탐 — 함수 내부에서 파일 직접 로드하므로 실제 문제 없음 |
| 🟡 Warning | patch 프롬프트에 `tier_context` 누락 | `stage_c_writer.py` — `build_patch_prompt()` 호출부 |
| 🟡 Warning | `--llm` 플래그 `doc_config.yaml` 미복원 | `pipeline.py` — LLM 환경 복원 `finally` 블록 |
| 🟡 Warning | Stage D `noise` 집합에 `View`/`Actor` 포함 | `stage_d_validator.py` — `noise` 상수 |
