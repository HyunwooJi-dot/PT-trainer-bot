"""
급여 계산기 캘린더 동기화 모듈
────────────────────────────────
- 구글 캘린더 이벤트 파싱 → 급여계산기 시트 세션기록에 자동 반영
- 회원명부에 없는 신규 회원 자동 등록
- bot.py의 JobQueue에서 daily 실행

파싱 규칙:
  현우-{회원명}[님](태그)-{신규|재등}-{a}[s]/{b}[s][+{c}[s]]  → 정상 세션
  현우-{회원명}[님]-{신규|재등}-{a}[s]+{b}[s]/{c}[s]         → 재등록 앞
  현우-{회원명}[님]-{신규|재등}-{n}회                          → 1회성 (선수 등)
  현우-{회원명}[님](공백|하이픈)OT                              → OT
  기타 → 무시 or 리포트
"""

import os
import re
import logging
from datetime import datetime, timezone, timedelta

import gspread
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# ---------- 설정 (환경변수) ----------
SALARY_SPREADSHEET_ID = os.getenv("SALARY_SPREADSHEET_ID", "1Xg9BgIKb0nA3ahz2Jn2c9hKOU80ta3Ki_KXX544_au8")
CALENDAR_ID = os.getenv("CALENDAR_ID", "jhw1390@gmail.com")
TRAINER_NAME = os.getenv("TRAINER_NAME", "현우")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# ---------- 정규식 ----------
NAME_PART = r"([^-]+?)(?:님)?"
TYPE_PART = r"(?:-(신규|재등)(?:\(.+?\))?)?"

PATTERN_A = re.compile(rf"^{TRAINER_NAME}-{NAME_PART}{TYPE_PART}-(\d+)s?\+(\d+)s?/(\d+)s?$")
PATTERN_B = re.compile(rf"^{TRAINER_NAME}-{NAME_PART}{TYPE_PART}-(\d+)s?/(\d+)s?(?:\+(\d+)s?)?$")
PATTERN_C = re.compile(rf"^{TRAINER_NAME}-{NAME_PART}{TYPE_PART}-(\d+)회$")
PATTERN_OT = re.compile(rf"^{TRAINER_NAME}-{NAME_PART}[\s\-]+OT.*$")
PATTERN_TRAINER = re.compile(rf"^{TRAINER_NAME}[\s\-]+.+$")


# ---------- 인증 ----------
def _get_credentials():
    import json
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        return Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    return Credentials.from_service_account_file("credentials.json", scopes=SCOPES)


# ---------- 캘린더 조회 ----------
def fetch_events(year: int, month: int) -> list:
    creds = _get_credentials()
    service = build("calendar", "v3", credentials=creds)

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=timezone.utc)

    all_events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
            maxResults=250,
        ).execute()
        all_events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return all_events


# ---------- 파싱 ----------
def parse_event(event: dict) -> dict | None:
    """이벤트 하나를 파싱해서 세션 정보 반환. 실패 시 None."""
    title = (event.get("summary") or "").strip()
    start_raw = event.get("start", {})
    start_dt_str = start_raw.get("dateTime") or start_raw.get("date", "")

    if not start_dt_str or "T" not in start_dt_str:
        return None

    try:
        dt = datetime.fromisoformat(start_dt_str.replace("Z", "+00:00"))
        kst = dt.astimezone(timezone(timedelta(hours=9)))
        date_str = kst.strftime("%Y-%m-%d")
        time_str = kst.strftime("%H:%M")
    except Exception:
        return None

    if not PATTERN_TRAINER.match(title):
        return {"skip": True, "reason": "ignored", "title": title, "date": date_str, "time": time_str}

    m = PATTERN_A.match(title)
    if m:
        name, reg_type, a, b, c = m.groups()
        return {
            "date": date_str, "time": time_str, "name": name.strip(),
            "reg_type": reg_type or "신규",
            "total_sessions": int(a), "extra_sessions": int(b), "progress": int(c),
            "title": title, "is_oneshot": False,
        }

    m = PATTERN_B.match(title)
    if m:
        name, reg_type, a, b, c = m.groups()
        return {
            "date": date_str, "time": time_str, "name": name.strip(),
            "reg_type": reg_type or "신규",
            "total_sessions": int(a), "extra_sessions": int(c) if c else 0, "progress": int(b),
            "title": title, "is_oneshot": False,
        }

    m = PATTERN_C.match(title)
    if m:
        name, reg_type, n = m.groups()
        return {
            "date": date_str, "time": time_str, "name": name.strip(),
            "reg_type": reg_type or "신규",
            "total_sessions": int(n), "extra_sessions": 0, "progress": int(n),
            "title": title, "is_oneshot": True,
        }

    m = PATTERN_OT.match(title)
    if m:
        return {
            "date": date_str, "time": time_str, "name": m.group(1).strip(),
            "title": title, "is_ot": True,
        }

    return {"parse_failed": True, "title": title, "date": date_str, "time": time_str}


# ---------- 메인 동기화 함수 ----------
def sync_month(year: int = None, month: int = None) -> dict:
    """
    지정 월(기본 이번 달) 캘린더 이벤트 → 세션기록 시트 동기화
    반환: {'sessions': N, 'ot': N, 'new_members': [...], 'failed': [...]}
    """
    if year is None or month is None:
        now = datetime.now(timezone(timedelta(hours=9)))
        year, month = now.year, now.month

    logger.info(f"[급여] {year}-{month:02d} 동기화 시작")

    events = fetch_events(year, month)
    logger.info(f"[급여] 캘린더 이벤트 {len(events)}개 조회")

    parsed_sessions = []
    ot_sessions = []
    failed = []

    for e in events:
        result = parse_event(e)
        if result is None:
            continue
        if result.get("skip"):
            continue
        if result.get("parse_failed"):
            failed.append(result)
            continue
        if result.get("is_ot"):
            ot_sessions.append(result)
            continue
        parsed_sessions.append(result)

    # ---- 시트 접근 ----
    creds = _get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SALARY_SPREADSHEET_ID)

    # ---- 회원명부 확인 & 신규 자동등록 ----
    member_ws = sh.worksheet("👥회원명부")
    member_data = member_ws.get_all_values()

    existing_members = {}
    last_row = 4
    for i, row in enumerate(member_data[4:], start=5):
        if len(row) > 0 and row[0].strip():
            existing_members[row[0].strip()] = i
            last_row = i

    unknown_members = {}
    for s in parsed_sessions:
        if s["name"] not in existing_members:
            cur = unknown_members.get(s["name"], {
                "total_sessions": 0, "reg_type": s["reg_type"],
                "is_oneshot": s.get("is_oneshot", False),
            })
            if s["total_sessions"] > cur["total_sessions"]:
                cur["total_sessions"] = s["total_sessions"]
                cur["reg_type"] = s["reg_type"]
            if s.get("is_oneshot"):
                cur["is_oneshot"] = True
            unknown_members[s["name"]] = cur

    ot_only_members = set()
    for s in ot_sessions:
        if s["name"] not in existing_members and s["name"] not in unknown_members:
            ot_only_members.add(s["name"])

    if unknown_members or ot_only_members:
        new_rows = []
        for name, info in unknown_members.items():
            memo = "🤖 캘린더 자동등록 - 총금액 입력 필요"
            if info.get("is_oneshot"):
                memo = "🤖 1회성 손님 - 1회당 금액 입력"
            new_rows.append([
                name, info["total_sessions"], "", "", "",
                info["reg_type"], memo,
            ])
        for name in ot_only_members:
            new_rows.append([
                name, "", "", "", "", "신규", "🤖 OT만 있음",
            ])

        start_new_row = last_row + 1
        for i, row in enumerate(new_rows):
            r_idx = start_new_row + i
            row[3] = f'=IFERROR(IF(B{r_idx}="","",C{r_idx}/B{r_idx}),"")'
            row[4] = f'=IF(B{r_idx}="","",IF(B{r_idx}=5,"패키지","개인"))'

        member_ws.update(
            range_name=f"A{start_new_row}:G{start_new_row + len(new_rows) - 1}",
            values=new_rows,
            value_input_option="USER_ENTERED",
        )

    # ---- 세션기록 업데이트 ----
    session_ws = sh.worksheet("📝세션기록")
    session_ws.batch_clear(["A5:C304"])

    session_rows = []
    for s in sorted(parsed_sessions + ot_sessions, key=lambda x: (x["date"], x["time"])):
        session_rows.append([s["date"], s["time"], s["name"]])

    while len(session_rows) < 300:
        session_rows.append(["", "", ""])

    session_ws.update(
        range_name=f"A5:C{5 + len(session_rows) - 1}",
        values=session_rows,
        value_input_option="USER_ENTERED",
    )

    result = {
        "year_month": f"{year}-{month:02d}",
        "sessions": len(parsed_sessions),
        "ot": len(ot_sessions),
        "new_members": list(unknown_members.keys()) + list(ot_only_members),
        "failed": failed,
    }
    logger.info(f"[급여] 동기화 완료: {result}")
    return result


# ---------- 대시보드에서 값 읽기 (아카이브용) ----------
def read_dashboard_values() -> dict:
    """대시보드의 계산된 값 읽어오기"""
    creds = _get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SALARY_SPREADSHEET_ID)

    dashboard = sh.worksheet("📊대시보드")
    values = dashboard.get("C6:C24", value_render_option="UNFORMATTED_VALUE")

    def get(idx, default=0):
        try:
            v = values[idx][0]
            return float(v) if v not in ("", None) else default
        except (IndexError, TypeError, ValueError):
            return default

    return {
        "개인매출":     get(0),
        "패키지매출":   get(1),
        "총매출":       get(2),
        "패키지세션":   int(get(3)),
        "개인세션":     int(get(4)),
        "기본급":       get(12),
        "수업료성과금": get(13),
        "인센티브":     get(14),
        "패키지급여":   get(15),
        "총지급액":     get(16),
        "실수령액":     get(18),
    }


# ---------- 월별기록 아카이브 ----------
def archive_month(year: int = None, month: int = None) -> dict:
    """이번 달 데이터를 💼월별기록 시트에 저장"""
    if year is None or month is None:
        now = datetime.now(timezone(timedelta(hours=9)))
        year, month = now.year, now.month

    year_month = f"{year}-{month:02d}"
    logger.info(f"[급여] {year_month} 아카이브 시작")

    vals = read_dashboard_values()

    creds = _get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SALARY_SPREADSHEET_ID)
    history = sh.worksheet("💼월별기록")

    all_data = history.get_all_values()
    target_row = None
    for i, row in enumerate(all_data[6:], start=7):
        if row and row[0].strip() == year_month:
            target_row = i
            break

    if target_row is None:
        last_data_row = 6
        for i, row in enumerate(all_data[6:], start=7):
            if row and row[0].strip():
                last_data_row = i
        target_row = last_data_row + 1

    row_data = [
        year_month,
        vals["총매출"], vals["개인매출"], vals["패키지매출"],
        vals["개인세션"], vals["패키지세션"],
        vals["기본급"], vals["수업료성과금"], vals["인센티브"], vals["패키지급여"],
        vals["총지급액"], vals["실수령액"],
    ]

    history.update(
        range_name=f"A{target_row}:L{target_row}",
        values=[row_data],
        value_input_option="USER_ENTERED",
    )

    logger.info(f"[급여] 아카이브 완료: {year_month} 실수령 {vals['실수령액']:,.0f}원")
    return {**vals, "year_month": year_month}
