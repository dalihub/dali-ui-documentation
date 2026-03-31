# Implementation Plan - Phase 2 (LLM Pipeline Infrastructure)

## Goal Description
`Phase 1`을 통해 완벽하게 산출된 정적 객체들(`feature_map.json`, `changed_apis.json` 등)을 실제 LLM 인퍼런스 엔진에 연결하여 Markdown 가이드를 뽑아내는 **Phase 2 (LLM 파이프라인)**로 본격 진입합니다.
우선 전체 4개의 Stage(A~D) 로직을 만들기 전에, 앞에서 우리가 논의했던 **내외부 모델 스위칭 아키텍처와 Rate Limit 지연 방어선**을 핵심 코어로 깔아놓는 **LLM 통신 인프라(`llm_client.py`)**를 최우선적으로 구축합니다.

## Proposed Changes

### [MODIFY] [doc_config.yaml](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/config/doc_config.yaml) (또는 신규 생성)
- Phase 2 구동에 쓰일 공통 설정값 파일(`yaml`)을 구성합니다.
  - `llm_environment`: "internal" 혹은 "external"의 글로벌 스위치.
  - 내부망(사내 LLM)과 외부망(Gemini) 각각의 `rate_limit_delay_sec`(분당 제한 대기 시간) 및 `max_retries`(재시도 횟수).

### [NEW] [llm_client.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/02_llm/llm_client.py)
- 백엔드의 뇌 역할을 할 독립적인 API 통신 싱글톤 파일입니다.
  - **팩토리 패턴(Factory Pattern)**: `doc_config.yaml`의 스위치에 따라 사내망 API 요청 방식 혹은 외부 인터넷(Gemini) 요청 방식 중 하나를 자동으로 선택하여 인스턴스화합니다.
  - **견고한 요청 계층**: API 호출 전후로 지정된 `time.sleep` 지연을 강제 삽입하고, HTTP 429(Too Many Requests) 에러 발생 시 Exponential Backoff 전략으로 자동 재시도를 수행하여 파이프라인 중단을 원천 차단합니다.
  - **인터페이스 분리**: 코드를 요청하는 측(개발자)은 `client.generate("Gemini prompt", model="think")` 형태로만 호출하면 되도록 매우 단조롭게 추상화합니다.

### Phase 2 Stage Overview (향후 단계별 로직)
강력한 `llm_client.py` 뼈대가 마련되면, 이어지는 단계에서 아래의 Stage 작업들을 수월하게 착수하게 됩니다.
- **Stage A (`stage_a_classifier.py`)**: `ambiguous: true` 특성 API들의 올바른 클러스터링 매핑.
- **Stage B (`stage_b_mapper.py`)**: 클러스터별 앱/플랫폼 개발자용 문서 구조(TOC) 설계.
- **Stage C (`stage_c_writer.py`)**: 본격적인 Markdown 본문 초안 작성 (Diff 업데이트 병합).
- **Stage D (`stage_d_reviewer.py`)**: 작성된 문서의 Anti-hallucination 크로스 체크.

## User Review Required
> [!IMPORTANT]
> `config/doc_config.yaml` 파일과 핵심 통신 인터페이스인 `llm_client.py`를 먼저 단단히 다져두는 것이 가장 베스트 프랙티스입니다.
> 
> *이 인프라 설계 방안대로 진행해도 좋을지 승인 한 번 부탁드립니다! 승인(진행!)해 주시는 즉시 코딩에 돌입하겠습니다.*

## Verification Plan
1. `llm_client.py` 자체 테스트 구문을 작성합니다.
2. 주입된 외부 Gemini KEY를 참조하여 `client.generate("hello")` 테스트를 2~3회 연속 실행시켜 통신 딜레이(지연시간 대기)와 정상 응답 출력 여부를 터미널로 검증합니다.
