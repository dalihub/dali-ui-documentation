# Implementation Plan - Feature Clusterer

## Goal Description
Phase 1의 마지막 대미를 장식할 `feature_clusterer.py` 모듈을 구축합니다. 
앞서 `doxygen_parser`가 추출한 구조화된 API 문서(JSON 스펙)와 `callgraph_json` 콜그래프 관계망을 융합하여 의미 있는 주제 그룹(Feature Map)으로 분류하는 작업입니다.
**이 단계는 100% 휴리스틱 로직만으로 작동합니다.** 분류 기준이 모호하거나 경로 트리가 깊지 않은 소수의 API들에게만 `ambiguous: true` 태그를 부여하여, Phase 2에 있을 LLM(Stage A)의 판단 토큰 소모를 극적으로 최소화합니다.

## Proposed Changes

### [NEW] [feature_clusterer.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/01_cluster/feature_clusterer.py)
`src/01_cluster/` 디렉터리를 생성하고, `feature_clusterer.py`에 다음 파이프라인을 구현합니다.

1. **API 스펙 로드**
   - `parsed_doxygen/*.json` 내에 존재하는 3개 패키지(core, adaptor, ui)의 모든 클래스/함수(Compound)들을 메모리에 불러옵니다.
2. **디렉터리 기반 1차 그룹핑**
   - API 스펙 내의 `file` 경로를 탐색하여, `api_dirs`(e.g., `public-api`, `devel-api`) 바로 한 단계 밑의 하위 폴더 이름(ex: `actors`, `events`, `rendering`)을 추출합니다. 이 이름을 곧 핵심 Feature명(Feature Group)으로 삼아 클러스터링을 유도합니다.
3. **Ambiguous 마킹 처리**
   - 하위 폴더 없이 `public-api/common.h` 처럼 바로 루트에 노출되어 분류가 애매하거나, 공통 모듈로 판단되는 단일 파일의 API들은 임시 클러스터(`root_level_uncategorized` 등)에 담고 `ambiguous: true`로 마킹합니다.
4. **결과 산출물 융합**
   - 모인 API들을 그룹별로 묶어 `cache/feature_map/feature_map.json` 저장소에 배열 형태로 도출합니다.

## User Review Required
> [!NOTE]
> 사용자의 명시적인 지시("작업을 바로 시작해줘")에 근거하여, 별도의 대기 루프(`request_feedback = true`)를 생략하고 곧바로 실제 파이썬 코드 구현을 진행하였습니다!

## Verification Plan
1. 새로운 폴더 구조(`src/01_cluster/`)와 스크립트 실행으로 에러가 없는지 체크합니다.
2. 출력되는 `feature_map.json` 내의 그룹화된 갯수와 분포, 그리고 `ambiguous` 마킹 값들의 정확성을 검증합니다.
