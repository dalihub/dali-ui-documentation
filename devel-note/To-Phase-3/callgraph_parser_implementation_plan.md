# Implementation Plan - Doxygen Call Graph Parser

## Goal Description
`Phase 1`의 추가 컴포넌트인 `callgraph_parser.py`를 구현합니다.
이 파서는 Doxygen이 생성한 XML 파일들을 분석하여 각 API(함수) 간의 호출 관계(`calls`, `called_by`)를 추출하고, 이를 경량화된 JSON 포맷으로 저장합니다. 추출된 통계는 이후 `feature_clusterer.py`에서 연관된 API들을 클러스터링(그룹화)할 때 중요한 데이터로 활용됩니다.

## Proposed Changes

### [NEW] [callgraph_parser.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/00_extract/callgraph_parser.py)
`src/00_extract/callgraph_parser.py`를 신규 작성합니다. 주요 로직은 다음과 같습니다.

1. **XML 순회 및 파싱**
   - 앞서 만들어진 `cache/doxygen_json/{package}/xml/` 디렉터리의 `index.xml`을 로드하여 각 Compound(`class`, `struct`, `namespace`, `file`)의 `refid`를 추출합니다.
   - 각 `refid.xml` 파일 내에 존재하는 `<memberdef>` (주로 함수) 태그를 검색합니다.
   
2. **호출 관계 추출**
   - `<memberdef>` 하위에 있는 `<references>` 태그(현재 함수가 호출하는 대상)와 `<referencedby>` 태그(현재 함수를 호출하는 곳)를 찾습니다.
   - 각 관계의 대상이 되는 `refid` 및 실제 함수 이름 문자열을 추출합니다.

3. **JSON 산출 및 저장 필터링**
   - `private`나 `internal` 멤버는 이미 가이드 대상에서 제외되었으므로, 불필요한 호출 정보라면 제외하거나 단순히 이름표기로만 유지합니다. (최소화 목적)
   - 파싱 결과를 다음과 같은 형태로 조합하여 `cache/callgraph_json/{package}.json`에 저장합니다.
   ```json
   {
     "package": "dali-core",
     "call_graphs": {
       "Dali::Actor::Add": {
         "calls": ["Dali::Actor::GetImplementation"],
         "called_by": ["Dali::Renderer::SetActor"]
       }
     }
   }
   ```

## User Review Required

> [!IMPORTANT]
> - `callgraph_parser.py`의 결과 저장 경로로 `cache/callgraph_json/{package}.json`을 사용할 예정입니다.
> - 사용자의 지시를 정확히 따르기 위해 본 문서를 `dali-guide` 디렉토리 아래로 복사해두었습니다.
> - 룰에 의거하여, **본 Implementation Plan에 대한 검토 후 "이대로 진행해도 좋다"고 승인을 주시면 즉시 코딩을 시작하겠습니다.** (만약 승인 없이 바로 진행해도 된다는 의미이셨다면, 다시 한 번 확인차 "진행해"라고 말씀 부탁드립니다!)

## Verification Plan
1. `python src/00_extract/callgraph_parser.py`를 단독 실행.
2. `cache/callgraph_json/dali-core.json`이 정상적으로 생성되는지 확인.
3. 생성된 JSON 내에 호출 관계 데이터(`calls`, `called_by`)가 적어도 수십 개 이상의 항목으로 제대로 파싱되었는지 `grep` 및 크기를 통해 점검.
