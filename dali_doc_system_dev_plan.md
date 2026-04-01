# DALi Guide Documentation 자동 생성 시스템 — 개발 플랜

## 개요

`dali-core`, `dali-adaptor`, `dali-ui` 세 패키지의 C++ Doxygen 주석을 파싱하여,
AI(Think/Instruct 이중 모델)를 통해 앱 개발자용 및 Platform 개발자용 Markdown 가이드 문서를
자동 생성하는 파이프라인을 구축한다.

- 최초 1회 전체 문서 생성 → 이후 주간 diff 기반 자동 업데이트 (GitHub Actions)
- 사내 로컬 LLM API(OpenAI-compatible REST) 사용
- 출력: Frontmatter 포함 `.md` → Docusaurus 배포 + MCP 서버 반영
- 사내 시스템에서는 사내 AI 모델을 사용하지만, 사외에서 테스트 할 때에는 다른 AI 모델 사용 필요하므로 AI 모델을 쉽게 교체할 수 있도록 설계해야 함.

---

## 요구사항 및 비기능 요구사항 (FR/NFR)

### 기능 요구사항 (FR)
1. **문서 자동 생성**: Doxygen 주석과 C++ 코드를 기반으로 LLM을 활용해 가이드 문서를 자동 생성한다. (최초 1회 전체 생성, 이후 주간 업데이트)
2. **독자 타겟별 분리**: 
   - `app-guide`: 일반 앱 개발자가 사용하는 Public API 전용.
   - `platform-guide`: 사내 플랫폼 개발자가 사용하는 Public, Devel, Integration API 모두 포함.
3. **API 자동 클러스터링**: 파일/네임스페이스/호출 관계를 분석하여 연관 API들을 자동으로 Feature 단위로 묶는다.
4. **Taxonomy (Tree/Flat) 자동 설계**: 상속 관계를 분석하여 하위 클래스가 독립적인 시나리오를 가질 경우 부모-자식 트리 구조 문서로, 그렇지 않을 경우 단일 문서(Flat)로 LLM이 구조를 스스로 판단하여 설계한다.
5. **앱 관점의 컨텍스트 반영**: `Dali::Ui::View`와 `Dali::Actor`의 관계처럼, 앱 개발자에게 실질적으로 중요한 객체(View)를 중심으로 문서 비중과 예제 코드를 서술하도록 컨텍스트를 주입한다.
6. **내/외부 LLM 스위칭**: 설정 파일(`.env`, `doc_config.yaml`)을 통해 사내 프라이빗 LLM과 외부 상용 LLM을 스크립트 수정 없이 자유롭게 교체하여 사용할 수 있어야 한다.
7. **Anti-Hallucination 파이프라인**: 
   - 생성된 마크다운을 정적 DB와 대조하여 미존재/잘못된 클래스 지칭을 감지한다.
   - 검증 실패(FAIL) 시 LLM에게 에러 내역을 주입하여 스스로 자동 복구하는 Retry Loop를 지원한다.
8. **증분 업데이트 시 구조 변동 자동 감지**: 주간 업데이트 파이프라인 가동 시, 시스템이 신규 추가되거나 변경된 코드를 자동으로 감지해 Taxonomy를 재평가하며, 기존 구조에 새로운 자식 노드(Child)가 편입되거나 Flat 구조가 Tree 구조로 격상되는 등의 구조적 변경 상황을 사람의 개입 없이 스스로 파악해야 한다.
9. **심층적 가이드 문서 서술**: 최종 결과물은 단순한 API 나열을 넘어, 구체적인 API 사용 방법(Step-by-step 튜토리얼), 특수 기능(Edge Cases)에 대한 설명, 그리고 중요한 유의사항(`@warning` 등)들을 밀도 있게 포함해야 한다. (해당 퀄리티는 파이프라인 완성 후 Phase 4의 프롬프트 튜닝을 통해 극한으로 강화한다.)

### 비기능 요구사항 (NFR)
1. **토큰 리소스 최적화**: 원본 코드를 그대로 LLM에 넘기지 않고, 정적 파서를 통해 JSON 스펙으로 경량화(60~70% 절감)하여 전달한다.
2. **독립적 실행 환경**: 로컬 개발(CLI) 및 CI/CD(GitHub Actions) 환경 어디서든 독립 스크립트로 동작 가능해야 한다.
3. **고가용성 방어 로직**: 클라우드 LLM의 Rate Limit(429) 및 일시 장애(503) 등에 대비해, 설정 가능한 대기 시간(Delay) 및 Exponential Backoff 기반 자동 재시도 로직을 탑재하여 시스템 중단을 차단한다.
4. **무결성 기반 업데이트 (Invalidation)**: 주기적 업데이트 시, Taxonomy(상속/분류 구조) 변경이 감지된 Feature 그룹은 얽힌 구버전 문서를 일괄 삭제(Invalidate)하고 전체 그룹을 최초 생성 방식으로 다시 덮어써서 논리적 모순을 방지한다.
5. **독립성 유지**: 문서 작성 프로세스가 원본 C++ 라이브러리 코드베이스를 어떠한 형태로도 수정하거나 오염시켜서는 안 된다.

---

## 시스템 아키텍처 요약

```
입력(GitHub Repos)
  └── Stage 0: Doxygen XML 파싱 → 구조화 JSON + Feature 클러스터링  [LLM 없음]
        └── Phase 1.5: Feature Taxonomy 설계 (상속 Tree 구조 결정)  [Think]
              └── Stage A: 모호 API Feature 경계 분류                [Think]
                    └── Stage B: 전체 목차 + 시나리오 설계           [Think]
                          └── Stage C: Feature별 문서 초안 작성 (병렬) [Instruct]
                                └── Stage D: 정적 검증 + 논리 검토/수정 [Think]
                                      └── Stage E: MD 렌더링 → PR 생성 [LLM 없음]
```

---

## 프로젝트 디렉터리 구조

```
dali-doc-gen/
├── .github/workflows/
│   ├── weekly-update.yml
│   └── initial-full-gen.yml
├── config/
│   ├── repo_config.yaml       # 각 패키지 경로, 브랜치, API 폴더 목록, manual_features 주입
│   └── doc_config.yaml        # 문서 카테고리, 출력 경로, Frontmatter 기본값
├── src/
│   ├── 00_extract/
│   │   ├── repo_manager.py      # GitPython으로 GitHub 주소에서 코드 Clone 및 Pull
│   │   ├── doxygen_runner.py    # Doxyfile 자동 생성 및 Doxygen 실행
│   │   ├── doxygen_parser.py    # Doxygen XML → 구조화 JSON (상속관계 base_class/derived_classes 포함)
│   │   ├── callgraph_parser.py  # Call Graph XML → 호출관계 JSON
│   │   └── diff_detector.py     # Git diff → 변경 API 목록 추출
│   ├── 01_cluster/
│   │   ├── feature_clusterer.py # 네임스페이스 + CallGraph → Feature 그룹 + manual_features 강제 주입
│   │   └── taxonomy_reviewer.py # [NEW] LLM이 상속 계층 Tree 구조 여부 결정 → feature_taxonomy.json
│   ├── 02_llm/
│   │   ├── llm_client.py        # OpenAI-compatible REST 클라이언트 (retry/backoff)
│   │   ├── stage_a_classifier.py
│   │   ├── stage_b_planner.py
│   │   ├── stage_c_writer.py
│   │   └── stage_d_reviewer.py
│   ├── 03_render/
│   │   ├── md_renderer.py        # Jinja2 기반 Markdown + Frontmatter 렌더링
│   │   └── sidebar_generator.py  # Docusaurus sidebar.json 자동 생성
│   ├── validator.py              # 정적 검증: 문서 내 API 이름 → DB 대조
│   └── pipeline.py               # 전체 파이프라인 오케스트레이션
├── prompts/
│   ├── stage_a_prompt.md
│   ├── stage_b_prompt.md
│   ├── stage_c_prompt.md
│   └── stage_d_prompt.md
├── cache/
│   ├── doxygen_json/
│   ├── callgraph_json/
│   ├── feature_map/
│   └── toc/
├── output/
│   ├── app-guide/
│   └── platform-guide/
├── tests/
├── requirements.txt
└── scripts/
    ├── run_full.sh
    └── run_update.sh
```

---

## Phase별 개발 계획

### Phase 0 — 환경 설정 및 기반 구축 (1~2주)

**목표**: 개발 환경 준비, 각 도구 단독 동작 검증

| 작업 | 내용 |
|---|---|
| 의존성 정리 | `requirements.txt` 작성 (doxygen, gitpython, aiohttp, jinja2 등) |
| Config 파일 설계 | `llm_config.yaml`, `repo_config.yaml`, `doc_config.yaml` 초안 |
| Doxygen 실행 검증 | `doxygen_runner.py` 구현, dali-core 대상으로 XML+CallGraph 출력 확인 |
| LLM API 연동 테스트 | `llm_client.py` 구현, Think/Instruct 각각 ping 테스트 + 응답 파싱 |
| 디렉터리 초기화 | 프로젝트 뼈대(폴더 + 빈 파일) 생성 |

**산출물**: 실행 가능한 Doxygen XML 출력, LLM API 연동 확인

---

### Phase 1 — 정적 분석 파이프라인 구현 (2~3주)

**목표**: LLM 없이 API 데이터를 완전히 구조화된 JSON으로 변환

#### `repo_manager.py`
- `repo_config.yaml`에 명시된 원격 저장소(`url`)와 `branch` 정보를 참조
- 로컬 임시 폴더(예: `repos/`)에 저장소가 없으면 `git clone`, 이미 존재하면 `git pull` 실행
- CI/CD 봇이나 초기화된 환경에서도 코드를 자동 확보

#### `doxygen_parser.py`
- Doxygen `compound.xml` 파싱
- 추출 항목: `id`, `package`, `api_tier`, `brief`, `params`, `returns`, `notes`, `warnings`, `deprecated`, `since`
- 내부 ID·파일 오프셋 제거 → 토큰 절감 (약 60~70%)
- 출력: `cache/parsed_doxygen/{package}.json`

#### `callgraph_parser.py`
- Doxygen Call Graph XML에서 직접 호출 1단계만 추출
- `calls`, `called_by` 필드로 정리
- 출력: `cache/callgraph_json/{package}.json`

#### `diff_detector.py`
- `GitPython`으로 `git diff <prev_tag>..<current_tag>`
- 변경된 헤더 파일 → 영향 API 목록 반환
- 출력: `changed_apis.json`

#### `feature_clusterer.py`
- **1차**: 디렉터리/네임스페이스 기반 그룹핑
- **2차**: Call Graph에서 밀집 호출 관계 병합 (패키지 경계 무시)
- **manual_features 주입**: `repo_config.yaml`에서 강제 정의된 Feature(예: `view`) 삽입
- 모호 케이스 플래그 (`ambiguous: true`)
- 출력: `cache/feature_map/feature_map.json`

#### `taxonomy_reviewer.py` ← **[Phase 1.5 신규]**
- **목적**: 상속 계층 기반 Tree 문서 구조 여부를 LLM(Think)이 결정
- **입력**: `feature_map.json` + Doxygen에서 추출한 `base_class`/`derived_classes` 관계
- **LLM 판단 기준**:
  - 하위 클래스 ≥ 3개 + 각각 독립 시나리오 → Tree 구조 생성
  - 단순 변형이거나 앱 개발자 관점 구분 불필요 → Flat 유지
- **출력**: `cache/feature_taxonomy/feature_taxonomy.json` (영속화)
- **증분 업데이트**: `diff_detector` 감지 신규/변경 클래스만 LLM 재검토, 기존 taxonomy 재사용

```json
// feature_taxonomy.json 예시
{
  "view": {
    "display_name": "View (Base UI Object)",
    "parent": null,
    "children": ["image-view", "label", "scroll-view"],
    "doc_file": "view.md"
  },
  "image-view": { "parent": "view", "children": [], "doc_file": "image-view.md" }
}
```

#### View/Actor 아키텍처 반영 원칙
- 앱 개발자는 `Dali::Ui::View`를 기본 UI 객체로 사용 (`Dali::Actor` 직접 사용 없음)
- View는 Actor를 상속하므로, Stage B/C 프롬프트에서:
  - **View 문서**: View API 중심, Actor 특성은 배경 설명으로만
  - **Actor 문서**: 플랫폼 개발자 관점의 저수준 설명
  - **코드 예제**: 항상 `Dali::Ui::View` 기준

```json
// feature_map.json 예시
{
  "feature": "Actor Positioning & Transformation",
  "packages": ["dali-core"],
  "apis": ["Dali::Actor::SetPosition", "..."],
  "cross_package_links": ["dali-adaptor::RenderSurface"],
  "api_tiers": ["public-api"],
  "ambiguous": false
}
```

**산출물**: 전체 API → Feature 매핑 JSON, diff 기반 변경 목록

---

### Phase 2 — LLM 파이프라인 구현 (3~4주)

**목표**: 4단계 LLM 처리(A→B→C→D) 구현 및 프롬프트 설계

#### `stage_a_classifier.py` (Think 모델)
- 입력: `ambiguous=true` API 목록 + 후보 Feature 목록
- 출력: 각 API → Feature 소속 결정
- 호출 조건: 모호한 케이스만 (비용 최소화)

#### `stage_b_planner.py` (Think 모델)
- 입력: Feature 목록 + API brief 요약 JSON
- 출력: `cache/toc/toc_plan.json` (카테고리 구조, 학습 순서, Feature별 시나리오 2~3개)
- 호출 조건: 최초 1회 + 신규 Feature 발생 시만

#### `stage_c_writer.py` (Instruct 모델, 비동기 병렬)
- 입력: Feature의 API JSON + Stage B 시나리오
- 출력: Markdown 초안 (overview / API 레퍼런스 / 코드 스니펫 / 주의사항)
- `asyncio` + `aiohttp` 병렬 처리
- **프롬프트 규칙**: 제공된 API JSON 범위 외 언급 금지, `@warning`/`@note` 반드시 포함

#### `stage_d_validator.py` ✅ 구현 완료

**역할**: Hallucination Validation Engine — Stage C 출력 문서의 품질을 정적으로 검증하고, FAIL 문서는 자동으로 재생성합니다.

**동작 흐름**:
```
markdown_drafts/*.md
  ↓
[1] 심볼 추출: 코드 블록/인라인 backtick에서 C++ 클래스·메서드명 추출
  ↓
[2] Doxygen DB 대조: parsed_doxygen/*.json의 전체/단순 이름 집합과 비교
  ↓
[3] 판정 (PASS ≥60% / WARN ≥35% / FAIL <35% / LOW_CONTENT <3 symbols)
  ↓
[4] FAIL 문서 → Retry Loop (최대 2회):
    - Stage B blueprint + 할루시네이션 심볼 목록을 프롬프트에 주입
    - Stage C 수준으로 문서 재생성
    - 재검증 → PASS/WARN이면 validated_drafts/에 최종 저장
  ↓
validated_drafts/ (PASS/WARN만 포함)
cache/validation_report/stage_d_report.json (판정 + retry_attempts 기록)
```

**플래그**:
- `--no-retry`: Retry Loop 건너뜀 (빠른 테스트 시 사용)
- `--no-llm`: LLM 전체 비활성화 (정적 검증만 수행)

**산출물**: `validated_drafts/` (검증 통과 문서), `stage_d_report.json` (상세 리포트)


---

### Phase 3 — 렌더링 및 CI/CD 구성 (2주)

**목표**: 최종 Markdown 출력 + GitHub Actions 파이프라인

#### `md_renderer.py`
- Jinja2 템플릿 기반
- Frontmatter 자동 삽입 (`title`, `category`, `tier`, `packages`, `api_version`, `last_updated`)
- `app-guide/` / `platform-guide/` 분리 출력

#### `sidebar_generator.py`
- `output/` 디렉터리 스캔 → `sidebar.json` 자동 생성
- Docusaurus v3 호환 형식

#### GitHub Actions 및 파이프라인 업데이트 아키텍처

주기적 갱신 시(Phase 3), 구조 변경(Tree/Flat 전환 또는 Child 노드 증감) 여부에 따라 처리 방식을 달리하여 논리적 일관성을 유지합니다.

1. **Taxonomy Diff 기반 무효화 (Invalidation)**
   - `taxonomy_reviewer`가 비교한 결과, 상속 트리 구조나 분류 체계가 변동된 Feature는 기존 `.md` 문서를 일괄 삭제하고 **최초 생성(Full Generate)** 파이프라인을 태웁니다.
2. **일반 Update (Patch)**
   - 구조 변경이 없는 단순 API 추가/수정의 경우, `changed_apis.json`과 기존 `.md`를 LLM에 동시에 주입하여 **기존 문서 기반 Patch**를 수행합니다.

**`weekly-update.yml`**
```yaml
on:
  schedule:
    - cron: '0 2 * * 1'   # 매주 월요일 02:00 UTC
  workflow_dispatch:
jobs:
  update-docs:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - name: Run update pipeline
        run: python src/pipeline.py --mode update
      - uses: peter-evans/create-pull-request@v6
        with:
          title: "docs: Weekly auto-update"
          branch: "auto-docs/${{ env.DATE }}"
          labels: "documentation,auto-generated"
          reviewers: "doc-reviewers-team"
```

**`initial-full-gen.yml`**
```yaml
on:
  workflow_dispatch:
    inputs:
      target_tier:
        description: 'app | platform | all'
        default: 'all'
jobs:
  full-gen:
    runs-on: self-hosted
    steps:
      - run: python src/pipeline.py --mode full --tier ${{ inputs.target_tier }}
      - uses: peter-evans/create-pull-request@v6
```

**산출물**: 완성된 `output/app-guide/`, `output/platform-guide/` + PR 자동 생성

---

### Phase 4 — E2E 테스트 및 품질 개선 (2주)

**목표**: 전체 파이프라인 통합 테스트 수행 및 **프롬프트 집중 튜닝(Prompt Engineering)**을 통한 문서 품질 극대화

| 측정 항목 | 방법 |
|---|---|
| API 커버리지 | 전체 API DB 대비 문서화된 API 비율 자동 계산, 미커버 항목 리포트 |
| 할루시네이션율 | `validator.py`의 미존재 API 플래그 수 / 전체 API 언급 수 |
| 토큰 사용량 | 각 Stage별 실제 호출 토큰 로깅 |
| 프롬프트 집중 튜닝 | 할루시네이션 차단 및 내용 보강(풍부한 예제 코드, 특수 사용례, 단계별 설명 추가 등)을 위해 `prompts/*.md` 지시문을 반복 개선하여 문서 퀄리티를 극대화 |

**테스트 범위**
```bash
# 단위 테스트
pytest tests/ -v

# 파이프라인 통합 테스트 (dali-core 단독, 풀 실행)
python src/pipeline.py --mode full --tier app --package dali-core --dry-run

# diff 기반 업데이트 테스트
python src/pipeline.py --mode update --from-tag v2.2.0 --to-tag v2.3.0
```

---

### Phase 5 — 전체 생성 및 배포 (1~2주)

**목표**: 3개 패키지 전체 대상 최초 문서 생성 및 운영 환경 배포

| 작업 | 내용 |
|---|---|
| 전체 최초 생성 | `--mode full --tier all` 실행, PR 생성 |
| 개발자 리뷰 | 생성된 PR에서 샘플 문서 품질 검토, 수정 |
| Docusaurus 배포 | `output/` 연동, 빌드 검증 |
| MCP 서버 연동 | 출력 MD 파일 MCP 서버 갱신 검증 |
| 운영 스케줄 확인 | GitHub Actions weekly trigger 동작 확인 |

---

## 할루시네이션 방지 다중 방어

```
[Layer 1] 정적 검증        → validator.py: 미존재 API 자동 플래그
[Layer 2] 프롬프트 제약    → Stage C: 제공된 JSON 외 언급 금지
[Layer 3] Think 검토       → Stage D: 플래그 항목 수정/삭제
[Layer 4] 개발자 PR 리뷰   → 최종 merge 전 human review
```

---

## 토큰 절약 전략

| 전략 | 효과 |
|---|---|
| Doxygen XML → 필터링된 구조화 JSON | ~60~70% 절감 |
| Call Graph는 Python에서 소화, LLM에 요약만 전달 | Call Graph 토큰 0 |
| Feature 단위 분할 → 전체 코드베이스 한 번에 입력 배제 | 컨텍스트 초과 방지 |
| 변경 감지 캐시 (변경분만 재처리) | 업데이트 시 O(M), M ≪ N |
| Stage B는 신규 Feature 발생 시만 호출 | Think 호출 최소화 |
| Stage C 병렬 처리 (`asyncio`) | 총 처리 시간 단축 |

---

## 기술 스택

| 영역 | 기술 |
|---|---|
| 언어 | Python 3.10+ |
| C++ 파싱 | Doxygen (XML + Call Graph XML) |
| LLM 연동 | OpenAI-compatible REST API (사내 로컬 LLM) |
| 병렬 처리 | `asyncio` + `aiohttp` |
| 변경 감지 | `GitPython` |
| 문서 렌더링 | `Jinja2` |
| CI/CD | GitHub Actions (self-hosted runner) |
| 정적 호스팅 | Docusaurus v3 |

---

## 리스크 및 대응

| 리스크 | 대응 |
|---|---|
| 할루시네이션 | 정적 검증 + Think 검토 + PR 리뷰 (4중 방어) |
| 토큰 비용 초과 | Feature 분할 + 캐시 + 변경분만 처리 |
| API 커버리지 누락 | 자동 커버리지 측정, 미커버 항목 리포트 |
| Doxygen Call Graph 가상함수 미추적 | 정적 클러스터링으로 보완, Think 모델 추가 검토 |
| 사내 LLM 불안정 | Retry + 지수 백오프 + 배치 크기 자동 조정 |

---

## 전체 로드맵

```
Week 1~2   : Phase 0 — 환경 설정, Doxygen 실행 검증, LLM API 연동
Week 3~5   : Phase 1 — repo_manager, doxygen_parser, callgraph_parser, diff_detector, feature_clusterer
Week 6~9   : Phase 2 — Stage A/B/C/D 프롬프트 설계 및 LLM 파이프라인 구현
Week 10~11 : Phase 3 — md_renderer, sidebar_generator, GitHub Actions 구성
Week 12~13 : Phase 4 — E2E 테스트, 품질 지표 측정, 프롬프트 개선
Week 14~15 : Phase 5 — 전체 최초 생성, Docusaurus 배포, MCP 연동 검증
```
