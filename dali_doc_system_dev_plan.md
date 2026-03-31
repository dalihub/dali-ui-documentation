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

## 시스템 아키텍처 요약

```
입력(GitHub Repos)
  └── Stage 0: Doxygen XML 파싱 → 구조화 JSON + Feature 클러스터링  [LLM 없음]
        └── Stage A: 모호 API Feature 경계 분류                     [Think]
              └── Stage B: 전체 목차 + 시나리오 설계                [Think]
                    └── Stage C: Feature별 문서 초안 작성 (병렬)    [Instruct]
                          └── Stage D: 정적 검증 + 논리 검토/수정   [Think]
                                └── Stage E: MD 렌더링 → PR 생성    [LLM 없음]
```

---

## 프로젝트 디렉터리 구조

```
dali-doc-gen/
├── .github/workflows/
│   ├── weekly-update.yml
│   └── initial-full-gen.yml
├── config/
│   ├── llm_config.yaml        # Think/Instruct 엔드포인트, 모델명, 파라미터
│   ├── repo_config.yaml       # 각 패키지 경로, 브랜치, API 폴더 목록
│   └── doc_config.yaml        # 문서 카테고리, 출력 경로, Frontmatter 기본값
├── src/
│   ├── 00_extract/
│   │   ├── doxygen_runner.py    # Doxyfile 자동 생성 및 Doxygen 실행
│   │   ├── doxygen_parser.py    # Doxygen XML → 구조화 JSON 변환
│   │   ├── callgraph_parser.py  # Call Graph XML → 호출관계 JSON
│   │   └── diff_detector.py     # Git diff → 변경 API 목록 추출
│   ├── 01_cluster/
│   │   └── feature_clusterer.py # 네임스페이스 + CallGraph → Feature 그룹
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

#### `doxygen_parser.py`
- Doxygen `compound.xml` 파싱
- 추출 항목: `id`, `package`, `api_tier`, `brief`, `params`, `returns`, `notes`, `warnings`, `deprecated`, `since`
- 내부 ID·파일 오프셋 제거 → 토큰 절감 (약 60~70%)
- 출력: `cache/doxygen_json/{package}.json`

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
- 모호 케이스 플래그 (`ambiguous: true`)
- 출력: `cache/feature_map/feature_map.json`

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

#### `stage_d_reviewer.py` (Think 모델)
- 입력: Stage C 초안 + 원본 API JSON + 정적 검증 플래그
- 출력: 수정 지시 (삭제/교체/보완) + 최종 승인 여부
- `validator.py`와 연동하여 미존재 API 자동 플래그 선처리

#### `validator.py`
- 문서 내 등장한 클래스/함수명 → API DB 대조
- 미존재 기호 → 자동 플래그 → Stage D 입력에 포함

**산출물**: Feature별 검토 완료 Markdown 초안

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

#### GitHub Actions

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

**목표**: 전체 파이프라인 통합 테스트 및 품질 지표 측정

| 측정 항목 | 방법 |
|---|---|
| API 커버리지 | 전체 API DB 대비 문서화된 API 비율 자동 계산, 미커버 항목 리포트 |
| 할루시네이션율 | `validator.py`의 미존재 API 플래그 수 / 전체 API 언급 수 |
| 토큰 사용량 | 각 Stage별 실제 호출 토큰 로깅 |
| 프롬프트 개선 | 할루시네이션 사례 수집 → `prompts/*.md` 반복 개선 |

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
Week 3~5   : Phase 1 — doxygen_parser, callgraph_parser, diff_detector, feature_clusterer
Week 6~9   : Phase 2 — Stage A/B/C/D 프롬프트 설계 및 LLM 파이프라인 구현
Week 10~11 : Phase 3 — md_renderer, sidebar_generator, GitHub Actions 구성
Week 12~13 : Phase 4 — E2E 테스트, 품질 지표 측정, 프롬프트 개선
Week 14~15 : Phase 5 — 전체 최초 생성, Docusaurus 배포, MCP 연동 검증
```
