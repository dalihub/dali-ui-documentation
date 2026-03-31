# Implementation Plan - Phase 2 Stage A (Classifier)

## Goal Description
Phase 1에서 정적 휴리스틱 코드로 분류를 시도했을 때, 디렉터리 경로가 짧거나(`public-api/common.h`) 기준이 없어 방치된 소수의 API들은 `ambiguous: true` 상태로 `feature_map.json`에 분류되어 있습니다.
**Stage A (`stage_a_classifier.py`)**는 방금 우리가 구축한 막강한 `llm_client.py`의 **Think 모델(`gemini-2.5-pro`)**을 호출하여, 오직 이 "모호한 API"들의 정체성을 파악한 뒤 확률이 가장 높은 정상 클러스터 방으로 병합(이사)시키는 "정리 정돈" 단계입니다.

## Proposed Changes

### [NEW] [stage_a_classifier.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/02_llm/stage_a_classifier.py)
`src/02_llm/stage_a_classifier.py` 스크립트를 신규 작성합니다. 주요 파이프라인은 다음과 같습니다.

1. **JSON 로드 및 스캔**
   - `phase 1`이 남겨둔 `cache/feature_map/feature_map.json`을 읽고 순회하면서 플래그가 `ambiguous: true`인 클러스터들을 수집합니다.
   
2. **LLM Prompting (가드레일 방식)**
   - 이미 정상적으로 분류가 완료된 다른 Feature 이름(ex: `actors`, `events`, `rendering`, `image-loader`)들의 리스트를 가이드라인으로 뽑아냅니다.
   - LLM 클라이언트(`llm_client.py`)를 호출하여 다음과 같은 프롬프트를 전송합니다.
     > *"너는 수석 C++ 아키텍트야. 여기 `Dali::Math`라는 API가 갈 곳을 잃었어. 현재 우리가 가진 모듈 목록은 [actors, events, rendering...] 이야. 가장 성격이 잘 맞는 모듈 1개를 골라서 {"target_feature": "...", "reason": "..."} 형태의 순수 JSON으로만 대답해."*

3. **결과 파싱 및 원본 데이터 병합(Merge)**
   - LLM이 반환한 타겟 Feature 이름을 텍스트 파싱을 통해 읽어 냅니다.
   - `ambiguous` 방에 있던 API 원소를 찾아낸 타겟 방의 `apis` 배열에 편입시키고, 남은 고아 클러스터 껍데기는 삭제합니다.

4. **클린 아웃풋 생성**
   - 불확실성이 0%로 제거된, 오직 확정된 Feature 구조만 남은 최종 `feature_map_classified.json`을 생성하여 다음 단계인 Stage B로 바통을 넘깁니다.

## Verification Plan
1. `src/02_llm/stage_a_classifier.py` 스크립트를 작성합니다.
2. 터미널에서 스크립트를 실행하여, 구글 서버(`gemini-2.5-pro` 모델)에 실제 지의가 들어가고, "어디로 병합되었다"는 AI 응답 체인 로그가 제대로 찍히는지 눈으로 확인합니다.
3. 최종 생성된 `cache/feature_map/feature_map_classified.json`의 배열에 더 이상 `ambiguous: true` 가 존재하지 않는 것을 검증합니다.
