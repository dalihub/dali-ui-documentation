# DALi AI Documentation Pipeline

DALi C++ 라이브러리(Core, Adaptor, UI)의 리포지토리 코드를 정적 분석(Doxygen XML)하고, 이 데이터를 바탕으로 두 개의 LLM (Think 모델, Instruct 모델)을 교차 활용하여 고품질의 Docusaurus용 마크다운 가이드 문서를 자동 생성하는 AI 파이프라인 시스템입니다.

---

## 🚀 파이프라인 기초 사용법 (`pipeline.py`)

파이프라인의 모든 코어 동작(Phase 1 ~ Phase 3)을 중앙 제어하는 스크립트는 `dali-doc-gen/src/pipeline.py` 입니다.

### 1. 전체 구동 (Full Generation)
```bash
cd dali-doc-gen
python src/pipeline.py --mode full --tier all
```
- 최초로 문서를 생성하거나 캐시를 전부 엎고 100% 새로 생성할 때 사용합니다.
- `--tier all`을 주면 `app`과 `platform` 독자 타겟을 각각 순회하여 두 파트의 문서를 모두 산출합니다.

### 2. 증분 업데이트 (Incremental Update)
```bash
python src/pipeline.py --mode update --tier app
```
- 매주 CI/CD가 돌 때 사용되는 모드입니다. 변경된 API를 패치하거나, 구조 변동(Taxonomy 변경)이 발생한 모듈만 찾아 무효화(Invalidation)하고 다시 작성합니다.

### 3. 디버깅 및 특정 기능 대상 타겟 테스트
아래 옵션을 조합하여 시간과 LLM API 토큰 비용을 아낄 수 있습니다.

```bash
# 앞 부분의 3개 모듈만 생성 테스트
python src/pipeline.py --mode full --tier app --limit 3

# (매우 유용!) 콕 집어서 'view' 모듈과 'actors' 모듈만 테스트
python src/pipeline.py --mode full --tier app --features "view,actors"
```

> **Q. 기존 bash 스크립트처럼 특정 Feature만 생성할 수 있나요?**  
> 네! `--features "콤마구분문자열"` 옵션을 주시면 기존 스크립트의 `TARGET_FEATURES`와 완벽히 동일하게 동작합니다. 위 예시처럼 타겟 문서를 정확히 지정하여 특정 모듈만 Stage C까지 파이프라인을 관통시킬 수 있습니다.

---

## 🧩 파이프라인 구조 및 단계별 개별 실행 방법

전체 파이프라인은 3개의 Phase(추출, 생성, 렌더링)로 구성되며, 각 파이썬 스크립트를 수동으로 단독 실행(`python src/.../script.py`)할 수 있도록 아키텍처가 철저히 분리되어 있습니다. 파이프라인이 멈추거나 특정 구간만 다시 디버깅할 때 유리합니다.

### Phase 1: 로우 데이터 추출 및 군집화 (Extract & Cluster)
*기계 친화적인 Doxygen 데이터를 인간(LLM) 친화적인 구조로 1차 압축합니다.*

1. **`00_extract/doxygen_parser.py`**
   - **기능**: Doxygen XML을 읽어와서 파라미터, 반환값, Brief 만 남긴 초경량 JSON 스펙 트리를 만듭니다.
   - **산출물**: `cache/parsed_doxygen/` (기존 용량의 90%를 줄인 경량 JSON)
2. **`01_cluster/feature_clusterer.py`**
   - **기능**: DALi C++의 패키지/클래스들을 기능적 의미 단위(Feature)인 클러스터로 묶어냅니다.
   - **산출물**: `cache/feature_map/feature_map_classified.json`
3. **`01_cluster/taxonomy_reviewer.py`**
   - **기능**: 평면적(Flat)이었던 피처들을 Tree 구조(부모-자식)로 재배치하고, 플랫폼 전용(platform)인지 앱 전용(app)인지 독자를 판별합니다.
   - **산출물**: `cache/feature_taxonomy/feature_taxonomy.json`

### Phase 2: LLM 문서 생성 시스템 (LLM Generation)
*Think Model 체인과 Instruct Model 체인이 협동하여 문서를 쓰고, Hallucination을 즉시 색출해 버립니다.*

4. **`02_llm/stage_b_mapper.py` (--limit, --features 지원)**
   - **기능**: Think Model을 써서, API 스펙을 바탕으로 문서의 뼈대(목차, TOC)를 기획합니다.
   - **산출물**: `cache/doc_blueprints/stage_b_blueprints.json`
5. **`02_llm/stage_c_writer.py` (--limit, --features 지원)**
   - **기능**: Instruct Model이 기획된 목차와 가이드라인(Prompt)을 바탕으로 실제 유려한 마크다운 본문을 작성합니다.
   - **산출물**: `cache/markdown_drafts/*.md`
6. **`02_llm/stage_d_validator.py`**
   - **기능**: 생성된 마크다운 본문 속 `Dali::Symbol` 들이 실제 Doxygen 원본에 존재하는지 교차 대조하여 거짓말(Hallucination)을 검증합니다.
   - **산출물**: `cache/validated_drafts/*.md` 및 `cache/validation_report/stage_d_report.json`

### Phase 3: Docusaurus 규격 렌더링 (Render & SEO)
*생성된 순수 마크다운을 Docusaurus v3 웹사이트 형태에 맞춰 포맷팅합니다.*

7. **`03_render/md_renderer.py` (--tier [app|platform])**
   - **기능**: YAML Frontmatter 생성, 더미 Doxygen 하단 링크 부착, 타 문서 간의 딥링크(`[ImageView](./image-view.md)`) 치환.
   - **산출물**: `output/app-guide/docs/` 또는 `output/platform-guide/docs/`
8. **`03_render/sidebar_generator.py` (--tier [app|platform])**
   - **기능**: Taxonomy 구조에 맞춰 Docusaurus 메뉴 내비게이션 트리를 JSON 배열로 직렬화합니다.
   - **산출물**: `output/app-guide/sidebar.json` 또는 `output/platform-guide/sidebar.json`

---

## 🔍 산출물 및 Docusaurus 사이드바 테스트 방법

1. **마크다운 초안이 제대로 써졌는가?**
   - `dali-doc-gen/cache/markdown_drafts/` 폴더 내 `.md` 파일들을 열어봅니다. 내용물이 C++ 예제 코드와 함께 잘 적혀있다면 Stage C가 정상 동작한 것입니다.
2. **할루시네이션(거짓 정보)이 생성되지 않았는가?**
   - `dali-doc-gen/cache/validation_report/stage_d_report.json` 파일을 확인합니다. 여기서 `"result": "FAIL"` 인 항목이 있다면, 자동 Retry Loop가 발동하였거나 본문 퀄리티에 치명적인 문제가 있는 것입니다.
3. **`sidebar.json`과 Docusaurus 결과물은 어떻게 테스트하나요?**
   - 렌더러가 만들어낸 `output/app-guide/sidebar.json`은 Docusaurus 프레임워크가 읽어들이는 **사이드바 메뉴 환경 설정 파일**입니다.
   - 이를 실제 화면으로 테스트하려면, 미리 구축된 Docusaurus 웹 프로젝트 폴더 안에 `output/app-guide/docs/` 폴더와 `sidebar.json`을 복사해 넣고, 터미널에서 `npm run start` 를 실행해야 합니다. Docusaurus가 이 JSON 구조를 파싱하여 왼쪽 내비게이션 트리를 예쁘게 렌더링해 줍니다.

---

## ⚙️ GitHub Actions CI/CD 파이프라인 실행 방법

이 레파지토리에는 `.github/workflows/` 안에 2개의 CI/CD 자동화 스크립트가 세팅되어 있습니다. **단순히 코드를 Push한다고 무턱대고 돌며 LLM 토큰을 소모하지 않도록 설계**되어 있습니다.

**1. 수동 전체 생성 (`initial-full-gen.yml`)**
- 깃허브 웹 화면에서 `Actions` 탭에 들어갑니다.
- 좌측 워크플로우 목록 중 **"Initial Full Documentation Generation"**을 클릭합니다.
- 우측의 **`Run workflow`** 버튼을 누르면 `--tier` 옵션을 고를 수 있는 창이 나옵니다.
- `app`, `platform`, `all` 중 하나를 선택해 돌리면, 파이프라인이 완료된 후 "docs/initial-full-app" 이라는 브랜치 이름으로 Docusaurus 문서 생성본 전체가 담긴 Pull Request(PR)가 자동으로 열립니다.

**2. 매주 자동 업데이트 (`weekly-update.yml`)**
- 별다른 클릭을 하지 않아도 **매주 월요일 새벽 0시(UTC)** 마다 깃허브 서버에서 백그라운드로 자동 실행(`cron 스케줄링`)됩니다.
- 한 주 동안 C++ 코드에 생긴 변동사항이나 새로 추가된 Feature들을 감지해 무효화 매커니즘을 돌린 후, 바뀐 내용들만 묶어서 Pull Request(PR)를 올려줍니다.
- 물론, 이것도 `Actions` 탭에서 **`Run workflow`** 버튼을 눌러 개발자가 원할 때 즉시(수동으로) 업데이트 PR을 찍어낼 수도 있습니다.
