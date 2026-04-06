# Large Feature 토큰 오버플로우 해결 구현 계획

## 1. 문제 정의

### 1.1 발생 현상

Stage C (`stage_c_writer.py`)에서 `get_api_specs()`가 feature에 속한 모든 클래스의 모든 멤버를 수집하여 LLM 프롬프트에 통째로 주입한다. 일부 대규모 feature에서 스펙 수가 폭발적으로 증가하면서 사내 LLM의 최대 컨텍스트(131,072 tokens)를 초과하는 오류가 발생한다.

| Feature | 스펙 수 | 추정 토큰 | 사내 LLM | Gemini free tier |
|---|---|---|---|---|
| `addons` | 10,704개 | ~884,966 | ❌ 컨텍스트 초과(131k) | ❌ 분당 쿼터 초과(250k) |
| `actors` | ~4,000개 | ~400,000 | ❌ 컨텍스트 초과 | ❌ 분당 쿼터 초과 |
| `common` | ~2,981개 | ~300,000 | ❌ 컨텍스트 초과 | ❌ 분당 쿼터 초과 |
| 일반 Feature | < 500개 | < 50,000 | ✅ 정상 | ✅ 정상 |

Gemini free tier의 경우 분당 입력 토큰 한도가 250,000 tokens/min이므로, 단일 feature 프롬프트가 이를 초과하면 HTTP 429(RESOURCE_EXHAUSTED) 오류가 발생한다. 사내 LLM은 "컨텍스트 초과"로, Gemini free tier는 "분당 쿼터 초과"로 거절하는 방식이 다를 뿐 동일한 원인(프롬프트 토큰 폭발)이다.

### 1.2 기존 대응의 문제점

이전에는 `--limit 40` 옵션으로 스펙 수를 하드 커팅하여 처리했으나, 다음 문제가 발생했다:
- 뒷순서 스펙이 무조건 누락되어 문서 커버리지 저하
- LLM이 누락된 API를 할루시네이션으로 채우려는 경향 증가
- 어떤 스펙이 잘렸는지 추적 불가

### 1.3 근본 원인 분석

두 가지 원인이 복합적으로 작용한다.

**원인 A — feature_clusterer의 디렉터리 기반 클러스터링 한계**
`feature_clusterer.py`는 단순히 API 디렉터리 구조를 기반으로 feature를 분류한다. `addons/` 같은 폴더 하나가 수십 개의 독립적인 서브시스템을 포함하더라도 하나의 feature로 묶인다.

**원인 B — 단일 LLM 호출로 전체 문서 생성 시도**
`actors` 처럼 논리적으로 하나의 문서로 유지해야 하는 feature도 스펙 수가 많으면 단일 호출로는 처리 불가능하다.

---

## 2. 해결 전략

두 원인에 각각 대응하는 이중 전략을 채택한다.

```
┌─────────────────────────────────────────────────────────┐
│              feature별 스펙 수 측정                       │
└──────────────────┬────────────────────┬─────────────────┘
                   │                    │
        ┌──────────▼──────────┐  ┌──────▼───────────────┐
        │ 전략 A: 서브 분할    │  │ 전략 B: 롤링 정제     │
        │ (분리 가능한 경우)   │  │ (하나로 유지해야 할 때)│
        │                     │  │                       │
        │ addons →            │  │ actors →              │
        │  addons-animation   │  │  Pass 1: 초안 생성    │
        │  addons-layout      │  │  Pass 2: 스펙 보강    │
        │  addons-effects     │  │  Pass N: 마지막 정제  │
        └─────────────────────┘  └───────────────────────┘
```

### 2.1 전략 A: Feature 서브 분할 (feature_clusterer.py 확장)

스펙 수가 임계값(`MAX_SPECS_PER_FEATURE`, 기본값 2,000개)을 초과하는 feature에 대해, 내부 네임스페이스/클래스 계층 기준으로 자동 서브 분할한다.

**분할 기준 우선순위:**
1. `Dali::Ui::ComponentName` 같은 네임스페이스 2단계 이하 클래스 그룹
2. 파일 경로의 서브디렉터리
3. 클래스 이름의 공통 접두어 (예: `Addon`, `AddonEvent`, `AddonButton` → `addon-core`, `addon-event`, `addon-button`)

분할된 서브 feature는 `feature_taxonomy.json`에 parent-children 관계로 등록되어 트리 문서 구조로 자동 처리된다.

### 2.2 전략 B: 롤링 정제 (stage_c_writer.py 확장)

전략 A를 적용해도 단일 feature가 토큰 예산을 초과하는 경우(예: `actors`처럼 하나로 묶어야 하는 feature), 여러 번의 LLM 호출로 단계적으로 문서를 완성한다.

```
Pass 1: specs[0] ~ specs[N]      → draft_v1  (초안 — 미완성 플레이스홀더 포함)
Pass 2: draft_v1 + specs[N+1]~M  → draft_v2  (보강 — 새 스펙 섹션 추가)
Pass 3: draft_v2 + specs[M+1]~Z  → draft_v3  (최종 정제 — 플레이스홀더 제거)
```

각 pass는 독립된 프롬프트 타입을 사용한다:
- **initial_prompt**: 전체 스펙을 다 못 받았음을 인지하고 초안 작성. 미처리 섹션에 `<!-- PENDING: ClassName -->` 마커 삽입
- **refine_prompt**: 기존 초안을 보존하면서 새 스펙에 해당하는 섹션만 보강
- **final_prompt**: 마지막 호출 — 모든 플레이스홀더 제거, conclusion 작성

---

## 3. 상세 구현 계획

### 3.1 전략 판단 로직 (공통)

두 전략 중 어떤 것을 쓸지는 스펙 수와 분할 가능성으로 판단한다.

```
스펙 수 > MAX_SPECS_PER_FEATURE?
  ↓ YES
클래스 그룹이 3개 이상이고 각자 독립 시나리오가 있는가?
  ↓ YES → 전략 A (서브 분할)
  ↓ NO  → 전략 B (롤링 정제)
```

이 판단은 **두 단계에 걸쳐** 이루어진다:

#### 단계 1 — `feature_clusterer.py` (정적 판단)

스펙 수 초과 여부와 **후보 서브 그룹 계산**만 수행한다. LLM 없이 순수 Python으로 처리한다.

- 각 feature의 클래스 이름을 네임스페이스 3번째 레벨(`Dali::Addon::Manager` → `Manager`) 또는 파일 경로 서브디렉터리 기준으로 그룹화
- 그룹 수 >= 3이면 `split_candidates` 목록과 함께 `oversized: true` 마킹
- 그룹 수 < 3이면 서브 분할 불가로 판단, `split_candidates: []`와 함께 `oversized: true` 마킹 → taxonomy_reviewer가 `oversized_single`로 직행 처리

```json
// feature_map.json에 추가되는 필드 예시
{
  "feature": "addons",
  "oversized": true,
  "total_spec_count": 10704,
  "split_candidates": [
    {"group_name": "addons-manager", "apis": ["Dali::Addon::Manager", ...]},
    {"group_name": "addons-event",   "apis": ["Dali::Addon::EventHandler", ...]},
    {"group_name": "addons-button",  "apis": ["Dali::Addon::Button", ...]}
  ]
}
```

#### 단계 2 — `taxonomy_reviewer.py` (LLM 판단)

`feature_clusterer`가 마킹한 `oversized: true` feature 중 `split_candidates`가 3개 이상인 것에 대해, Think LLM에게 **각 후보 그룹이 개발자 관점에서 독립적인 사용 시나리오를 갖는지** 판단을 요청한다.

- **YES (독립 시나리오 있음)** → `feature_taxonomy.json`에 parent-children tree 구조로 등록. 이후 stage_c가 각 서브 feature를 독립 문서로 생성
- **NO (독립 시나리오 없음)** → taxonomy에 `oversized_single: true` 마킹. stage_c가 롤링 정제 모드로 처리

`taxonomy_reviewer.py`는 이미 상속 계층에 대해 "독립 시나리오 3개 이상" 판단을 수행하고 있다(기존 tree/flat decision). 이번 변경은 **같은 판단을 네임스페이스 그룹에도 확장**하는 것이다.

```
feature_clusterer.py      taxonomy_reviewer.py       stage_c_writer.py
─────────────────────     ────────────────────────   ──────────────────────
스펙 수 카운팅          →  split_candidates 3개+      →  (각 sub-feature가
후보 그룹 계산             → LLM: 독립성 판단              이미 분리된 feature로
oversized 마킹             → tree 등록 OR                  처리됨)
                            oversized_single 마킹      →  oversized_single이면
                                                           롤링 정제 모드
```

### 3.2 전략 A 구현: feature_clusterer.py 수정

**추가 함수: `auto_split_large_feature()`**

```python
def auto_split_large_feature(feature_name, apis, all_compounds, max_specs):
    """
    스펙 수 초과 feature를 클래스 그룹 단위로 자동 서브 분할한다.
    반환: [{"sub_feature": "...", "apis": [...]}, ...]
    """
    # 1. 클래스 이름의 공통 접두어로 그룹화
    # 2. 그룹별 스펙 수 계산
    # 3. 각 그룹이 max_specs 이하가 되도록 분할
    # 4. 단독으로 너무 큰 그룹은 further split
```

**수정 위치:** `main()` 함수의 직렬화(Serialize) 직전, feature_map 순회 시 스펙 수 체크 후 자동 분할

**feature_taxonomy.json 자동 등록:**
- 원본 feature는 `tree_decision: "tree"`, `children: [sub1, sub2, ...]`로 등록
- 각 서브 feature는 `parent: original_feature`, `tree_decision: "leaf"`로 등록

### 3.3 전략 B 구현: stage_c_writer.py 수정

**추가 함수 3개:**

#### `chunk_specs_by_class(specs, token_budget)`
```python
def chunk_specs_by_class(specs, token_budget):
    """
    클래스 단위로 묶어서 청크 분할.
    같은 클래스의 메서드가 두 청크에 걸치지 않도록 보장.
    """
```

#### `estimate_prompt_tokens(text)`
```python
def estimate_prompt_tokens(text):
    """
    LLM 호출 전 프롬프트 토큰 수를 추정한다.
    근사값: len(json_string) / 3.5
    """
```

#### `run_rolling_refinement(feat_name, outline, specs, client, ...)`
```python
def run_rolling_refinement(feat_name, outline, specs, client, 
                            taxonomy_context, view_context, tier_context):
    """
    토큰 예산 초과 feature에 대해 다중 Pass로 문서를 점진적으로 생성한다.
    """
    CONTEXT_LIMIT = 120_000   # 사내 LLM 131,072에서 안전 마진 적용
    PROMPT_OVERHEAD = 4_000   # 프롬프트 고정 텍스트 토큰 추정치
    
    chunks = chunk_specs_by_class(specs, initial_budget)
    
    # Pass 1: 초안 생성
    draft = client.generate(build_initial_prompt(...))
    
    # Pass N+1: 점진적 보강
    for i, chunk in enumerate(chunks[1:]):
        is_last = (i == len(chunks) - 2)
        draft_tokens = estimate_prompt_tokens(draft)
        remaining_budget = CONTEXT_LIMIT - PROMPT_OVERHEAD - draft_tokens
        
        # 드래프트 성장으로 여유 공간이 줄어든 경우 청크 재분할
        if remaining_budget < estimate_prompt_tokens(chunk):
            chunk = chunk_specs_by_class(chunk, remaining_budget * 0.8)[0]
        
        draft = client.generate(build_refine_prompt(feat_name, draft, chunk, is_last))
    
    return draft
```

**`main()` 수정 포인트:**
```python
# 기존 코드 (단일 호출)
specs = get_api_specs(packages, api_names, allowed_tiers)
prompt = f"... {json.dumps(specs, indent=2)} ..."
response_md = client.generate(prompt, use_think=False)

# 변경 후 (토큰 체크 후 분기)
specs = get_api_specs(packages, api_names, allowed_tiers)
estimated_tokens = estimate_prompt_tokens(json.dumps(specs))

if estimated_tokens > TOKEN_THRESHOLD:
    print(f"    [!] 스펙 토큰 {estimated_tokens:,} — 롤링 정제 모드 전환")
    clean_md = run_rolling_refinement(feat_name, outline, specs, client, ...)
else:
    prompt = build_full_prompt(...)
    clean_md = strip_markdown_wrapping(client.generate(prompt))
```

---

## 4. 변경 파일 및 영향도

| 파일 | 변경 유형 | 영향 범위 |
|---|---|---|
| `config/doc_config.yaml` | 설정 추가 | `token_overflow` 섹션 추가 |
| `src/01_cluster/feature_clusterer.py` | 기능 추가 | 스펙 수 카운팅, `oversized` 마킹, 후보 그룹 계산 추가 |
| `src/01_cluster/taxonomy_reviewer.py` | 기능 추가 | oversized feature 독립성 LLM 판단 로직 추가 |
| `src/02_llm/stage_c_writer.py` | 기능 추가 | `chunk_specs_by_class()`, `estimate_prompt_tokens()`, `run_rolling_refinement()` 추가, `main()` 분기 수정 |
| `cache/feature_map/feature_map.json` | 런타임 재생성 | oversized feature에 `split_candidates` 필드 추가 |
| `cache/feature_taxonomy/feature_taxonomy.json` | 런타임 재생성 | 서브 분할 feature는 tree 구조로, 단일 유지 feature는 `oversized_single: true`로 등록 |
| `src/02_llm/stage_b_mapper.py` | 변경 없음 | — |
| `src/02_llm/stage_a_classifier.py` | 변경 없음 | — |
| `src/pipeline.py` | 변경 없음 | feature_clusterer 재실행 시 자동 반영 |

### 4.1 하위 호환성

- 기존에 정상 동작하던 feature(스펙 수 < 임계값)는 코드 경로가 동일하게 유지되어 영향 없음
- `--limit` 옵션은 그대로 유지 (디버그/테스트용)
- 기존 생성된 마크다운 캐시는 영향 없음

### 4.2 파이프라인 실행 순서 변화

```
기존: feature_clusterer → stage_b → stage_c (단일 호출)

변경:
  feature_clusterer (서브 분할 포함)
    ↓
  stage_b (서브 feature별 outline 생성)
    ↓
  stage_c
    ├── 정상 feature     → 단일 LLM 호출 (기존과 동일)
    └── 대규모 feature   → 롤링 정제 (다중 LLM 호출)
```

---

## 5. 설정값 및 임계값

`config/doc_config.yaml`에 다음 항목을 추가한다:

```yaml
token_overflow:
  # feature_clusterer: 이 수치 초과 시 서브 분할 시도
  max_specs_per_feature: 2000

  # stage_c_writer: 이 토큰 수 초과 시 롤링 정제 모드
  spec_token_threshold: 60000

  # 사내 LLM 컨텍스트 한도 (안전 마진 포함)
  context_limit: 120000

  # 프롬프트 고정 텍스트 토큰 추정치
  prompt_overhead: 4000
```

---

## 6. 리스크 및 대응

| 리스크 | 가능성 | 대응 |
|---|---|---|
| refine pass가 기존 내용을 조용히 덮어씀 | 중간 | refine_prompt에 "기존 내용 수정 금지" 규칙 명시, Stage D에서 diff 검증 |
| 드래프트가 너무 커져서 후반 pass에 스펙 공간 부족 | 낮음 | 동적 청크 재분할 로직으로 대응 |
| `<!-- PENDING -->` 마커를 LLM이 임의로 제거 | 낮음 | 마커 잔류 여부를 Stage D 정적 검증에서 체크 |
| 서브 분할 후 feature 간 내용 중복 | 중간 | parent overview 페이지에서 중복 억제 규칙 (taxonomy_context 기존 로직 활용) |
| 롤링 정제 시 LLM 호출 횟수 증가로 비용/시간 상승 | 중간 | 임계값 이상인 feature만 해당. 주간 업데이트에서는 변경된 feature만 처리하므로 실제 발생 빈도 낮음 |

---

## 7. 구현 단계

| 단계 | 작업 | 담당 파일 |
|---|---|---|
| Step 1 | `doc_config.yaml`에 `token_overflow` 설정 추가 | `config/doc_config.yaml` |
| Step 2 | `feature_clusterer.py`에 스펙 수 카운팅 + `oversized` 마킹 + 후보 그룹 계산 추가 | `feature_clusterer.py` |
| Step 3 | `taxonomy_reviewer.py`에 oversized feature 독립성 LLM 판단 추가 | `taxonomy_reviewer.py` |
| Step 4 | `stage_c_writer.py`에 `estimate_prompt_tokens()`, `chunk_specs_by_class()`, `run_rolling_refinement()` 추가 | `stage_c_writer.py` |
| Step 5 | `stage_c_writer.py` `main()`에 단일 호출 / 롤링 정제 분기 추가 | `stage_c_writer.py` |
| Step 6 | E2E 테스트: `actors` (전략 B), `addons` (전략 A+B 복합) | — |

Step 4~5(stage_c 롤링 정제)는 Step 2~3(oversized 마킹)과 독립적으로 먼저 배포 가능하다. taxonomy에 `oversized_single: true`가 없어도 토큰 추정값 기반으로 자동 전환되도록 fallback을 둔다.

---

## 8. 검증 기준

- [ ] `actors` feature가 토큰 오류 없이 단일 `.md` 파일로 생성됨
- [ ] 생성된 문서에 `<!-- PENDING -->` 마커가 남아 있지 않음
- [ ] `addons` feature가 서브 feature 목록으로 분할되고 각각 문서 생성됨
- [ ] 기존 소규모 feature(예: `animation`, `label`)는 코드 경로 변화 없이 기존과 동일하게 동작함
- [ ] 롤링 정제 완료 문서가 단일 호출 문서와 유사한 섹션 구조를 가짐
