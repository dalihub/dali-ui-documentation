# [ENH-28] Workflow 상태 관리 및 자동 머지 — cache 보존, 레포 분리 반영 흐름 재설계

## 개요

ENH-27에서 구성한 workflow는 매 실행이 fresh checkout이므로 weekly-update 실행 시
이전 실행의 `cache/` 데이터가 없어 매주 전체 재생성이 발생한다.

이를 해결하면서, 사용자가 생성된 문서를 점검·승인한 뒤 dali-guide_auto에 반영하는
전체 흐름을 재설계한다.

### 변경 후 전체 흐름

```
[weekly-update / initial-full-gen]
  │
  ├─ pipeline.py 실행 (cache/ 참조 — dali-ui-documentation main 기준)
  │
  └─ dali-ui-documentation에 PR 생성
       (변경 내용: cache/ + app-guide/ + platform-guide/)
            │
            ├─ [사용자 점검 후 수동 머지]
            │       └─ on-docs-merged.yml 트리거
            │               └─ app-guide/, platform-guide/만 dali-guide_auto에 push/PR
            │
            └─ [다음 weekly-update 실행 전까지 미머지 시]
                    └─ auto-approve.yml이 자동 머지
                            └─ on-docs-merged.yml 트리거 → dali-guide_auto 반영
```

---

## 작업 1: `weekly-update.yml` 및 `initial-full-gen.yml` — PR 대상을 dali-ui-documentation으로 변경

### 현재 상태 (ENH-27 결과)

pipeline 실행 후 생성된 docs를 `dali-guide_auto`에 직접 push + PR.

### 변경

pipeline 실행 후 `cache/`, `app-guide/`, `platform-guide/`를 **dali-ui-documentation 레포 자신에게** PR로 올린다.

- `GITHUB_TOKEN`으로 충분 (`DOCS_REPO_TOKEN` 불필요)
- 브랜치 이름:
  - weekly-update: `docs/weekly-update`
  - initial-full-gen: `docs/initial-full-{tier}`

```yaml
- name: Create PR to dali-ui-documentation
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    BRANCH="docs/weekly-update"   # initial-full의 경우 docs/initial-full-${TIER}

    git config user.name "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"

    git add dali-doc-gen/cache/ app-guide/ platform-guide/

    if [ -z "$(git status --porcelain)" ]; then
      echo "[skip] No changes. Skipping PR creation."
      exit 0
    fi

    git switch -C "$BRANCH"
    git commit -m "docs(auto): weekly incremental update"
    git push origin "$BRANCH" --force

    gh pr create \
      --title "docs(auto): Weekly Incremental Update Sync" \
      --body "Generated docs + cache state. Review and merge to publish to dali-guide_auto." \
      --base main \
      --head "$BRANCH" \
    || gh pr edit "$BRANCH" \
      --body "Generated docs + cache state. (updated: $(date -u +%Y-%m-%dT%H:%M:%SZ))"
```

#### cache 경로 주의사항

`pipeline.py`는 `dali-doc-gen/` 디렉터리 안에서 실행되고, cache는 `dali-doc-gen/cache/`에 생성된다.
git add 시 경로를 `dali-doc-gen/cache/`로 지정한다.

#### cache가 없는 경우 (5번 요구사항)

`pipeline.py` 내부에 이미 fallback 로직이 구현되어 있다.

```python
old_tax = load_json(TAXONOMY_OLD_PATH)
if not old_tax:
    needs_regen = set(new_tax.keys())  # 전체 재생성
    return needs_regen, needs_patch
```

`cache/`가 없으면 자동으로 전체 재생성이 수행되므로 별도 처리 불필요.

#### schedule 실행 시 Repository Variables fallback

schedule 트리거로 실행될 때 input이 없으므로, `Run Pipeline` 스텝에서 아래 Variables를 fallback으로 사용한다.

| Variable | 용도 | 미설정 시 기본값 |
|----------|------|-----------------|
| `DEFAULT_ENVIRONMENT` | LLM 환경 (`internal` / `external`) | `external` |
| `WEEKLY_TIER` | 처리할 tier | `all` |
| `WEEKLY_FEATURES` | 처리할 feature 목록 (콤마 구분) | 전체 (--features 미전달) |

`WEEKLY_FEATURES`가 설정되어 있으면 `--features`로 전달하고, 비어 있으면 전체 feature를 처리한다.

```yaml
- name: Run Pipeline (Update Mode)
  run: |
    TIER="${{ github.event.inputs.tier }}"
    TIER="${TIER:-${{ vars.WEEKLY_TIER }}}"
    TIER="${TIER:-all}"

    FEATURES="${{ github.event.inputs.target_features }}"
    FEATURES="${FEATURES:-${{ vars.WEEKLY_FEATURES }}}"

    cd dali-doc-gen
    ARGS="--mode update --tier $TIER"
    if [ -n "$FEATURES" ]; then
      ARGS="$ARGS --features $FEATURES"
    fi
    echo "Running: python src/pipeline.py $ARGS"
    python src/pipeline.py $ARGS
```

### 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `.github/workflows/weekly-update.yml` | `Push docs to dali-guide_auto` 스텝 → `Create PR to dali-ui-documentation` 스텝으로 교체, `WEEKLY_TIER`/`WEEKLY_FEATURES` Variables fallback 추가 |
| `.github/workflows/initial-full-gen.yml` | `Push docs to dali-guide_auto` 스텝 → `Create PR to dali-ui-documentation` 스텝으로 교체 |

---

## 작업 2: `on-docs-merged.yml` 신규 추가 — PR 머지 시 dali-guide_auto 반영

### 트리거 조건

dali-ui-documentation의 `docs/weekly-update` 또는 `docs/initial-full-*` 브랜치의 PR이 main에 머지될 때 실행.

```yaml
on:
  pull_request:
    types: [closed]
    branches: [main]

jobs:
  sync-to-guide:
    if: >
      github.event.pull_request.merged == true &&
      (startsWith(github.event.pull_request.head.ref, 'docs/weekly-update') ||
       startsWith(github.event.pull_request.head.ref, 'docs/initial-full-'))
    runs-on: ubuntu-latest
```

### 동작

1. main checkout (머지된 최신 상태)
2. `dali-guide_auto` 레포 checkout (`docs-output/` 경로)
3. `app-guide/`, `platform-guide/`만 복사 (cache는 제외)
4. 변경사항 있으면 브랜치 push + PR 생성 (또는 기존 PR 업데이트)

### 브랜치 이름 컨벤션 주의

이 workflow는 **브랜치 이름이 `docs/weekly-update` 또는 `docs/initial-full-*`인 PR이 머지될 때만** 동작한다.
개발자가 `app-guide/`, `platform-guide/`를 수동으로 수정하는 PR을 올릴 경우, 브랜치 이름을 `docs/` prefix로 짓지 않도록 한다. (`feature/`, `fix/` 등 사용)

```yaml
    steps:
      - name: Checkout dali-ui-documentation (merged state)
        uses: actions/checkout@v4

      - name: Checkout dali-guide_auto
        uses: actions/checkout@v4
        with:
          repository: dalihub/dali-guide_auto
          token: ${{ secrets.DOCS_REPO_TOKEN }}
          path: docs-output

      - name: Copy docs and create PR to dali-guide_auto
        env:
          GH_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
          DOCS_REPO_TOKEN: ${{ secrets.DOCS_REPO_TOKEN }}
          PR_BRANCH: ${{ github.event.pull_request.head.ref }}
        run: |
          rm -rf docs-output/app-guide docs-output/platform-guide
          [ -d app-guide/ ]      && cp -r app-guide/      docs-output/
          [ -d platform-guide/ ] && cp -r platform-guide/ docs-output/

          cd docs-output
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          git add .

          if [ -z "$(git status --porcelain)" ]; then
            echo "[skip] No changes to docs."
            exit 0
          fi

          if git ls-remote --heads origin | grep -q 'refs/heads/main'; then
            git switch -C "$PR_BRANCH"
            git commit -m "docs(auto): sync from dali-ui-documentation (${PR_BRANCH})"
            git push origin "$PR_BRANCH" --force
            gh pr create \
              --repo dalihub/dali-guide_auto \
              --title "docs: Sync from dali-ui-documentation (${PR_BRANCH})" \
              --body "Synced from merged PR in dali-ui-documentation." \
              --base main \
              --head "$PR_BRANCH" \
            || gh pr edit "$PR_BRANCH" \
              --repo dalihub/dali-guide_auto \
              --body "Synced from merged PR in dali-ui-documentation. (updated: $(date -u +%Y-%m-%dT%H:%M:%SZ))"
          else
            git switch -C main
            git commit -m "docs(auto): initial sync from dali-ui-documentation"
            git push origin main
          fi
```

### 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `.github/workflows/on-docs-merged.yml` | 신규 추가 |

---

## 작업 3: `auto-approve.yml` 신규 추가 — 다음 weekly-update 전 자동 머지

### 목적

사용자가 weekly-update PR을 다음 주 실행 전까지 머지하지 않은 경우, 자동으로 머지하여
on-docs-merged.yml을 통해 dali-guide_auto에 반영.

### 트리거

weekly-update cron(`0 0 * * 1`, 매주 월 00:00 UTC) 실행 **1시간 전**인
**매주 일요일 23:00 UTC**에 실행.

```yaml
on:
  schedule:
    - cron: '0 23 * * 0'   # 매주 일요일 23:00 UTC
  workflow_dispatch:        # 수동 테스트용
```

### 동작

`docs/weekly-update` 브랜치의 열린 PR을 찾아 `gh pr merge`로 squash 머지.

```yaml
jobs:
  auto-merge:
    runs-on: ubuntu-latest
    steps:
      - name: Auto-merge pending docs PR
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          PR_NUMBER=$(gh pr list \
            --repo dalihub/dali-ui-documentation \
            --head docs/weekly-update \
            --state open \
            --json number \
            --jq '.[0].number')

          if [ -z "$PR_NUMBER" ]; then
            echo "[skip] No open docs/weekly-update PR found."
            exit 0
          fi

          echo "[auto-merge] Merging PR #${PR_NUMBER}..."
          gh pr merge "$PR_NUMBER" \
            --repo dalihub/dali-ui-documentation \
            --squash \
            --subject "docs(auto): weekly update auto-merge" \
            --delete-branch
```

### 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `.github/workflows/auto-approve.yml` | 신규 추가 |

---

## 전체 영향 범위 요약

| 파일 | 작업 | 변경 종류 |
|------|------|-----------|
| `.github/workflows/weekly-update.yml` | 1 | 수정 |
| `.github/workflows/initial-full-gen.yml` | 1 | 수정 |
| `.github/workflows/on-docs-merged.yml` | 2 | 신규 |
| `.github/workflows/auto-approve.yml` | 3 | 신규 |

## 작업 순서

작업 1 → 작업 2 → 작업 3

- 작업 2, 3은 병렬 진행 가능
