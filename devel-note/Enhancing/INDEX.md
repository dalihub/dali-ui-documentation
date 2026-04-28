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

## 5단계 — Taxonomy 및 매핑 버그 수정 (Taxonomy & Mapping Fix)

Taxonomy child feature 관련 구조적 버그와 enum·impl 클래스 매핑 문제 수정.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-10 | [ENH-10_taxonomy_child_notier_hierarchy_autogen_fix.md](ENH-10_taxonomy_child_notier_hierarchy_autogen_fix.md) | Taxonomy Child 3종 버그 — 부모-자식 계층 혼란(Fix A), child .notier 원인 `class_feature_map` 미갱신(Fix B), autogen 억제 프롬프트(Fix C) | 🔴 미구현 |
| ENH-11 | [ENH-11_enum_only_feature_hallucination_fix.md](ENH-11_enum_only_feature_hallucination_fix.md) | Enum-only Feature 할루시네이션 — namespace compound의 enum memberdef를 synthetic compound로 추출, `feature_clusterer` 라우팅 수정 (`view-accessibility-enums` 등) | ✅ 완료 |
| ENH-12 | [ENH-12_integration_impl_class_feature_mapping_fix.md](ENH-12_integration_impl_class_feature_mapping_fix.md) | Integration::XxxImpl 클래스 remapping 오류 — `find_child_api_names()` startswith 조건 추가, Pass 2 substring 스캔으로 `AnimatedImageViewImpl::Property` 등 연관 compound 전파 | ✅ 완료 |
| ENH-13 | [ENH-13_taxonomy_tree_leaf_downgrade_fix.md](ENH-13_taxonomy_tree_leaf_downgrade_fix.md) | Taxonomy flat→tree→leaf 불일치 — `tree_decision="tree"` 이지만 `children=[]`인 모순 상태 및 `decision_reason`과 `parent` 불일치를 후처리 패스로 자동 교정 | ✅ 완료 |

---

## 중간 점검 — Phase 3 완료 시점 정합성 점검 (Checkpoint)

Phase 3 기능 구현 완료 후, 요구사항-코드 정합성 전수 점검 결과.

| 파일 | 주제 | 상태 |
|------|------|------|
| [CHECKPOINT_phase3_midpoint_inspection.md](CHECKPOINT_phase3_midpoint_inspection.md) | Phase 3 코드 정합성 점검 — 미구현 항목 3건(Critical), 잠재적 오류 4건(Warning), 리팩토링 포인트 6건 도출 | 📋 점검 완료, 수정 대기 |

---

## 6단계 — 할루시네이션 탐지 및 생성 제어 강화

Stage C/D 검증 정확도와 생성 품질을 종합적으로 개선하는 대규모 작업.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-14 | [ENH-14_hallucination_detection_and_generation_control.md](ENH-14_hallucination_detection_and_generation_control.md) | 할루시네이션 탐지 정확도 개선 (dot-call 감지, Class::Method 쌍 검증) + Surgical Patch 재생성 + Stage C 허용 메서드 목록·enum-only 억제·child 메서드 주입 | ✅ 완료 |
| ENH-15 | [ENH-15_tier_separated_blueprint.md](ENH-15_tier_separated_blueprint.md) | API Tier 기반 Blueprint 분리 — `stage_b_blueprints_app.json` / `stage_b_blueprints_platform.json` 분리 생성, Stage B/C/D에서 `--tier` 기반 동적 파일 로드 | ✅ 완료 |

---

## 7단계 — 완전 네임스페이스 API DB 및 2-Phase 코드 생성 개선

심볼 DB 정확도 향상과 Stage C 코드 생성 로직의 구조적 개선.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-16 | [ENH-16_fullns_api_db_and_twophase_codegen.md](ENH-16_fullns_api_db_and_twophase_codegen.md) | 완전 네임스페이스 기반 API DB 정확도 향상 및 2-Phase 샘플코드 생성 개선 — Phase 1: `doxygen_parser.py` 익명 enum 추출, `stage_d` pair_names 제거, Stage C 완전 네임스페이스 강제 / Phase 2: 자연어/샘플코드 2-Pass 분리, 블록 단위 Graceful Degradation | ✅ 완료 |

> **참고 문서 (Agent 세션 로그)**
>
> | 파일 | 내용 |
> |------|------|
> | [ENH-16_Agent.md](ENH-16_Agent.md) | Tier 기반 Blueprint 분리 계획 도출 과정 — LLM과의 대화 기록 (ENH-15 선행 작업) |
> | [ENH-16_Agent_2.md](ENH-16_Agent_2.md) | ENH-16 Phase 2 구현 계속 작업 — LLM과의 대화 기록 |

---

## 8단계 — 코드 생성 할루시네이션 감소 및 파이프라인 단순화

코드블럭 품질 규칙 추가, 파이프라인 구조 단순화, 프롬프트·코드 효율화.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-17 | [ENH-17_codegen_hallucination_reduction.md](ENH-17_codegen_hallucination_reduction.md) | 코드 생성 할루시네이션 감소 — Enum 인라인 제공(P1), 상속 메서드 DB 등록(P2), `&` 레퍼런스 파라미터 타입 캡처(P3), SetProperty 남용 억제(P4), Concept Index 도입(P5) | ✅ 완료 |
| ENH-18 | [ENH-18_inline_code_tag_and_pipeline_simplification.md](ENH-18_inline_code_tag_and_pipeline_simplification.md) | 인라인 코드 태그 시스템 및 파이프라인 단순화 — `SCREAMING_SNAKE_CASE` 규칙, `using namespace` 후처리 제거, 코드블럭 줄바꿈 강제, 백틱 인라인 태그 Pass 2 통합, Stage D→Stage C 흡수 | ✅ 완료 |
| ENH-19 | [ENH-19_prompt_and_code_efficiency.md](ENH-19_prompt_and_code_efficiency.md) | 프롬프트 토큰 및 코드 효율 개선 — `re.compile()` 모듈 상수화, spec 필드 `brief`+`signature`로 축소, `TERMINOLOGY OVERRIDE` 조건부 포함, `alias_leaf` 등록 제거 | ✅ 완료 |
| ENH-20 | [ENH-20_inline_code_params_and_postprocess_fix.md](ENH-20_inline_code_params_and_postprocess_fix.md) | 인라인 코드 파라미터 표시 및 postprocess regex 수정 — `_postprocess_markdown` trailing whitespace 매칭 버그 수정(`\n\s*````) + Pass 2 inline 출력에 파라미터 타입 포함(`SetPositionX(float)`) | ✅ 완료 |

---

## 9단계 — 심볼 DB 커버리지 및 최종 할루시네이션 수정

테스트 실행 로그 분석 기반 심볼 DB 보완과 잔여 환각 패턴 제거.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-21 | [ENH-21_symbol_db_and_hallucination_fixes.md](ENH-21_symbol_db_and_hallucination_fixes.md) | 심볼 DB 커버리지 및 할루시네이션 수정 — named nested enum 중간 레이어(일반 enum) 단축 심볼 등록(`AlphaFunction::EASE_IN_OUT`), symbol aliases 개선, pair-based validation 정확도 향상 | ✅ 완료 |
| ENH-22 | [ENH-22_validation_and_pass1_tag_compliance.md](ENH-22_validation_and_pass1_tag_compliance.md) | 검증 정확도 및 Pass 1 태그 준수 개선 — named enum 완전형 DB 등록(`AlphaFunction::BuiltinFunction::BOUNCE`), `absolute-layout` `View::SetLayout` 환각 억제, `feature_hints` 주입 기능 개선 | ✅ 완료 |
| ENH-23 | [ENH-23_uicolor_hallucination_and_pass2_hint_fix.md](ENH-23_uicolor_hallucination_and_pass2_hint_fix.md) | UiColor 프리셋 환각 차단 및 Pass 2 hint 전달 수정 — `UiColor::RED` 등 존재하지 않는 프리셋 전역 CONSTRAINT 추가(Pass 1/2 모두 적용), `feature_hint_block`이 Pass 2 retry에 미전달되던 호출 체인 버그 수정 | ✅ 완료 |

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

---

---

## 10단계 — Taxonomy Reviewer 트리 재설계

Feature 재구조화(분할/통합)와 전체 일괄 Taxonomy Tree 설계를 자동화하는 대규모 리팩터링.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-24 | [ENH-24_taxonomy_reviewer_tree_redesign.md](ENH-24_taxonomy_reviewer_tree_redesign.md) | Feature 재구조화 및 Taxonomy Tree 품질 개선 — Phase A oversized 분할·소규모 통합, Phase B LLM 1회 호출 2-depth 트리 생성, `stage_a` class_feature_map 재계산, `stage_b` Fix B 로직 제거 | ✅ 완료 |

---

## 11단계 — Taxonomy Tree 품질 및 문서 생성 품질 개선

트리 계층 품질과 LLM 문서 생성 품질을 함께 개선하는 연속 작업.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-25 | [ENH-25_taxonomy_tree_quality_and_tree_doc_generation.md](ENH-25_taxonomy_tree_quality_and_tree_doc_generation.md) | Taxonomy Tree 품질 및 Tree 문서 생성 개선 — Phase B 과도 계층화 억제 프롬프트, `_split_root` 기반 overview 분기 생성 | ✅ 완료 |
| ENH-26 | [ENH-26_doc_quality_improvements.md](ENH-26_doc_quality_improvements.md) | 문서 퀄리티 향상 5종 — Phase A-2 merge target brief 추가, stage_b TOC UI 주제 단위 재편, `typical_use_cases` 힌트 지원, stage_c 주의사항 Doxygen 근거 제약, 시그널 패턴 + `code_patterns` 주입 | ✅ 완료 |

---

## 12단계 — GitHub Actions Workflow 수정

CI/CD 파이프라인 정상화 및 runner 환경 분리.

| # | 파일 | 주제 | 구현 상태 |
|---|------|------|-----------|
| ENH-27 | [ENH-27_github_actions_workflow_fix.md](ENH-27_github_actions_workflow_fix.md) | Workflow 수정 4종 — `pip install` 누락(블로커), `e2e` INTERNAL_API_KEY secret 누락, `environment`별 runner 분기(internal→code-large / external→ubuntu-latest), 변경없음 시 PR skip | 🔴 미구현 |

---

## 전체 진행 현황 요약

| 단계 | 범위 | 상태 |
|------|------|------|
| 1단계 기능 강화 | ENH-01~04 | ✅ 전체 완료 |
| 2단계 버그 수정 | ENH-05 | ✅ 완료 |
| 3단계 MD 품질 개선 | ENH-06 | 🔶 부분 완료 (FIX-0,1만 완료) |
| 4단계 Update 모드 안정화 | ENH-07~08 | ✅ 전체 완료 |
| 5단계 Taxonomy 및 매핑 버그 | ENH-10~13 | 🔶 부분 완료 (ENH-10 미구현) |
| 중간 점검 | CHECKPOINT | 📋 점검 완료, 일부 수정 대기 |
| 6단계 할루시네이션 탐지·Blueprint 분리 | ENH-14~15 | ✅ 전체 완료 |
| 7단계 완전 NS API DB + 2-Phase 코드 생성 | ENH-16 | ✅ 완료 |
| 8단계 코드 생성 개선 및 파이프라인 단순화 | ENH-17~20 | ✅ 전체 완료 |
| 9단계 심볼 DB 커버리지 및 잔여 환각 수정 | ENH-21~23 | ✅ 전체 완료 |
| 10단계 Taxonomy Reviewer 트리 재설계 | ENH-24 | ✅ 완료 |
| 11단계 Taxonomy Tree 품질 및 문서 생성 품질 개선 | ENH-25~26 | ✅ 전체 완료 |
| 12단계 GitHub Actions Workflow 수정 | ENH-27 | 🔴 미구현 |
