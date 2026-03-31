# Implementation Plan - Diff Detector

## Goal Description
`Phase 1`의 추가 컴포넌트인 `diff_detector.py`를 구현합니다.
이 스크립트는 매 업데이트 주기마다 "기존에 문서 생성이 완료되었던 Commit(또는 커밋 태그)"과 "현재 원격 저장소의 최신 Commit(HEAD)" 간의 달라진 파일 목록을 추출합니다. 그리고 변경된 헤더 파일들의 경로를 앞서 생성해둔 `parsed_doxygen/{package}.json` 내의 `file` 정보와 대조하여, **실제로 변경이 발생한 API(클래스/네임스페이스 등)들의 명단(이름표)만 담고 있는 `changed_apis.json`을 단독으로 생성**합니다.

## Proposed Changes

### [NEW] [diff_detector.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/00_extract/diff_detector.py)
`src/00_extract/diff_detector.py`를 신규 작성합니다. 주요 로직은 다음과 같습니다.

1. **Git Diff 실행**
   - 개발자가 인자로 넘긴 `--from-commit` (기본값 `HEAD~5`)과 `--to-commit` (기본값 `HEAD`) 사이의 파일 변경 사항을 `GitPython` 모듈을 이용해 추적합니다. (`repo.git.diff` 활용)
   
2. **변경된 API 대조 추출**
   - 1번에서 확보한 변경된 파일의 상대 경로 목록 문자열들을, `cache/parsed_doxygen/{package}.json`에 있는 각 컴파운드들의 `file` 프로퍼티 문자열과 매칭(검색)합니다.
   
3. **JSON 산출 및 저장 필터링**
   - 변경된 파일에 해당하는 API의 이름과 티어(api_tier)만을 리스트업하여 결과 구조체로 저장합니다. 
   ```json
   {
     "dali-core": [
       { "name": "Dali::Actor", "kind": "class", "api_tier": "public-api" }
     ],
     "dali-ui": []
   }
   ```

## User Review Required
> [!NOTE]
> 사용자의 명시적인 사전 승인 지시("작업을 바로 시작해줘")에 근거하여, 별도의 대기 피드백 루프(`request_feedback = true`)를 생략하고 곧바로 실제 파이썬 코드(`diff_detector.py`) 구현을 진행하였습니다!

## Verification Plan
1. `diff_detector.py --from-commit HEAD~5 --to-commit HEAD` 처럼 임의의 과거 구간을 설정하여 파이썬 스크립트 단독 실행 (최근 커밋에서 발생한 변경사항이 잡히도록 범위 지정).
2. 생성된 `cache/changed_apis.json` 내부에 변경 사항이 발생한 API만 정확하게 추출되었는지 조회.
