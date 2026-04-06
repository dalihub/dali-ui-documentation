# [Phase 4] Incremental Update 정밀 엔진 구현

## 배경 및 목표

이전 Phase까지는 `update` 모드가 **Draft 파일 존재 여부(파일명)**만 보고 변경을 판단했습니다.
이로 인해 구조 변경 감지가 불가능했고, 변경이 없는 문서까지 통째로 재생성되는 문제가 있었습니다.

이번 Phase에서는 아래 **3가지 원칙**을 정확히 구현하여 정밀 업데이트 엔진을 완성합니다.

---

## 구현 원칙 (3가지)

### 원칙 1. 비교 기준: 구 Taxonomy JSON ↔ 신 Taxonomy JSON

> [!IMPORTANT]
> 파일명 비교는 신규 추가 피처 탐지만 가능합니다. **구조 변경(Flat → Tree, children 추가 등)을 감지하려면 반드시 JSON 레벨 비교**가 필요합니다.

- `pipeline.py`가 `taxonomy_reviewer.py` 실행 **직전**에 기존 `feature_taxonomy.json`을 `feature_taxonomy.json.old`로 백업합니다.
- 신규 Taxonomy 생성 완료 후, 두 JSON을 피처 ID 단위로 순회하며 비교합니다.
- 비교 대상 필드: `children`, `parent`, `tree_decision`

---

### 원칙 2. Taxonomy 구조 변경 시 → 영향받는 부모까지 연쇄 삭제 후 전체 재생성

**트리거 조건**: `children`, `parent`, `tree_decision` 중 하나라도 구 ↔ 신 간에 다를 때.

**핵심 규칙 — 부모 연쇄 삭제(Cascade Invalidation)**:

신규 문서(`Doc3`)가 기존 문서(`Doc1`)의 `children`에 추가된 경우,
변경된 것은 `Doc3`만이 아니라 **`Doc1`의 구조도 바뀐 것**입니다.
따라서 `Doc1`의 기존 Draft도 **함께 삭제**하고 재생성해야 합니다.

```
삭제 대상 = {
  신규로 추가된 피처 (children에 처음 등장한 피처),
  그 피처를 자식으로 갖게 된 부모(parent) 피처,
  구조 관련 필드(children / parent / tree_decision)가 변경된 피처 본인
}
```

삭제 후 처리:
- 삭제된 피처 전체 → `needs_regen` 목록에 추가
- Stage B → Stage C → Stage D 순서로 `--mode full`과 동일하게 전체 재생성

---

### 원칙 3. Taxonomy 구조 동일 + API 추가/변경 시 → 기존 문서 최대 재사용 Patch

**트리거 조건**: Taxonomy 구조에는 변경이 없지만, `diff_detector.py`가 생성한 `changed_apis.json`에 해당 피처 관련 API가 포함된 경우.

**처리 방식 — Patch 모드 (`stage_c_writer.py --patch`)**:
- 기존 `validated_drafts/<feature>.md`를 LLM 컨텍스트에 **원본 그대로 주입**합니다.
- LLM에게 "변경된 API 스펙에 해당하는 부분만 수정하고, 나머지는 원문 그대로 출력"하도록 지시합니다.
- 결과적으로 **문체, 섹션 구성, 예제 코드 스타일이 최대한 보존**됩니다.

---

## 전체 분류 흐름 요약

| 감지 유형 | 조건 | 삭제 대상 | 처리 방식 |
|---|---|---|---|
| **신규 피처 추가** | 구 Taxonomy에 없던 피처 등장 | 해당 피처 + **부모 피처** Draft 삭제 | Stage B+C+D **전체 재생성** |
| **구조 변경** | `children` / `parent` / `tree_decision` 필드 변경 | 해당 피처 + **부모 피처** Draft 삭제 | Stage B+C+D **전체 재생성** |
| **피처 삭제** | 신 Taxonomy에서 사라진 피처 | 해당 피처 Draft 삭제 | 로그 기록 후 종료 |
| **API 변경 (구조 동일)** | `changed_apis.json` 포함, Taxonomy 구조 동일 | 삭제 없음 | `stage_c --patch` 부분 패치 |
| **변경 없음** | 위 조건 모두 해당 없음 | 없음 | **LLM 호출 0건 (전체 스킵)** |

> [!NOTE]
> `needs_regen`과 `needs_patch`는 상호 배타적입니다.
> 동일 피처가 구조 변경과 API 변경을 동시에 겪으면 **`needs_regen`이 우선** 적용됩니다.

---

## Proposed Changes

---

### Component 1: 파이프라인 제어부

#### [MODIFY] [pipeline.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/pipeline.py)

**❶ Taxonomy 백업**

`taxonomy_reviewer.py` 실행 직전, 기존 파일을 백업합니다.

```python
taxonomy_path = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"
taxonomy_old_path = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json.old"

if taxonomy_path.exists():
    shutil.copy2(taxonomy_path, taxonomy_old_path)
    print("  [*] Backed up existing taxonomy to feature_taxonomy.json.old")
```

**❷ Taxonomy Diff (구 ↔ 신 JSON 비교)**

```python
STRUCTURAL_KEYS = {"children", "parent", "tree_decision"}

needs_regen = set()
needs_patch  = set()

old_tax = load_json(taxonomy_old_path) or {}
new_tax = load_json(taxonomy_path)     or {}

# 2-a. 신규 추가된 피처 탐지 → 해당 피처 + 부모 피처 삭제 대상
for feat_id in new_tax:
    if feat_id not in old_tax:
        needs_regen.add(feat_id)
        parent = new_tax[feat_id].get("parent")
        if parent:
            needs_regen.add(parent)   # 원칙 2: 부모 연쇄 삭제

# 2-b. 구조 변경 탐지 → 해당 피처 + 부모 피처 삭제 대상
for feat_id in new_tax:
    if feat_id in old_tax:
        if any(old_tax[feat_id].get(k) != new_tax[feat_id].get(k) for k in STRUCTURAL_KEYS):
            needs_regen.add(feat_id)
            parent = new_tax[feat_id].get("parent")
            if parent:
                needs_regen.add(parent)   # 원칙 2: 부모 연쇄 삭제

# 2-c. 삭제된 피처 처리
for feat_id in old_tax:
    if feat_id not in new_tax:
        (drafts_dir / f"{feat_id}.md").unlink(missing_ok=True)
        print(f"  [-] Removed obsolete draft: {feat_id}")
```

**❸ needs_regen Draft 파일 삭제**

```python
for feat_id in needs_regen:
    draft_file = drafts_dir / f"{feat_id}.md"
    if draft_file.exists():
        draft_file.unlink()
        print(f"  [!] Invalidated draft: {feat_id}")
```

**❹ needs_patch 분류 (원칙 3)**

```python
changed_apis_path = CACHE_DIR / "changed_apis.json"
if changed_apis_path.exists():
    changed_apis = load_json(changed_apis_path)
    # 패키지별 변경 API name set 통합
    changed_api_names = set()
    for pkg_apis in changed_apis.values():
        for api in pkg_apis:
            changed_api_names.add(api.get("name", ""))

    for feat_id, feat_data in new_tax.items():
        if feat_id in needs_regen:
            continue   # needs_regen 우선
        feat_apis = set(feat_data.get("apis", []))
        if feat_apis & changed_api_names:   # 교집합이 존재하면
            needs_patch.add(feat_id)
```

**❺ Stage 호출 분기**

```
needs_regen → stage_b (Blueprint 생성) → stage_c (전체 재작성) → stage_d (검증)
needs_patch  → stage_c --patch --patch-features <list> → stage_d (검증)
둘 다 없으면 → 전체 LLM 스킵, Phase 3 렌더링만 수행
```

---

### Component 2: LLM 패치 모드

#### [MODIFY] [stage_c_writer.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/02_llm/stage_c_writer.py)

**추가 옵션**:

| 옵션 | 설명 |
|---|---|
| `--patch` | 패치 모드 활성화 플래그 |
| `--patch-features` | 쉼표 구분 패치 대상 피처 목록 |

**패치 모드 동작 로직**:

```python
if args.patch:
    # 1. validated_drafts에서 기존 문서 읽기
    existing_draft_path = VALIDATED_DRAFTS_DIR / f"{feat_name}.md"
    existing_draft = existing_draft_path.read_text(encoding="utf-8") if existing_draft_path.exists() else ""

    # 2. changed_apis.json에서 이 피처 관련 변경 API만 필터링
    changed_specs = get_changed_api_specs(feat_name, new_tax, changed_apis)

    # 3. Patching Prompt 사용
    prompt = build_patch_prompt(existing_draft, changed_specs)
else:
    # 기존 Full 생성 Prompt 사용 (변경 없음)
    prompt = build_full_prompt(...)
```

**Patching Prompt 규칙**:

```
[기존 이미 배포된 가이드 문서]
<기존 마크다운 본문 전체>

[최신 소스 코드 기준, 이 문서와 관련된 변경된 API 스펙]
<filtered changed API specs>

작성 규칙:
- 기존 문서의 섹션 구성, 문체, 예제 코드 스타일을 최대한 그대로 유지하라.
- 변경된 API 스펙에 관련된 부분(해당 API를 설명하는 섹션, 예제)만 수정하라.
- 변경된 API와 무관한 기존 내용, 예제, 설명은 절대 건드리지 말라.
- 새로운 API는 가장 적절한 섹션에 삽입하고, 삭제된 API는 관련 설명을 제거하라.
- 출력은 완성된 마크다운 전체를 그대로 내보낼 것 (섹션 일부만 출력하지 말 것).
```

---

### Component 3: CI/CD 캐시 보존

#### [MODIFY] [.github/workflows/weekly-update.yml](file:///home/bshsqa/Shared/DALi/dali-guide/.github/workflows/weekly-update.yml)

다음 실행에서 Taxonomy Diff가 정상 동작하려면 이번 실행 결과를 리포지토리에 저장해야 합니다.

PR 생성 전, 아래 데이터를 `git add -f`로 강제 포함:

| 경로 | 목적 |
|---|---|
| `cache/feature_taxonomy/feature_taxonomy.json` | 다음 주 비교 기준 (이번 주 신규 Taxonomy) |
| `cache/validated_drafts/` | 다음 주 패치 원본 (이번 주 검증 완료 Draft) |
| `output/app-guide/`, `output/platform-guide/` | 최종 배포 산출물 |

> [!NOTE]
> `feature_taxonomy.json.old`는 **저장 불필요**. 실행 시작 시 저장된 `feature_taxonomy.json`을 `.old`로 복사 후 사용하는 1회성 파일이기 때문입니다.

---

## Open Questions

> [!WARNING]
> **API 변경 감지 민감도**: 현재 `diff_detector.py`는 **파일 단위** 변경을 감지합니다.
> 헤더 파일에서 주석 한 줄이 바뀌어도 해당 파일에 속한 모든 API가 "변경됨"으로 분류됩니다.
> 이 민감도(파일 단위)로 진행해도 괜찮을까요?
> 아니면 함수 시그니처 수준(추가/삭제/파라미터 변경 여부)으로 더 정밀하게 필터링해야 할까요?

---

## Verification Plan

### 검증 시나리오 (run_extract_all.sh HEAD~30 → HEAD 롤백 기반)

| 시나리오 | 설정 방법 | 기대 결과 |
|---|---|---|
| **케이스 1: 신규 child 피처 추가** | 신 Taxonomy에 child 피처 1개 수동 추가 | 신규 피처 + **부모 피처** 모두 `needs_regen` 분류, Draft 삭제 후 B+C+D 재생성 |
| **케이스 2: API 변경 (구조 동일)** | `.h` 파일 API brief 수동 수정 | 해당 피처만 `needs_patch` 분류, 나머지 문서 변경 없음 |
| **케이스 3: 피처 삭제** | 신 Taxonomy에서 피처 1개 제거 | 해당 Draft 파일 삭제, LLM 미호출 |
| **케이스 4: 변경 없음** | 소스/Taxonomy 모두 동일 | `needs_regen`, `needs_patch` 모두 비어 LLM 호출 0건 |

### Manual Verification
- **케이스 1 완료 후**: 부모 문서가 새 자식을 올바르게 언급하는지 직접 확인.
- **케이스 2 완료 후**: 패치된 문서의 인트로 섹션, 비관련 예제 코드가 원본 Draft와 동일한지 `diff`로 확인.
