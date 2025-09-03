# Xray Test Case Exporter

Jira Xray Cloud에서 테스트 케이스를 JQL 쿼리로 조회하여, 각 테스트의 상세 정보(스텝, 전제조건 등)를 Excel 파일로 추출하는 스크립트입니다.

## 사전 준비

*   Python 3.x
*   pip (Python 패키지 관리자)

## 설치

스크립트 실행에 필요한 라이브러리를 설치합니다.

```bash
pip install requests pandas openpyxl python-dotenv tqdm
```

## 설정 (`.env` 파일)

프로젝트 루트 디렉터리에 `.env` 라는 파일을 생성하고 아래 내용을 채워넣어야 합니다. 이 파일은 민감한 정보(API 키 등)를 코드와 분리하여 안전하게 관리하기 위해 사용됩니다.

```
# Xray API 인증 정보
XRAY_CLIENT_ID="여기에_XRAY_CLIENT_ID를_입력하세요"
XRAY_CLIENT_SECRET="여기에_XRAY_CLIENT_SECRET를_입력하세요"

# 조회할 테스트 케이스를 선택하는 JQL 쿼리
JIRA_JQL="project = 'YOUR_PROJECT' AND issuetype = Test"
```

**설정 항목 설명:**

*   `XRAY_CLIENT_ID` / `XRAY_CLIENT_SECRET`: Xray API에 접근하기 위한 인증 정보입니다. Jira 관리자 또는 Xray 설정 페이지에서 발급받을 수 있습니다.
*   `JIRA_JQL`: 추출할 테스트 케이스를 필터링하기 위한 JQL(Jira Query Language) 쿼리입니다. 위 예시처럼 프로젝트 키를 지정하거나, 특정 라벨, 상태 등을 기준으로 쿼리를 작성할 수 있습니다.

## 사용법

### 테스트 케이스 추출

아래 명령어를 실행하면 `.env` 파일의 `JIRA_JQL` 에 해당하는 테스트 케이스를 조회하여 `xray_tests.xlsx` 파일로 저장합니다.

```bash
python xray_export.py
```

다른 이름으로 파일을 저장하고 싶다면 `--outfile` 옵션을 사용하세요.

```bash
python xray_export.py --outfile My_Test_Cases.xlsx
```

### 커스텀 필드 ID 진단

엑셀에 '컴포넌트'와 같은 특정 커스텀 필드를 추가하고 싶지만 필드의 ID (`customfield_xxxxx`)를 모를 경우, 아래 명령어를 사용하여 진단 파일을 생성할 수 있습니다.

```bash
python xray_export.py --diagnose-fields
```

이 명령어는 `field_diagnostics.xlsx` 라는 파일을 생성합니다. 이 파일을 열어보면 JQL로 조회된 테스트 몇 개의 각 커스텀 필드 ID와 실제 값이 표시되어 있어, 원하는 필드의 ID를 쉽게 찾을 수 있습니다.

## 커스터마이징

### 엑셀에 커스텀 필드 추가하기

진단 기능을 통해 찾은 커스텀 필드 ID를 `xray_export.py` 스크립트 상단에 있는 `CUSTOM_FIELDS_TO_EXPORT` 딕셔너리에 추가하여 엑셀 출력에 포함시킬 수 있습니다.

예를 들어, '담당자' 필드의 ID가 `customfield_10200` 이라면 아래와 같이 수정합니다.

```python
# xray_export.py 파일 상단

CUSTOM_FIELDS_TO_EXPORT = {
    "customfield_10138": "Components",
    "customfield_10200": "담당자",  # 원하는 컬럼 이름으로 지정
}
```
