이전 대화 내역을 완전히 무시하고 아래 내용만 고려해 줘

-------------------------------------------------------------------------------------------

AI 기반 다계층 C++ 라이브러리 가이드 문서 자동 생성 시스템

작업 배경
1. dali-core, dali-adaptor, dali-ui 구조로 구성된 ui-framework, ui-toolkit 라이브러리에 대해 md 형태의 가이드 문서를 작성해야 함.
2. dali-adaptor는 dali-core에 종속성이 있고, dali-ui는 dali-adaptor, dali-core에 종속성을 가지고 있음.
3. dali-core, dali-adaptor, dali-ui의 개발 언어는 C++
4. 각 API에는 doxygen으로 주석이 작성되어 있음.
5. 각 패키지마다 API 구성은 다음과 같음
  - public-api : 앱 개발자 및 platform 개발자가 사용할 수 있는 APIs
  - devel-api, integration-api : 앱 개발자는 사용할 수 없으며 inhouse platform 개발자가 사용할 수 있는 APIs (예를 들어 dali-adaptor는 dali-core의 public-api와 devel-api, integration-api를 사용할 수 있으며 dali-ui는 dali-core와 dali-adaptor의 public-api, devel-api, integration-api를 사용할 수 있음.)
  - devel-api는 향후 제거될 예정이지만 현재는 integration-api와 동일하게 취급
6. 각 패키지는 github에서 clone 가능
7. 각 가이드 문서는 일반 앱 개발자, 사내 Platform 개발자에게 공개되고 동시에 코드 어시스트용 mcp 서버에 업데이트 예정.

요구사항
1. 최초 1회 모든 기능에 대한 가이드 문서 작성
2. 그 이후로 변경사항에 대해 가이드 문서 추가 혹은 업데이트.
3. 변경사항 업데이트의 경우 github action 등으로 1주에 한번 실행 가능
4. 업데이트는 PR로 생성되며, 개발자 리뷰를 거쳐 merge 됨.
5. 가이드 문서는 LLM기반으로 자동생성됨.
6. API를 기반으로 작성되어야 하며, API사용시 유의사항이나 API 순서 등 로직과 관련된 부분에 대해 작성 필요.
7. public-api만 고려한 앱 개발자용 가이드 문서 외에, devel-api, integration-api를 고려한 사내 platform 개발자용 추가 가이드 문서가 별도로 나와야 함.

비기능 요구사항
1. 문서 정확도가 높아야 함.
2. 할루시네이션이 최소화되어야 함. (없는 내용을 만들어 작성하면 안됨)
3. 최대한 모든 API들을 커버할 수 있어야 함.
4. 토큰을 최대한 절약할 수 있는 방법이 고려되어 있어야 함.
5. 가이드 문서로 작성될 각 Feature는 사용자 관점에서 알기 쉽게 구성되어야 하며, Feature 생성과 코드파일-Feature간 매핑 등은 수동 작성을 배제하고 정적 분석(Call Graph/AST) 및 LLM을 활용하여 자동화한다.
6. 로컬 개발 환경(CLI) 및 CI/CD(GitHub Actions 등) 환경에서 모두 독립적으로 실행 가능해야 한다.
7. 정적 웹 호스팅(Docusaurus 등) 및 MCP 서버 연동에 최적화된 표준 Markdown(`.md`) 포맷 (메타데이터를 위한 Frontmatter 포함)으로 출력되어야 함.

제약사항
1. 변경사항 업데이트의 경우 사내 github에서 동작해야 하므로 사내 로컬 LLM API를 사용할 수 있어야 함.
2. 가이드 문서 작성 과정에서 dali-core, dali-adaptor, dali-ui의 코드는 전혀 수정되지 않아야 함.
3. 하나의 기능이 3개의 패키지를 관통하며 구현되어 있는 경우가 많으나, 가이드 문서의 경우 패키지를 구분하지 않고 전체를 고려하여 사용자 관점에서 작성되어야 함.

-------------------------------------------------------------------------------------------

 위와 같은 기능을 만들고자 해.

 이 때, 너도 알다시피 dali-core, dali-adaptor, dali-ui는 doxygen 주석이 api마다 달려있으므로 이것을 최대한 활용하면 좋을 거 같아.

 내가 알아볼 때 사내에서 쓸 수 있는 AI는 Intruct 모델과 Think 모델이 있어.

1. 기획: 전체 가이드 문서(목차) 및 핵심 예제 로직 설계 <- Think모델
2. 작성: 기능별 설명, 코드 스니펫, 파라미터 문서 초안 생성 <- Instruct모델
3. 검토: 논리적 허점, 사용 시나리오 누락, 가독성 검토 <- Think모델 

 두 종류의 모델을 이렇게 구분해서 사용할 수 있을 것이라고 하더라고.

  이러한 내용을 고려해서 이 시스템을 개발할 수 있는 전체 프로세스 플랜을 수립해줘.