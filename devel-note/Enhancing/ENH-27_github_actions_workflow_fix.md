# [ENH-27] GitHub Actions Workflow 수정 — Secret 누락, Runner 분기, Docs 레포 분리

## 개요

세 개의 workflow(`initial-full-gen.yml`, `weekly-update.yml`, `e2e-update-test.yml`)를 분석한 결과 발견된 문제들을 수정한다.

1. **`INTERNAL_API_KEY` secret 누락 (e2e)** — `e2e-update-test.yml`의 pipeline 실행 스텝에 `INTERNAL_API_KEY`가 주입되지 않아 `internal` 환경 선택 시 인증 실패
2. **Runner 환경별 분기** — `external` 환경에서는 GitHub-hosted runner(`ubuntu-latest`)를, `internal` 환경에서는 self-hosted runner(`code-large`)를 사용
3. **Docs 별도 레포 분리 + PR 생성 로직 개선** — workflow 실행 시 생성된 docs를 별도 레포의 브랜치에 push하여 PR 생성. 로컬 실행은 기존 동작 유지.

---

## 작업 1: `e2e-update-test.yml` `INTERNAL_API_KEY` 누락 수정

### 문제

`Run Full Generation` 및 `Run Incremental Update` 스텝의 `env`에 `GEMINI_API_KEY`만 있고 `INTERNAL_API_KEY`가 없다. `environment: internal` 선택 시 API 인증이 실패한다.

```yaml
# 현재 (누락 상태)
- name: Run Full Generation
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  run: ...
```

### 해결

두 pipeline 실행 스텝 모두에 `INTERNAL_API_KEY`를 추가한다.

```yaml
- name: Run Full Generation
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
    INTERNAL_API_KEY: ${{ secrets.INTERNAL_API_KEY }}
  run: ...

- name: Run Incremental Update
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
    INTERNAL_API_KEY: ${{ secrets.INTERNAL_API_KEY }}
  run: ...
```

### 영향 범위

| 파일 | 스텝 |
|------|------|
| `.github/workflows/e2e-update-test.yml` | `Run Full Generation`, `Run Incremental Update` |

---

## 작업 2: Runner 환경별 분기

### 현재 상태

세 workflow 모두 `runs-on: code-large`로 하드코딩되어 있어, `external` 환경을 선택해도 self-hosted runner로 실행된다.

### 해결

`runs-on`에 expression을 사용하여 `environment` input 값에 따라 runner를 동적으로 선택한다.

```yaml
jobs:
  generate-docs:  # 또는 update-docs, e2e-test
    runs-on: ${{ github.event.inputs.environment == 'internal' && 'code-large' || 'ubuntu-latest' }}
```

#### `weekly-update.yml` 특이사항

`schedule` 트리거로 실행될 때는 `github.event.inputs.environment`가 빈 문자열이다. `runs-on`은 job 레벨에서 결정되므로 스텝 안의 fallback 로직과 별개로 처리해야 한다.

Repository Variable `DEFAULT_ENVIRONMENT`가 `internal`이면 `code-large`, 그 외(또는 미설정)이면 `ubuntu-latest`로 동작한다.

```yaml
jobs:
  update-docs:
    runs-on: >-
      ${{
        (github.event.inputs.environment == 'internal' ||
         (github.event.inputs.environment == '' && vars.DEFAULT_ENVIRONMENT == 'internal'))
        && 'code-large' || 'ubuntu-latest'
      }}
```

### 영향 범위

| 파일 | 변경 위치 |
|------|-----------|
| `.github/workflows/initial-full-gen.yml` | `jobs.generate-docs.runs-on` |
| `.github/workflows/weekly-update.yml` | `jobs.update-docs.runs-on` (schedule fallback 포함) |
| `.github/workflows/e2e-update-test.yml` | `jobs.e2e-test.runs-on` |

---

## 작업 3: Docs 별도 레포 분리 + PR 생성 로직 개선

### 설계 원칙

- **로컬 실행**: `pipeline.py`를 직접 실행하면 기존과 동일하게 `app-guide/`, `platform-guide/`를 이 레포 안에 생성한다. 변경 없음.
- **workflow 실행**: pipeline 실행 후 생성된 docs를 별도 docs 레포의 새 브랜치에 push하고 PR을 올린다. 이 레포에는 docs 파일 커밋이 쌓이지 않는다.

### docs 레포 구조

```
dalihub/dali-guide_auto          ← docs 전용 레포
  ├── app-guide/
  │   └── docs/
  └── platform-guide/
      └── docs/
```

default 브랜치는 `main`. 레포에 `main` 브랜치가 없는 경우 최초 push 시 생성한다.

### 사전 준비

1. 이 레포(`dali-ui-documentation`)의 Secrets에 `DOCS_REPO_TOKEN` 추가
   - `dalihub/dali-guide_auto`에 `contents: write` 권한을 가진 PAT 또는 GitHub App 토큰
   - `GITHUB_TOKEN`은 같은 org의 다른 레포에는 push 불가이므로 별도 토큰 필요

### workflow 변경 — `Create Pull Request` 스텝 교체

기존 스텝을 아래 두 스텝으로 교체한다.

```yaml
- name: Checkout docs repository
  uses: actions/checkout@v4
  with:
    repository: dalihub/dali-guide_auto
    token: ${{ secrets.DOCS_REPO_TOKEN }}
    path: docs-output

- name: Push docs and create PR
  env:
    GH_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
  run: |
    # 생성된 docs를 docs 레포 작업 디렉터리로 복사
    cp -r app-guide/   docs-output/app-guide/
    cp -r platform-guide/ docs-output/platform-guide/

    cd docs-output
    git config user.name "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"

    git add app-guide/ platform-guide/

    # 변경사항 없으면 skip
    if git diff --cached --quiet; then
      echo "[skip] No changes to docs. Skipping PR creation."
      exit 0
    fi

    # 브랜치 생성 (이미 있으면 reset)
    BRANCH="docs/weekly-update"    # initial-full의 경우 docs/initial-full-${{ github.event.inputs.tier }}
    git switch -C "$BRANCH"
    git commit -m "docs(auto): weekly incremental update"
    git push origin "$BRANCH" --force

    # PR 생성 — 이미 존재하면 본문 업데이트
    gh pr create \
      --repo dalihub/dali-guide_auto \
      --title "docs(auto): Weekly Incremental Update Sync" \
      --body "Automated PR from weekly-update pipeline." \
      --base main \
      --head "$BRANCH" \
    || gh pr edit "$BRANCH" \
      --repo dalihub/dali-guide_auto \
      --body "Automated PR from weekly-update pipeline. (updated: $(date -u +%Y-%m-%dT%H:%M:%SZ))"
```

### 핵심 포인트

| 항목 | 설명 |
|------|------|
| `git switch -C` | 브랜치 있으면 reset, 없으면 신규 생성. 기존 `git checkout -b` 실패 원인 해결 |
| `git diff --cached --quiet` 로 변경 감지 | 변경 없을 때 push/PR 시도 전체 skip |
| `gh pr create \|\| gh pr edit` | PR 없으면 생성, 이미 있으면 본문 업데이트. `\|\| echo` 로 실패를 묻어버리는 기존 방식 제거 |
| `DOCS_REPO_TOKEN` | 별도 레포 push를 위한 전용 토큰. `GITHUB_TOKEN`과 분리 |
| 로컬 실행 무영향 | `app-guide/`, `platform-guide/` 생성 위치 변경 없음 |

### `e2e-update-test.yml` 처리

e2e workflow는 결과를 `artifact`로 업로드하는 구조이므로 docs 레포 push 대상에서 **제외**한다. 현재의 artifact 업로드 방식을 유지한다.

### 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `.github/workflows/initial-full-gen.yml` | `Create Pull Request` 스텝 → docs 레포 checkout + push/PR 스텝 2개로 교체 |
| `.github/workflows/weekly-update.yml` | `Create Pull Request` 스텝 → docs 레포 checkout + push/PR 스텝 2개로 교체 |
| `.github/workflows/e2e-update-test.yml` | 변경 없음 (artifact 업로드 유지) |

---

## 전체 영향 범위 요약

| 파일 | 작업 |
|------|------|
| `.github/workflows/initial-full-gen.yml` | 2, 3 |
| `.github/workflows/weekly-update.yml` | 2, 3 |
| `.github/workflows/e2e-update-test.yml` | 1, 2 |

## 사전 준비 사항

구현 시작 전 완료가 필요한 항목:

| 항목 | 내용 |
|------|------|
| docs 레포 | `dalihub/dali-guide_auto` — default 브랜치 `main` (없으면 최초 push 시 생성) |
| `DOCS_REPO_TOKEN` | `dali-ui-documentation` Secrets에 등록 — `dalihub/dali-guide_auto`에 `contents: write` 권한을 가진 PAT |

## 작업 순서

작업 1 (e2e secret) → 작업 2 (runner 분기) → [docs 레포 생성 + 토큰 발급] → 작업 3 (docs 레포 분리)

- 작업 1, 2는 docs 레포 결정과 무관하게 바로 진행 가능
- 작업 3은 docs 레포 이름 확정 후 진행
