"""
Google Sheets 연동 모듈
스프레드시트 구조:
  시트1: 회원     - 이름 | chat_id | 수업요일 | 특이사항 | 등록일
  시트2: 운동     - 날짜 | 회원명 | 운동내용 | 완료여부 | 완료시간
  시트3: 숙제     - 날짜 | 회원명 | 숙제내용 | 발송상태 | 발송시간
  시트4: 로그     - 시간 | 회원명 | chat_id | 활동유형 | 날짜
  시트5: 볼륨로그  - 날짜 | 회원명 | 운동명 | 부위 | 무게(KG) | 세트 | 횟수 | 총볼륨(KG)
"""

import os
import json
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ─────────────────────────────────────────────
# 연결
# ─────────────────────────────────────────────

def _get_client():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # 로컬 개발용
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)


def _get_spreadsheet():
    client = _get_client()
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    return client.open_by_key(spreadsheet_id)


def _sheet(name: str):
    return _get_spreadsheet().worksheet(name)


# ─────────────────────────────────────────────
# 회원 관련
# ─────────────────────────────────────────────

def get_member_by_name(name: str) -> dict | None:
    try:
        records = _sheet("회원").get_all_records()
        for r in records:
            if str(r.get("이름", "")).strip() == name.strip():
                return r
        return None
    except Exception as e:
        logger.error(f"[get_member_by_name] {e}")
        return None


def get_all_members() -> list[dict]:
    try:
        return _sheet("회원").get_all_records()
    except Exception as e:
        logger.error(f"[get_all_members] {e}")
        return []


def register_member(name: str, schedule: str = "", notes: str = "") -> bool:
    try:
        ws = _sheet("회원")
        ws.append_row([
            name, "", schedule, notes,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ])
        # 회원 전용 볼륨 시트 자동 생성
        _get_or_create_member_volume_sheet(name)
        return True
    except Exception as e:
        logger.error(f"[register_member] {e}")
        return False


def update_member_chat_id(name: str, chat_id: str) -> bool:
    try:
        ws = _sheet("회원")
        records = ws.get_all_records()
        for i, r in enumerate(records):
            if str(r.get("이름", "")).strip() == name.strip():
                ws.update_cell(i + 2, 2, str(chat_id))  # 2열 = chat_id
                return True
        return False
    except Exception as e:
        logger.error(f"[update_member_chat_id] {e}")
        return False


def update_member_notes(name: str, notes: str) -> bool:
    try:
        ws = _sheet("회원")
        records = ws.get_all_records()
        for i, r in enumerate(records):
            if str(r.get("이름", "")).strip() == name.strip():
                ws.update_cell(i + 2, 4, notes)  # 4열 = 특이사항
                return True
        return False
    except Exception as e:
        logger.error(f"[update_member_notes] {e}")
        return False


# ─────────────────────────────────────────────
# 운동 관련
# ─────────────────────────────────────────────

def get_workout(name: str, date: str) -> str | None:
    try:
        records = _sheet("운동").get_all_records()
        for r in records:
            if (str(r.get("회원명", "")).strip() == name.strip()
                    and str(r.get("날짜", "")).strip() == date.strip()):
                return str(r.get("운동내용", "")) or None
        return None
    except Exception as e:
        logger.error(f"[get_workout] {e}")
        return None


def save_workout(name: str, date: str, workout: str) -> bool:
    try:
        ws = _sheet("운동")
        records = ws.get_all_records()
        for i, r in enumerate(records):
            if (str(r.get("회원명", "")).strip() == name.strip()
                    and str(r.get("날짜", "")).strip() == date.strip()):
                ws.update_cell(i + 2, 3, workout)  # 3열 = 운동내용
                return True
        # 신규 행 추가
        ws.append_row([
            date, name, workout, "미완료", ""
        ])
        return True
    except Exception as e:
        logger.error(f"[save_workout] {e}")
        return False


def mark_workout_done(name: str, date: str) -> bool:
    try:
        ws = _sheet("운동")
        records = ws.get_all_records()
        for i, r in enumerate(records):
            if (str(r.get("회원명", "")).strip() == name.strip()
                    and str(r.get("날짜", "")).strip() == date.strip()):
                ws.update_cell(i + 2, 4, "완료")  # 4열 = 완료여부
                ws.update_cell(i + 2, 5, datetime.now().strftime("%Y-%m-%d %H:%M"))
                return True
        return False
    except Exception as e:
        logger.error(f"[mark_workout_done] {e}")
        return False


# ─────────────────────────────────────────────
# 숙제 관련
# ─────────────────────────────────────────────

def save_homework(name: str, date: str, homework: str) -> bool:
    try:
        ws = _sheet("숙제")
        ws.append_row([
            date, name, homework, "발송완료",
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ])
        return True
    except Exception as e:
        logger.error(f"[save_homework] {e}")
        return False


def get_completed_without_homework(date: str) -> list[str]:
    """
    오늘 수업 완료했지만 숙제가 없는 회원 목록 반환.
    운동 시트에서 완료=True인데 숙제 시트에 오늘 날짜 기록 없는 회원.
    """
    try:
        workouts  = _sheet("운동").get_all_records()
        homeworks = _sheet("숙제").get_all_records()

        # 오늘 수업 완료한 회원
        completed = {
            str(r.get("회원명", "")).strip()
            for r in workouts
            if str(r.get("날짜", "")).strip() == date
            and str(r.get("완료여부", "")).strip() == "완료"
        }

        # 오늘 숙제 받은 회원
        got_homework = {
            str(r.get("회원명", "")).strip()
            for r in homeworks
            if str(r.get("날짜", "")).strip() == date
        }

        # 완료했지만 숙제 없는 회원
        return sorted(completed - got_homework)
    except Exception as e:
        logger.error(f"[get_completed_without_homework] {e}")
        return []


def get_recent_homework(name: str, limit: int = 3) -> list[dict]:
    """최근 숙제 목록 (AI 생성 시 참고용)"""
    try:
        records = _sheet("숙제").get_all_records()
        member_hw = [r for r in records if str(r.get("회원명", "")).strip() == name.strip()]
        return member_hw[-limit:] if member_hw else []
    except Exception as e:
        logger.error(f"[get_recent_homework] {e}")
        return []


# ─────────────────────────────────────────────
# 볼륨 로그
# ─────────────────────────────────────────────

def save_volume_log(name: str, date: str, exercises: list) -> bool:
    """
    회원 전용 시트에 세션 1개 = 1줄로 볼륨 저장.
    컬럼: 날짜 | 상체볼륨(KG) | 하체볼륨(KG) | 기타볼륨(KG) | 전체볼륨(KG) | 운동내용
    """
    try:
        ws = _get_or_create_member_volume_sheet(name)

        upper = sum(e.get('volume', 0) for e in exercises if e.get('category') == '상체')
        lower = sum(e.get('volume', 0) for e in exercises if e.get('category') == '하체')
        etc   = sum(e.get('volume', 0) for e in exercises if e.get('category') == '기타')
        total = upper + lower + etc

        summary_parts = []
        for e in exercises:
            w = f"{e['weight']:g}kg " if e.get('weight') else ""
            summary_parts.append(f"{e['name']} {w}{e['reps']}x{e['sets']}")
        summary = ", ".join(summary_parts)

        ws.append_row([date, upper, lower, etc, total, summary])
        return True
    except Exception as e:
        logger.error(f"[save_volume_log] {e}")
        return False


def _get_or_create_member_volume_sheet(name: str):
    """회원 전용 볼륨 시트 반환. 없으면 헤더와 함께 자동 생성."""
    ss = _get_spreadsheet()
    sheet_name = f"{name}_볼륨"
    try:
        return ss.worksheet(sheet_name)
    except Exception:
        ws = ss.add_worksheet(title=sheet_name, rows=1000, cols=6)
        ws.append_row(["날짜", "상체볼륨(KG)", "하체볼륨(KG)", "기타볼륨(KG)", "전체볼륨(KG)", "운동내용"])
        return ws


def get_volume_history(name: str) -> list:
    """회원 볼륨 히스토리 조회. 시각화용."""
    try:
        ws = _get_or_create_member_volume_sheet(name)
        return ws.get_all_records()
    except Exception as e:
        logger.error(f"[get_volume_history] {e}")
        return []


# ─────────────────────────────────────────────
# 로그
# ─────────────────────────────────────────────

def log_activity(name: str, chat_id: str, activity_type: str, date: str) -> bool:
    try:
        ws = _sheet("로그")
        ws.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name, str(chat_id), activity_type, date
        ])
        return True
    except Exception as e:
        logger.error(f"[log_activity] {e}")
        return False
