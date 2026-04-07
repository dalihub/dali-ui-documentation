# TODO

## 미완료

- [ ] `doxygen_parser.py` — namespace compound에서 enum memberdef를 synthetic compound로 추출, enumvalue 자식 포함
- [ ] `feature_clusterer.py` — synthetic enum compound의 file 경로로 feature 라우팅
  - 설계 문서: [devel-note/Enhancing/ENH-11_enum_only_feature_hallucination_fix.md](../devel-note/Enhancing/ENH-11_enum_only_feature_hallucination_fix.md)

- [ ] **Docusaurus 사이트 구성**
  - `app-guide/`, `platform-guide/` 디렉토리에 Docusaurus 프로젝트 초기화
  - 파이프라인 출력(마크다운, sidebar.json)을 자동으로 Docusaurus `docs/` 폴더에 반영하는 연동 방식 결정
  - MCP 서버 연동 설계

---

## 완료

- [x] **Stage B 프롬프트 — Overview 섹션 고정**
  - 첫 번째 TOC 항목을 항상 `"Overview"`로 강제, 섹션 수(3~10) 계산에서 제외
  - 효과: 모든 생성 문서의 서두에 균일하게 개요 섹션 존재

- [x] **Stage C 프롬프트 — 인문서 목차(TOC) 제거**
  - 일반 생성 프롬프트 및 rolling refinement 첫 패스 모두에 TOC 금지 지시 추가
  - 효과: Docusaurus가 자동 생성하는 사이드바 TOC와 중복 제거, 문서 균일성 확보

- [x] **`index_generator.py` — Stage D FAIL 문서의 잘못된 링크 생성 버그 수정**
  - `doc_exists()` 함수가 Stage D 리포트 존재 시 `validated_drafts/`만 신뢰하도록 수정
  - 기존: `markdown_drafts/`의 stale `.md`를 보고 링크 생성 → `app-guide/`에 파일 없어 링크 깨짐
  - 수정 후: Stage D가 실행된 경우 `validated_drafts/`에 없는 파일은 링크 생성 안 함

- [x] **`index_generator.py` — `flat_roots` unused 변수 제거**
