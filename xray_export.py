#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Xray Cloud에서 JQL로 Test들을 조회해
각 Step의 Precondition / Action / Expected Result와
(필요 시) 이슈 단위 Precondition(정의)까지 엑셀로 저장.

pip install requests pandas openpyxl python-dotenv
사용 예:
python xray_export_steps_precond.py \
  --outfile xray_tests.xlsx
"""

import argparse
import sys
import time
import os
from typing import Dict, List, Any
import requests
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

# .env 파일에서 환경 변수 로드
load_dotenv()

# --------------------------------------------------------------------
# ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
# 엑셀에 추가할 사용자 정의 필드를 설정합니다.
# 형식: "customfield_ID": "엑셀에 표시할 컬럼 이름"
# ID를 모를 경우, 터미널에서 `python xray_export.py --diagnose-fields` 명령을 실행하여 찾으세요.
CUSTOM_FIELDS_TO_EXPORT = {
    "customfield_10138": "Components",
    "customfield_10167": "Custom Field 2",  # 이 필드의 컬럼명을 원하시는 이름으로 변경하세요.
}
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
# --------------------------------------------------------------------

XRAY_AUTH = "https://xray.cloud.getxray.app/api/v2/authenticate"
XRAY_GRAPHQL = "https://xray.cloud.getxray.app/api/v2/graphql"

# ❗steps에 data가 없고 precondition/action/result만 있는 스키마에 맞춤
GQL_GET_TESTS = """
query ($jql: String!, $limit: Int!, $start: Int!) {
  getTests(jql: $jql, limit: $limit, start: $start) {
    total
    start
    limit
    results {
      jira(fields: ["*all"])
      steps { id action result customFields { name value } }
      # 아래는 이슈 단위 Precondition 이슈(선택적으로 엑셀에 함께 표시하려고 유지)
      preconditions(limit: 50) {
        results {jira(fields:["key","summary"]) definition }
      }
    }
  }
}
""".strip()

def get_token(client_id: str, client_secret: str, timeout: int = 30) -> str:
    """Xray 인증 API를 호출하여 토큰을 받아옵니다."""
    r = requests.post(XRAY_AUTH, json={"client_id": client_id, "client_secret": client_secret}, timeout=timeout)
    r.raise_for_status()
    token = r.json()
    if not isinstance(token, str):
        raise RuntimeError(f"Unexpected token response: {token}")
    return token

def gql(session: requests.Session, token: str, query: str, variables: Dict[str, Any], timeout: int = 60) -> Dict:
    """GraphQL API를 실행하고 결과를 반환합니다."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = session.post(XRAY_GRAPHQL, headers=headers, json={"query": query, "variables": variables}, timeout=timeout)
    resp.raise_for_status()
    j = resp.json()
    if "errors" in j:
        raise RuntimeError(j["errors"])
    return j["data"]

def fetch_all_tests(token: str, jql: str, limit: int = 100, sleep_sec: float = 0.2) -> List[Dict]:
    """JQL에 해당하는 모든 테스트 이슈를 가져옵니다."""
    s = requests.Session()
    out: List[Dict] = []
    start = 0
    try:
        # 첫 페이지를 가져와서 전체 개수를 확인
        data = gql(s, token, GQL_GET_TESTS, {"jql": jql, "limit": limit, "start": start})["getTests"]
    except Exception as e:
        print(f"Error fetching first page: {e}", file=sys.stderr)
        return []

    total = data.get("total", 0)
    if not total:
        return []

    batch = data.get("results") or []
    out.extend(batch)
    start += data.get("limit", limit)

    with tqdm(total=total, desc="   Fetching tests", unit=" tests", initial=len(batch)) as pbar:
        while start < total and batch:
            data = gql(s, token, GQL_GET_TESTS, {"jql": jql, "limit": limit, "start": start})["getTests"]
            batch = data.get("results") or []
            out.extend(batch)
            pbar.update(len(batch))
            start += data.get("limit", limit)
            time.sleep(sleep_sec)
    return out

def _format_jira_field_value(value: Any) -> str:
    """Formats a Jira custom field value (e.g., dropdown) into a displayable string."""
    if isinstance(value, dict) and 'value' in value:
        # 단일 선택 드롭다운: {'value': '선택값'}
        return str(value.get('value', ''))
    elif isinstance(value, list):
        # 다중 선택 드롭다운: [{'value': '선택값1'}, {'value': '선택값2'}]
        str_values = []
        for item in value:
            if isinstance(item, dict) and 'value' in item:
                str_values.append(str(item.get('value', '')))
            else:
                str_values.append(str(item))
        return ", ".join(filter(None, str_values))
    elif value:
        # 기타 단순 값 (e.g., 텍스트 필드)
        return str(value)
    return ""

def flatten_rows(tests: List[Dict]) -> List[Dict[str, Any]]:
    """Xray 테스트 데이터를 엑셀 행으로 변환합니다."""
    rows: List[Dict[str, Any]] = []
    for test in tests:
        jira_info = test.get("jira") or {}
        labels = jira_info.get("labels") or []

        # 설정된 사용자 정의 필드들의 값을 가져옵니다.
        custom_field_values = {}
        for field_id, col_name in CUSTOM_FIELDS_TO_EXPORT.items():
            field_value = jira_info.get(field_id)
            custom_field_values[col_name] = _format_jira_field_value(field_value)
 
        # 이슈 단위 Precondition(있으면 참고용으로 묶어서 한 셀에)
        precondition_results = (test.get("preconditions") or {}).get("results") or []
        pre_titles_list: List[str] = []
        pre_defs_list: List[str] = []
        for p in precondition_results:
            if not p:
                continue
            pre_jira = p.get("jira") or {}
            pre_key = pre_jira.get("key")
            pre_summary = pre_jira.get("summary")
            if pre_key and pre_summary:
                pre_titles_list.append(f"{pre_key} - {pre_summary}")

            definition = p.get("definition")
            if definition:
                # Normalize whitespace
                normalized_def = ' '.join(definition.split())
                pre_defs_list.append(normalized_def)

        base_row = {
            "Test Key": jira_info.get("key", ""),
            "Summary": jira_info.get("summary", ""),
            "Labels": ", ".join(labels),
            **custom_field_values,
            "Issue Preconditions (keys & titles)": "; ".join(pre_titles_list),
            "Issue Preconditions Definition": " | ".join(pre_defs_list),
        }

        # ❗스텝: precondition/action/result만 사용
        steps = test.get("steps") or []
        if not steps:
            rows.append({**base_row, "Step #": "", "Step Precondition": "", "Action": "", "Expected Result": ""})
        else:
            for idx, step in enumerate(steps, start=1):
                # 스텝의 커스텀 필드에서 'precondition' 찾기
                step_precondition = ""
                custom_fields = step.get("customFields") or []
                for cf in custom_fields:
                    if cf and cf.get("name", "").lower() == "precondition":
                        step_precondition = cf.get("value") or ""
                        break
                rows.append({
                    **base_row,
                    "Step #": idx,
                    "Step Precondition": step_precondition.strip(),
                    "Action": (step.get("action") or "").strip(),
                    "Expected Result": (step.get("result") or "").strip(),
                })
    return rows

def run_field_diagnostics(token: str, jql: str):
    """사용자 정의 필드 ID를 찾기 위한 진단 파일을 생성합니다."""
    print("\n[Running Field Diagnostics]")
    print("[1/3] Fetching a few sample tests...")
    s = requests.Session()
    try:
        # 전체가 아닌 한 페이지만 가져오도록 수정
        data = gql(s, token, GQL_GET_TESTS, {"jql": jql, "limit": 5, "start": 0})["getTests"]
        tests = data.get("results") or []
    except Exception as e:
        print(f"Error fetching sample tests: {e}", file=sys.stderr)
        sys.exit(1)

    if not tests:
        print("오류: JQL에 해당하는 테스트를 찾을 수 없습니다. 진단을 진행할 수 없습니다.", file=sys.stderr)
        sys.exit(1)
    print(f" -> {len(tests)} tests fetched for diagnosis.")

    print("[2/3] Analyzing custom fields...")
    diag_data = {}

    # 가져온 모든 테스트에서 customfield 키를 수집하여 누락 방지
    all_custom_field_ids = {k for test in tests for k in test.get("jira", {}).keys() if k.startswith("customfield_")}
    custom_field_ids = sorted(list(all_custom_field_ids))

    # 각 테스트의 키와 값을 수집
    for test in tests:
        jira_info = test.get("jira", {})
        test_key = jira_info.get("key", "N/A")

        for field_id in custom_field_ids:
            if field_id not in diag_data:
                diag_data[field_id] = {}

            value = jira_info.get(field_id)
            diag_data[field_id][test_key] = _format_jira_field_value(value)

    print("[3/3] Writing diagnostic Excel file...")
    df = pd.DataFrame.from_dict(diag_data, orient='index')
    df.index.name = "Field ID"
    df.reset_index(inplace=True)

    outfile = "field_diagnostics.xlsx"
    df.to_excel(outfile, index=False)
    print("\n--- 진단 완료 ---")
    print(f"파일 '{outfile}'이 생성되었습니다.")
    print("엑셀 파일을 열어 각 'Field ID' 행의 값들을 확인하고, '컴포넌트'에 해당하는 ID를 찾으세요.")
    print(f"찾은 ID를 스크립트 상단의 'COMPONENT_FIELD_ID' 변수에 복사하여 붙여넣으세요.")

def main():
    """메인 함수"""
    ap = argparse.ArgumentParser(description="Export Xray Tests (steps: precondition/action/result) to XLSX")
    ap.add_argument("--outfile", default="xray_tests.xlsx", help="Output file name (default: xray_tests.xlsx)")
    ap.add_argument("--limit", type=int, default=100, help="Number of tests to fetch per request (default: 100)")
    ap.add_argument("--diagnose-fields", action="store_true", help="Create a diagnostic file to help find custom field IDs.")
    args = ap.parse_args()

    # .env에서 설정 값들을 가져오고, 앞뒤 공백과 따옴표를 제거하여 안정성을 높임
    client_id = (os.getenv("XRAY_CLIENT_ID") or "").strip().strip("'\"")
    client_secret = (os.getenv("XRAY_CLIENT_SECRET") or "").strip().strip("'\"")
    jql = (os.getenv("JIRA_JQL") or "").strip()

    if not client_id or not client_secret:
        print("오류: .env 파일에 XRAY_CLIENT_ID와 XRAY_CLIENT_SECRET이 정의되어야 합니다.", file=sys.stderr)
        sys.exit(1)
    if not jql:
        print("오류: .env 파일에 JIRA_JQL이 정의되어야 합니다.", file=sys.stderr)
        sys.exit(1)

    print(f"Using Client ID: {client_id[:4]}...{client_id[-4:]}")
    print(f"Using JQL: {jql}")
    print("[1/3] Authenticating...")
    token = get_token(client_id, client_secret)
    print(" -> OK")

    if args.diagnose_fields:
        run_field_diagnostics(token, jql)
        sys.exit(0)

    print("[2/3] Fetching tests...")
    tests = fetch_all_tests(token, jql, limit=args.limit)
    print(f" -> {len(tests)} test issues fetched")

    print("[3/3] Writing Excel...")
    rows = flatten_rows(tests)
    df = pd.DataFrame(
        rows,
        columns=[
            "Test Key", "Summary", "Labels",
            *CUSTOM_FIELDS_TO_EXPORT.values(),  # 설정된 사용자 정의 필드 컬럼들을 동적으로 추가
            "Step #",
            "Step Precondition", "Action", "Expected Result",
            "Issue Preconditions (keys & titles)", "Issue Preconditions Definition",
        ],
    )

    with pd.ExcelWriter(args.outfile, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Xray Tests", index=False)
        ws = writer.sheets["Xray Tests"]
        # 간단 열폭 조정
        for col_cells in ws.columns:
            max_len = 10
            letter = col_cells[0].column_letter
            for c in col_cells:
                v = "" if c.value is None else str(c.value)
                if len(v) > max_len:
                    max_len = len(v)
            ws.column_dimensions[letter].width = min(max_len + 2, 80)

    print(f"Done. Saved: {args.outfile}")

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        if e.response.status_code == 401:
            print("\n오류: 인증에 실패했습니다 (401 Unauthorized).", file=sys.stderr)
            print(".env 파일의 XRAY_CLIENT_ID와 XRAY_CLIENT_SECRET 값이 올바른지 다시 확인해 주세요.", file=sys.stderr)
        else:
            print(f"\nHTTPError: {e.response.status_code} {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
