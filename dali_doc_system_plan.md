# AI 기반 다계층 C++ 라이브러리 가이드 문서 자동 생성 시스템 — 전체 프로세스 플랜

## 1. 시스템 개요

```
┌──────────────────────────────────────────────────────────┐
│                      입력 소스                            │
│   dali-core / dali-adaptor / dali-ui  (GitHub Repos)     │
│   public-api / devel-api / integration-api (C++ + Dox)   │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│           Stage 0: 정적 분석 & 데이터 추출 [LLM 없음]     │
│  Doxygen XML (API 문서 + Call Graph + 상속 관계) → JSON    │
│  → Python 기반 Feature 클러스터링                         │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│     Phase 1.5: Feature Taxonomy 설계 [Think 모델]        │
│  - 상속 계층 Tree 구조 여부 LLM 결정                      │
│  - View 문서 강제 주입 (수동 Feature Override)            │
│  - 결과 영속화 → feature_taxonomy.json                   │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│         Stage A: Feature 경계 분류 [Think 모델]           │
│  모호한 API만 선별 처리                                   │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│           Stage B: 목차 설계 [Think 모델]                 │
│  전체 목차 + 핵심 시나리오 + prerequisite 정의            │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│         Stage C: 문서 초안 작성 [Instruct 모델]           │
│  Feature 단위 병렬 처리                                   │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│          Stage D: 검토 및 수정 [Think 모델]               │
│  할루시네이션 검증 + 논리 오류 + 누락 시나리오 보완       │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│            Stage E: 출력 & 배포 [LLM 없음]               │
│  Frontmatter .md 생성 → PR 생성 → Docusaurus / MCP       │
└──────────────────────────────────────────────────────────┘
```

---

## 2. 대상 API 범위

| 패키지 | public-api | devel-api / integration-api | 문서 타겟 |
|---|---|---|---|
| dali-core | ✅ | ✅ 사내 전용 | 앱 개발자 + Platform 개발자 |
| dali-adaptor | ✅ | ✅ 사내 전용 | 앱 개발자 + Platform 개발자 |
| dali-ui | ✅ | ✅ 사내 전용 | 앱 개발자 + Platform 개발자 |

| 문서 종류 | 포함 API | 독자 |
|---|---|---|
| `app-guide/` | public-api 전용 | 일반 앱 개발자 |
| `platform-guide/` | public-api + devel-api + integration-api | 사내 Platform 개발자 |

---

## 3. 시스템 디렉터리 구조

```
dali-doc-gen/
├── .github/
│   └── workflows/
│       ├── weekly-update.yml       # 주간 diff 기반 업데이트
│       └── initial-full-gen.yml    # 최초 전체 생성
├── config/
│   ├── llm_config.yaml             # Think/Instruct 엔드포인트
│   ├── repo_config.yaml            # 패키지 경로/브랜치
│   └── doc_config.yaml             # 문서 구조/카테고리
├── src/
│   ├── 00_extract/
│   │   ├── doxygen_runner.py       # Doxyfile 생성 및 Doxygen 실행
│   │   ├── doxygen_parser.py       # XML → 구조화 JSON (API 문서)
│   │   ├── callgraph_parser.py     # XML → 호출 관계 JSON
│   │   └── diff_detector.py        # Git diff → 변경 API 목록
│   ├── 01_cluster/
│   │   └── feature_clusterer.py    # API + 호출관계 → Feature 그룹
│   ├── 02_llm/
│   │   ├── stage_a_classifier.py   # Think: Feature 경계 분류
│   │   ├── stage_b_planner.py      # Think: 목차 설계
│   │   ├── stage_c_writer.py       # Instruct: 문서 초안 작성
│   │   └── stage_d_reviewer.py     # Think: 검토 및 수정
│   ├── 03_render/
│   │   ├── md_renderer.py          # Markdown + Frontmatter 생성
│   │   └── sidebar_generator.py    # Docusaurus sidebar.json 생성
│   ├── validator.py                # 정적 검증 (API 존재 여부)
│   └── pipeline.py                 # 전체 파이프라인 오케스트레이션
├── prompts/
│   ├── stage_a_prompt.md
│   ├── stage_b_prompt.md
│   ├── stage_c_prompt.md
│   └── stage_d_prompt.md
├── cache/
│   ├── doxygen_json/               # 파싱 결과 캐시
│   ├── callgraph_json/             # 호출 관계 캐시
│   ├── feature_map/                # Feature 클러스터링 캐시
│   └── toc/                        # 목차 캐시
├── output/
│   ├── app-guide/
│   └── platform-guide/
└── scripts/
    ├── run_full.sh
    └── run_update.sh
```

---

## 4. Stage 0: 정적 분석 & 데이터 추출 (LLM 없음)

### 4.1 Doxygen 설정

```ini
# Doxyfile (공통)
GENERATE_XML   = YES
XML_OUTPUT     = doxygen-xml
EXTRACT_ALL    = YES
CALL_GRAPH     = YES   # 함수가 호출하는 대상
CALLER_GRAPH   = YES   # 함수를 호출하는 주체
HAVE_DOT       = YES
```

Doxygen 한 번 실행으로 **API 문서 + Call Graph** 둘 다 XML로 출력됩니다.

### 4.2 XML → 구조화 JSON 변환 전략

XML을 JSON으로 변환하는 것은 단순 포맷 변환이 아니라 **LLM 입력에 최적화된 정보 추출**입니다.

| 항목 | XML 포함 | JSON 포함 | 이유 |
|---|---|---|---|
| 내부 ID, 파일 오프셋 | ✅ | ❌ | LLM에 불필요 |
| brief / param / return | ✅ | ✅ | 문서 핵심 |
| @note / @warning / @since / @deprecated | ✅ | ✅ | 문서 핵심 |
| XML 중첩 태그 구조 | ✅ | ❌ | 평탄화하여 토큰 절감 |
| calls / called_by (직접 1단계만) | ✅ | ✅ (요약) | Feature 클러스터링용 |

**효과: 원본 XML 대비 약 60~70% 토큰 절감**

```json
// API 문서 JSON 예시
{
  "id": "Dali::Actor::SetPosition",
  "package": "dali-core",
  "api_tier": "public-api",
  "brief": "Sets the position of the actor.",
  "params": [{"name": "position", "type": "const Vector3&", "desc": "The new position."}],
  "returns": "void",
  "notes": ["Position is relative to parent."],
  "warnings": [],
  "deprecated": false,
  "since": "1.0.0",
  "calls": ["Node::SetPosition"],
  "called_by": ["Animation::AnimateTo"]
}
```

> **Call Graph는 LLM에 직접 넣지 않습니다.**  
> Python 코드(feature_clusterer.py)에서 소화하여 Feature 클러스터링에 활용하고,  
> LLM에는 Feature 단위 요약 결과만 전달합니다.

### 4.3 View 기반 앱 아키텍처 반영 원칙

`dali-ui` 앱 개발자는 `Dali::Actor`를 직접 사용하지 않고, `Dali::Ui::View`를 기본 UI 객체로 사용합니다.
View는 Actor를 상속받지만, API 사용 방식과 이벤트 모델이 상이하므로 문서 작성 시 아래 원칙을 적용합니다.

- **View 문서 강제 주입**: `repo_config.yaml`의 `manual_features` 항목으로 View를 별도 Feature로 추가
- **Actor 문서의 비중 조정**: Stage C 프롬프트에서 Actor 설명은 배경 지식으로만, View API를 주체로 작성
- **코드 예제**: 항상 `Dali::Ui::View` 기준으로 작성, Actor API는 View가 상속한 컨텍스트로 설명

### 4.4 Feature Taxonomy (Phase 1.5 신규)

상속 계층이 있다고 해서 무조건 Tree 문서 구조를 만들지 않습니다. LLM이 다음 기준으로 판단합니다:

- **Tree 구조 생성 기준**: 하위 클래스 수 ≥ 3개이고, 각 클래스가 독립적인 사용 시나리오를 가질 때
- **Flat 유지 기준**: 하위 클래스가 단순 변형이거나 앱 개발자 관점에서 구분이 불필요할 때

```json
// feature_taxonomy.json 예시
{
  "view": {
    "display_name": "View (Base UI Object)",
    "parent": null,
    "children": ["image-view", "label", "scroll-view", "button"],
    "doc_file": "view.md"
  },
  "image-view": {
    "display_name": "ImageView",
    "parent": "view",
    "children": [],
    "doc_file": "image-view.md"
  }
}
```

- **영속화**: `cache/feature_taxonomy/feature_taxonomy.json`에 저장
- **증분 업데이트**: `diff_detector`가 감지한 신규/변경 클래스만 LLM 재검토, 나머지는 기존 taxonomy 재사용

```json
// feature_map.json 예시
{
  "feature": "Actor Positioning & Transformation",
  "packages": ["dali-core"],
  "apis": ["Dali::Actor::SetPosition", "Dali::Actor::GetPosition", "..."],
  "cross_package_links": ["dali-adaptor::RenderSurface"],
  "related_features": ["Animation", "Scene Graph"],
  "api_tiers": ["public-api"],
  "ambiguous": false
}
```

---

## 5. LLM 사용 단계 상세

### Stage A — Feature 경계 분류 (Think)

| | |
|---|---|
| **Input** | 모호 플래그 API 목록 + 후보 Feature 목록 (JSON) |
| **Output** | 각 API의 소속 Feature 결정값 |
| **호출 빈도** | 모호한 케이스만 (전체의 일부) |

---

### Stage B — 목차 설계 (Think)

| | |
|---|---|
| **Input** | Feature 목록 + API 이름/brief 요약 (JSON) |
| **Output** | `toc_plan.json` (카테고리 구조, 학습 순서, Feature별 시나리오 2~3개) |
| **호출 빈도** | 최초 1회 / 신규 Feature 추가 시만 |

---

### Stage C — 문서 초안 작성 (Instruct)

| | |
|---|---|
| **Input** | Feature의 API JSON (brief/param/return/note/warning) + Stage B 시나리오 |
| **Output** | Markdown 초안 (overview + API 설명 + 코드 스니펫 + 주의사항) |
| **호출 빈도** | Feature 수만큼 병렬 / 변경된 Feature만 재호출 |

```
프롬프트 규칙:
1. 제공된 API JSON에 없는 함수/클래스/동작은 절대 언급하지 말 것
2. 코드 스니펫은 실제 API 시그니처의 타입만 사용
3. @warning, @note는 반드시 포함
4. Frontmatter (title, category, tier, packages) 포함
```

---

### Stage D — 검토 및 수정 (Think)

| | |
|---|---|
| **Input** | Stage C 초안 + 원본 API JSON + 정적 검증 플래그 목록 |
| **Output** | 수정 지시 (삭제/교체/보완 항목) + 최종 승인 여부 |
| **호출 빈도** | Stage C와 동일 (변경된 Feature만) |

**정적 검증 (LLM 없음, Stage D 이전 선처리)**:
- 문서 내 등장한 모든 클래스/함수명 → API DB와 대조
- 존재하지 않는 API → 자동 플래그 후 Stage D 입력에 포함

---

## 6. 할루시네이션 방지 다중 방어

```
[Layer 1] 정적 검증 (LLM 없음)
  문서 내 API 이름 → Doxygen DB 대조, 미존재 기호 자동 플래그

[Layer 2] 프롬프트 제약 (Stage C)
  "제공된 API JSON 외 언급 금지" 명시
  구조화 JSON만 입력 (자연어 설명 최소화)

[Layer 3] Think 모델 검토 (Stage D)
  플래그 항목 수정/삭제, 논리적 오류 수정

[Layer 4] 개발자 PR 리뷰
  최종 merge 전 human review
```

---

## 7. 실행 모드 비교

### 7.1 최초 전체 생성

| Stage | 모델 | 범위 |
|---|---|---|
| 0. 정적 분석 | — | 전체 패키지 |
| A. Feature 분류 | Think | 전체 중 모호한 케이스 |
| B. 목차 설계 | Think | **전체 Feature 1회** |
| C. 문서 작성 | Instruct | **전체 Feature N개 (병렬)** |
| D. 검토 | Think | **전체 Feature N개 (병렬)** |

### 7.2 주기적 업데이트 (diff 기반)

```
git diff <prev_tag>..<current_tag> -- */public-api/ */devel-api/ */integration-api/
→ 변경된 헤더 파일 → 영향받는 API → 해당 Feature 식별
→ Feature 간 의존 파급 범위 계산 (Python)
→ 재처리 대상 Feature 목록 확정
```

| Stage | 모델 | 범위 |
|---|---|---|
| 0. 정적 분석 | — | 변경된 파일만 |
| A. Feature 분류 | Think | 신규 API가 기존 Feature 불일치 시만 |
| B. 목차 설계 | Think | **신규 Feature 발생 시만 (대부분 스킵)** |
| C. 문서 작성 | Instruct | **변경된 Feature M개만 (M ≪ N)** |
| D. 검토 | Think | **변경된 Feature M개만** |

> 일반적인 주간 업데이트: Stage B 스킵, C+D만 변경 Feature 수만큼 호출

---

## 8. 토큰 절약 전략 요약

| 전략 | 효과 |
|---|---|
| Doxygen XML → 구조화 JSON (필터링) | ~60~70% 토큰 절감 |
| Call Graph는 Python에서 소화, LLM에 요약만 전달 | Call Graph 토큰 비용 0 |
| Feature 단위 분할 처리 | 코드베이스 전체 한 번에 입력 배제 |
| 변경 감지 캐시 (변경분만 재처리) | 업데이트 시 LLM 호출 O(M), M ≪ N |
| Stage B는 신규 Feature 시만 호출 | Think 모델 호출 최소화 |
| Stage C 병렬 처리 | 전체 처리 시간 단축 |

---

## 9. GitHub Actions CI/CD

### 주간 업데이트 (`weekly-update.yml`)

```yaml
on:
  schedule:
    - cron: '0 2 * * 1'   # 매주 월요일 02:00 UTC
  workflow_dispatch:

jobs:
  update-docs:
    runs-on: self-hosted    # 사내 runner (로컬 LLM 접근)
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - name: Run update pipeline
        env:
          LLM_THINK_ENDPOINT: ${{ secrets.LLM_THINK_ENDPOINT }}
          LLM_INSTRUCT_ENDPOINT: ${{ secrets.LLM_INSTRUCT_ENDPOINT }}
        run: python src/pipeline.py --mode update
      - uses: peter-evans/create-pull-request@v6
        with:
          title: "docs: Weekly auto-update"
          branch: "auto-docs/${{ env.DATE }}"
          labels: "documentation,auto-generated"
          reviewers: "doc-reviewers-team"
```

### 최초 전체 생성 (`initial-full-gen.yml`)

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
      - ...
      - run: python src/pipeline.py --mode full --tier ${{ inputs.target_tier }}
      - uses: peter-evans/create-pull-request@v6
        with:
          title: "docs: Initial full documentation generation"
```

---

## 10. 출력 Markdown 형식

```markdown
---
title: Actor Positioning & Transformation
category: UI Layout
tier: app          # app | platform
packages:
  - dali-core
api_version: "2.3.0"
last_updated: "2026-03-31"
---

## 개요
...

## API 레퍼런스
...

## 사용 예제
...

## 주의사항
...

## 관련 문서
...
```

---

## 11. 기술 스택

| 영역 | 기술 |
|---|---|
| 언어 | Python 3.10+ |
| C++ 파싱 | Doxygen (XML + Call Graph XML) |
| LLM 연동 | OpenAI-compatible REST API (사내 로컬 LLM) |
| 병렬 처리 | `asyncio` + `aiohttp` |
| 변경 감지 | GitPython |
| 문서 출력 | Jinja2 템플릿 |
| CI/CD | GitHub Actions (self-hosted runner) |
| 정적 호스팅 | Docusaurus v3 |

---

## 12. 개발 로드맵

| Phase | 내용 | 기간 |
|---|---|---|
| 0 | 환경 설정, LLM API 연동 테스트, Doxygen XML+CallGraph 출력 검증 | 1~2주 |
| 1 | doxygen_parser, callgraph_parser, diff_detector, feature_clusterer 구현 | 2~3주 |
| 2 | Stage A/B/C/D 프롬프트 설계 및 LLM 파이프라인 구현 | 3~4주 |
| 3 | md_renderer, sidebar_generator, GitHub Actions 워크플로우 구성 | 2주 |
| 4 | E2E 테스트, 할루시네이션 율 측정, API 커버리지 측정, 프롬프트 개선 | 2주 |
| 5 | 전체 패키지 최초 생성, PR/리뷰, Docusaurus 배포, MCP 연동 검증 | 1~2주 |

---

## 13. 리스크 및 대응

| 리스크 | 대응 |
|---|---|
| 할루시네이션 | 정적 검증 + Think 검토 + PR 리뷰 (4중 방어) |
| 토큰 비용 초과 | Feature 분할 + 캐시 재사용 + 변경분만 처리 |
| API 커버리지 누락 | API DB 대비 문서화 비율 자동 측정, 미커버 항목 리포트 |
| Doxygen Call Graph 가상함수 미추적 | 정적 호출 체인으로 Feature 클러스터링, 누락은 Think 모델 보완 |
| 사내 LLM 불안정 | Retry + 지수 백오프 + 배치 크기 조정 |
