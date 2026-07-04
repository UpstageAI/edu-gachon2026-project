# 가천대 2026 교육 프로젝트 제출 Repository

이 저장소는 **가천대학교 2026 교육 프로그램**의 팀별 최종 프로젝트 제출·아카이빙을 위한 repository입니다.

각 팀은 `projects/` 아래에 자신의 팀 폴더를 만들고, Pull Request(PR)로 제출합니다. 프로젝트 내부 구조와 기술 스택은 자유롭게 구성할 수 있지만, 제출 폴더명과 기본 설명 파일은 아래 규칙을 따라주세요.

---

## 1. 제출 구조

각 팀은 `projects/` 아래에 하나의 팀 폴더만 만들어 제출합니다.

```text
projects/team01-project-name/
projects/team02-project-name/
projects/team12-ai-agent/
```

팀 폴더명은 아래 형식을 사용합니다.

```text
teamNN-project-name
```

규칙:

- `NN`은 두 자리 팀 번호입니다. 예: `01`, `02`, `12`, `60`
- `project-name`은 영어 소문자, 숫자, hyphen(`-`)만 사용합니다.
- 공백, 한글, 특수문자는 사용하지 않습니다.

각 팀 폴더에는 아래 파일을 넣어주세요.

```text
projects/team01-project-name/
├── README.md
├── project.yml
└── 실제 프로젝트 파일들...
```

- `README.md`: 사람이 읽는 프로젝트 설명서입니다.
- `project.yml`: 자동 검증, 프로젝트 목록 생성, 블로그/회고 글 초안 생성에 사용할 제출 정보 카드입니다.

---

## 2. 팀별 README.md 작성 안내

팀별 `README.md`에는 아래 섹션을 넣어주세요.

아래 섹션 중 일부는 자동 검증에서 필수로 확인될 수 있고, 일부는 선택 항목으로 둘 수 있습니다. 현재 template에서는 `데모 영상`, `참고자료 / 발표자료`를 optional로 둘 수 있게 설정되어 있습니다.

권장 섹션:

1. 프로젝트 소개
2. 문제 정의
3. 문제 해결
4. 핵심 기능
5. 데모 영상
6. 팀원 소개
7. 참고자료 / 발표자료

템플릿 파일을 복사해서 작성하면 됩니다.

```bash
cp templates/TEAM_README_TEMPLATE.md projects/team01-project-name/README.md
```

템플릿 위치:

```text
templates/TEAM_README_TEMPLATE.md
```

---

## 3. project.yml 작성 안내

`project.yml`은 프로젝트 정보를 기계가 읽기 쉬운 형태로 정리한 파일입니다.

이 파일은 다음 용도로 사용될 수 있습니다.

- 제출 형식 자동 검증
- 전체 프로젝트 목록 자동 생성
- 블로그/회고 글 초안 생성
- 기술 스택 및 프로젝트 주제 분석

템플릿 파일을 복사해서 작성하면 됩니다.

```bash
cp templates/project.yml projects/team01-project-name/project.yml
```

템플릿 위치:

```text
templates/project.yml
```

---

## 4. 프로젝트 파일 복사 방법

프로젝트를 복사할 때 내부 `.git` 폴더는 제출하지 마세요.

`.git`까지 복사하면 GitHub에서 실제 파일이 아니라 submodule/gitlink처럼 등록되어, merge 후 파일이 보이지 않거나 검토가 어려워질 수 있습니다.

권장 복사 방법:

```bash
# 팀 폴더 생성
mkdir -p projects/team01-project-name

# 프로젝트 파일 복사: 내부 .git 제외
rsync -av --exclude='.git' /path/to/your-project/ projects/team01-project-name/
```

---

## 5. Pull Request 제출 방법

Git이 처음이어도 아래 순서대로 진행하면 됩니다.

### Step 1. 이 저장소를 Fork 하세요

GitHub 페이지 우측 상단의 **Fork** 버튼을 클릭하면 자신의 GitHub 계정에 동일한 저장소가 복사됩니다.

> Fork는 원본 저장소를 내 계정으로 복사하는 것입니다. 원본에 직접 영향을 주지 않으니 안심하세요.

### Step 2. Fork한 저장소를 로컬에 Clone 하세요

```bash
git clone https://github.com/<내-GitHub-아이디>/<이-저장소-이름>.git
cd <이-저장소-이름>
```

예시:

```bash
git clone https://github.com/my-github-id/project-submission-repo.git
cd project-submission-repo
```

### Step 3. 팀 폴더를 만들고 프로젝트를 넣으세요

```bash
mkdir -p projects/team01-project-name
rsync -av --exclude='.git' /path/to/your-project/ projects/team01-project-name/
cp templates/TEAM_README_TEMPLATE.md projects/team01-project-name/README.md
cp templates/project.yml projects/team01-project-name/project.yml
```

그 다음 `README.md`와 `project.yml`을 자신의 프로젝트에 맞게 수정하세요.

### Step 4. Commit & Push 하세요

```bash
git add projects/team01-project-name
git commit -m "[Team 01] 프로젝트 제출 - project-name"
git push origin main
```

### Step 5. Pull Request를 만드세요

1. GitHub에서 자신의 Fork 저장소로 이동합니다.
2. 상단에 나타나는 **Contribute** 버튼을 클릭합니다.
3. **Open pull request**를 클릭합니다.
4. PR 제목을 아래 형식으로 작성합니다.

```text
[Team 01] 프로젝트 제출 - project-name
```

5. **Create pull request**를 클릭하면 제출 완료입니다.

PR이 생성되면 자동 검증이 실행됩니다. 검증에 실패하면 GitHub Actions 로그를 보고 수정한 뒤 다시 push하면 됩니다.

---

## 6. 제출하지 말아야 할 파일/폴더

아래 파일/폴더는 제출하지 마세요.

- `.git/`
- `.gitmodules`
- `.env`
- `node_modules/`
- `.venv/`
- `dist/`
- `build/`
- `__pycache__/`
- 매우 큰 파일

필요한 환경 변수는 `.env` 대신 `.env.example`에 예시 형태로 작성해주세요.

---

## 7. 자동 검증 기준

PR이 올라오면 GitHub Actions가 아래 항목을 확인합니다.

- 팀 폴더명이 `teamNN-project-name` 형식인지
- 팀 폴더 안에 `README.md`가 있는지
- 팀 폴더 안에 `project.yml`이 있는지
- required README 섹션이 있는지
- `project.yml`의 필수 필드가 작성되어 있는지
- `.gitmodules`, nested `.git`, submodule/gitlink가 없는지
- 금지 파일/폴더가 없는지
- 파일 크기가 제한을 넘지 않는지

README 섹션의 required/optional 여부는 운영자가 아래 파일에서 조정할 수 있습니다.

```text
.github/submission-policy.yml
```

---

## 8. 자동 검증 실패 시 자주 나오는 해결 방법

### `.git` 또는 submodule 관련 오류

```bash
git rm --cached -r projects/team01-project-name
rm -rf projects/team01-project-name/.git
git add projects/team01-project-name
git commit -m "Fix team01 submission files"
git push
```

### `.env` 파일 제출 오류

```bash
mv projects/team01-project-name/.env projects/team01-project-name/.env.example
git add projects/team01-project-name/.env.example
git rm --cached projects/team01-project-name/.env
git commit -m "Replace .env with .env.example"
git push
```

### README 섹션 누락 오류

`templates/TEAM_README_TEMPLATE.md`를 참고해서 누락된 섹션을 추가해주세요.
