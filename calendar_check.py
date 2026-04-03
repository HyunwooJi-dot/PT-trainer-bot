"""
구글 캘린더 연동 모듈
────────────────────────────────────────────────
설정 방법:
  1. 트레이너 본인의 구글 캘린더를 서비스 계정 이메일과 공유 (조회 권한)
  2. 수업 이벤트 제목에 회원 이름을 포함
     예: "PT 홍길동", "홍길동 수업", "홍길동 PT 60분"
  3. 봇이 5분마다 종료된 이벤트를 감지해 트레이너에게 알림

주의: 구글 캘린더 API는 개인 캘린더 접근 시 OAuth2 또는
      서비스 계정으로 공유 받은 캘린더만 가능합니다.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
# primary = 기본 캘린더. 공유받은 캘린더는 이메일 주소로 설정


def _get_calendar_service():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)


def get_recently_ended_classes(window_minutes: int = 10) -> list[dict]:
    """
    최근 window_minutes분 내에 종료된 수업 이벤트 반환

    Args:
        window_minutes: 몇 분 전까지의 종료 이벤트를 감지할지 (기본 10분)

    Returns:
        [{"id": ..., "title": ..., "end_time": ...}, ...]
    """
    try:
        service = _get_calendar_service()

        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(minutes=window_minutes)).isoformat()
        time_max = now.isoformat()

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            # 제목에 PT, 수업, 트레이닝 포함된 이벤트 필터 (선택)
            # q="PT"  ← 특정 키워드로 필터링 원할 시 주석 해제
        ).execute()

        items = events_result.get("items", [])
        ended = []

        for item in items:
            end_raw = item.get("end", {})
            end_str = end_raw.get("dateTime") or end_raw.get("date", "")
            if not end_str:
                continue

            # 종료 시간이 현재보다 과거인지 확인
            try:
                if "T" in end_str:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                else:
                    # 종일 이벤트는 건너뜀
                    continue

                if end_dt <= now:
                    ended.append({
                        "id": item.get("id", ""),
                        "title": item.get("summary", ""),
                        "end_time": end_dt.strftime("%H:%M"),
                    })
            except Exception:
                continue

        logger.info(f"[캘린더] 최근 {window_minutes}분 내 종료 이벤트 {len(ended)}개")
        return ended

    except Exception as e:
        logger.error(f"[get_recently_ended_classes] {e}")
        return []


def create_class_event(
    name: str,
    date_str: str,
    start_time: str,
    end_time: str = None,
    timezone: str = "Asia/Seoul"
) -> dict | None:
    """
    구글 캘린더에 PT 수업 이벤트 생성.
    Args:
        name: 회원 이름 (이벤트 제목: "PT {name}")
        date_str: 날짜 "YYYY-MM-DD"
        start_time: 시작 시간 "HH:MM"
        end_time: 종료 시간 "HH:MM" (없으면 시작+1시간)
    Returns:
        {'id', 'title', 'start', 'end', 'link'} 또는 None
    """
    try:
        service = _get_calendar_service()

        # 종료 시간 기본값: 시작 + 1시간
        if not end_time:
            from datetime import datetime, timedelta
            start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(hours=1)
            end_time = end_dt.strftime("%H:%M")

        event = {
            "summary": f"PT {name}",
            "start": {
                "dateTime": f"{date_str}T{start_time}:00",
                "timeZone": timezone,
            },
            "end": {
                "dateTime": f"{date_str}T{end_time}:00",
                "timeZone": timezone,
            },
        }

        result = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()

        return {
            "id": result.get("id"),
            "title": result.get("summary"),
            "start": start_time,
            "end": end_time,
            "link": result.get("htmlLink", ""),
        }

    except Exception as e:
        logger.error(f"[create_class_event] {e}")
        return None


def list_upcoming_classes(days: int = 1) -> list[dict]:
    """
    향후 days일 내 예정된 수업 목록 (테스트/디버그용)
    """
    try:
        service = _get_calendar_service()
        now = datetime.now(timezone.utc)
        time_max = (now + timedelta(days=days)).isoformat()

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        return [
            {
                "title": e.get("summary", "(제목 없음)"),
                "start": e.get("start", {}).get("dateTime", ""),
                "end": e.get("end", {}).get("dateTime", ""),
            }
            for e in events_result.get("items", [])
        ]
    except Exception as e:
        logger.error(f"[list_upcoming_classes] {e}")
        return []
