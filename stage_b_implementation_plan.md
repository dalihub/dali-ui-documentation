# Implementation Plan - Phase 2 Stage B (Content Mapper)

## Goal Description
맞습니다! `feature_map_classified.json`은 Stage A를 거쳐 불확실성이 완전히 소거된 **"최종 무결점 API 지도"**입니다. 원본을 파괴하지 않고 이를 파이프라인의 다음 단계 입력값으로 넘기는 것이 안전한 데이터 엔지니어링의 정석입니다.
이제 이 무결점 지도를 기반으로 **Stage B (`stage_b_mapper.py`)** 를 진행합니다. 이 단계는 무작정 빈 백지에 글을 쓰기 전에, 각 기능(Feature)마다 어떤 순서로 문서를 써내려갈지(도입부, 핵심 클래스, 연동 방식, 예제 등) **목차(TOC)와 뼈대를 기획**하는 "설계도 그리기" 단계입니다.

## Proposed Changes

### [NEW] `src/02_llm/stage_b_mapper.py`
다음과 같은 논리로 구동되는 파이썬 스크립트를 신규 작성합니다:

1. **지형지물(Classified Map) 로드**
   - 앞서 산출된 무결점 파일 `cache/feature_map/feature_map_classified.json`을 읽어들입니다.
   - 각 Feature(예: `actors`, `events`, `rendering` 등) 블록마다 순차적으로 순회를 시작합니다.

2. **LLM Prompting (설계사 - Think 모델 호출)**
   - API 리스트와 `api_tiers` (Public/Devel 구조 등) 정보를 묶어서 LLM(`gemini-2.0-flash`)에게 다음과 같은 프롬프트를 전송합니다.
     > *"너는 C++ 개발 문서를 집필하는 테크니컬 라이터야. 이번에 다룰 챕터는 `{feature_name}` 모듈이고, 여기에 포함된 API들은 `[Dali::Actor, Dali::Actor::Add...]` 이야. 이 기능들을 앱 개발자와 플랫폼 개발자 관점에서 가장 쉽고 논리적으로 설명할 수 있도록 마크다운 가이드의 논리적 목차(섹션 제목 3~5개 정도)와, 각 섹션에서 무얼 다룰지 짧은 요약을 만들어줘. 결과는 반드시 사전에 정의된 JSON 배열로만 줘."*

3. **기획서(Blueprint) 산출**
   - 각 Feature별로 LLM이 짜준 `outline` (목차 배열)을 원본 딕셔너리에 추가합니다.
   - 33개의 Feature 그룹 각각에 "마크다운 문서 뼈대"가 장착된 거대한 최종 설계도를 `cache/doc_blueprints/stage_b_blueprints.json` 이라는 파일로 생성합니다.

## User Review Required
> [!IMPORTANT]
> Stage B는 바로 문서를 쓰는 게 아니라, **건축의 철골(목차)을 세우는 작업**입니다. 여기서 뼈대를 잘 잡아두면 Stage C에서 글을 쓸 때 주제가 산으로 가거나(Hallucination) 포커스가 흔들리는 것을 원천 차단할 수 있습니다.
> 
> *이 "목차 뼈대 설계 전략"으로 코딩에 돌입할지 승인(`진행!`) 한 번 부탁드립니다.*

## Verification Plan
1. `src/02_llm/stage_b_mapper.py` 스크립트 구조를 작성합니다.
2. 실행 시 터미널에서 구글 2.0 API와 통신하며 각 그룹들의 문서 뼈대를 어떻게 설계하는지 로그를 관찰합니다. (이번 역시 Rate Limit에 걸리지 않고 부드럽게 넘어가도록 설계합니다)
3. 파이프라인 출력물 `cache/doc_blueprints/stage_b_blueprints.json`이 각 모듈마다 이쁜 `"outline"` 키를 가지고 생성되었는지 확인합니다.
