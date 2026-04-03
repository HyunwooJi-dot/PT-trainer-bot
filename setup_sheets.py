"""
Google Sheets 초기 세팅 스크립트
처음 한 번만 실행하면 스프레드시트에 필요한 시트와 헤더가 자동 생성됩니다.

실행 방법:
  python setup_sheets.py
"""

import os
import json
import sys
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 시트별 헤더 정의
SHEET_HEADERS = {
    "회원": ["이름", "chat_id", "수업요일", "특이사항", "등록일"],
    "운동": ["날짜", "회원명", "운동내용", "완료여부", "완료시간"],
    "숙제": ["날짜", "회원명", "숙제내용", "발송상태", "발송시간"],
    "로그": ["시간", "회원명", "chat_id", "활동유형", "날짜"],
}


def main():
    print("🔧 Google Sheets 초기 세팅을 시작합니다...\n")

    # 인증
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    spreadsheet_id = os.getenv("SPREADSHEET_ID")

    if not spreadsheet_id:
        print("❌ 오류: .env 파일에 SPREADSHEET_ID가 없습니다.")
        sys.exit(1)

    try:
        if creds_json:
            creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        client = gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 인증 오류: {e}")
        sys.exit(1)

    # 스프레드시트 열기
    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        print(f"✅ 스프레드시트 연결 성공: {spreadsheet.title}\n")
    except Exception as e:
        print(f"❌ 스프레드시트 열기 오류: {e}")
        print("   SPREADSHEET_ID가 올바른지, 서비스 계정에 공유됐는지 확인해주세요.")
        sys.exit(1)

    existing_sheets = {ws.title for ws in spreadsheet.worksheets()}

    for sheet_name, headers in SHEET_HEADERS.items():
        if sheet_name in existing_sheets:
            print(f"⚠️  '{sheet_name}' 시트가 이미 있습니다. 건너뜁니다.")
        else:
            ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(headers))
            ws.append_row(headers)

            # 헤더 서식 (굵게, 배경색)
            ws.format("A1:Z1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}
            })
            print(f"✅ '{sheet_name}' 시트 생성 완료 — 헤더: {headers}")

    # 기본 Sheet1 삭제 (필요 시)
    if "Sheet1" in existing_sheets or "시트1" in existing_sheets:
        try:
            default = spreadsheet.worksheet("Sheet1")
            spreadsheet.del_worksheet(default)
            print("🗑️  기본 'Sheet1' 삭제 완료")
        except Exception:
            pass
        try:
            default = spreadsheet.worksheet("시트1")
            spreadsheet.del_worksheet(default)
        except Exception:
            pass

    print("\n🎉 초기 세팅 완료!")
    print(f"   스프레드시트 주소: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")


if __name__ == "__main__":
    main()
