"""
AI 숙제 생성 모듈
Claude API를 사용해 회원 맞춤 숙제 운동을 생성합니다.
"""

import os
import logging
import anthropic

logger = logging.getLogger(__name__)


async def generate_homework(
    name: str,
    today_workout: str | None,
    member_notes: str | None,
    special_note: str = "",
    recent_homework: list[dict] | None = None
) -> str:
    """
    Claude API로 맞춤 숙제 운동 생성

    Args:
        name: 회원 이름
        today_workout: 오늘 수업에서 한 운동
        member_notes: 회원 특이사항 (부상, 건강 상태 등)
        special_note: 트레이너가 추가 입력한 사항
        recent_homework: 최근 숙제 목록 (중복 방지용)

    Returns:
        포맷된 숙제 텍스트
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        return _fallback_homework(name)

    # 최근 숙제 요약 (중복 방지)
    recent_hw_text = ""
    if recent_homework:
        recent_hw_text = "최근 발송된 숙제 (중복 피해주세요):\n"
        for hw in recent_homework[-3:]:
            recent_hw_text += f"- {hw.get('날짜', '')}: {str(hw.get('숙제내용', ''))[:100]}\n"

    prompt = f"""당신은 경험 많은 전문 개인 트레이너입니다.
아래 정보를 바탕으로 회원에게 맞는 홈 숙제 운동을 작성해주세요.

---
회원 이름: {name}
회원 특이사항/건강정보: {member_notes if member_notes else "없음"}
오늘 수업에서 한 운동: {today_workout if today_workout else "정보 없음 (다양한 근육군 고려)"}
트레이너 추가 요청: {special_note if special_note else "없음"}
{recent_hw_text}
---

작성 규칙:
1. 오늘 수업에서 사용한 근육군과 겹치지 않게 구성 (회복 필요)
2. 집에서 맨몸 또는 간단한 밴드로 할 수 있는 운동으로 구성
3. 회원의 특이사항(부상, 제한 사항)을 반드시 반영
4. 운동 3~5개 + 스트레칭/쿨다운 1~2개
5. 각 운동은 세트수, 횟수 또는 시간을 명시
6. 운동 강도는 수업 후 피로를 고려해 중간~낮은 수준
7. 친근하고 격려하는 톤으로 작성

출력 형식 (이모지 포함, 텔레그램 읽기 좋게):

🏠 *홈 숙제 운동*

*[ 메인 운동 ]*
1. 운동명 — N세트 × N회 (짧은 설명)
2. 운동명 — N세트 × N회 (짧은 설명)
...

*[ 스트레칭 ]*
- 스트레칭명 — N초 × N회

💬 [짧은 격려 한마디]"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    except anthropic.APIError as e:
        logger.error(f"[Anthropic API 오류] {e}")
        return _fallback_homework(name)
    except Exception as e:
        logger.error(f"[generate_homework 오류] {e}")
        return _fallback_homework(name)


def _fallback_homework(name: str) -> str:
    """API 실패 시 기본 숙제 반환"""
    return (
        f"🏠 *홈 숙제 운동*\n\n"
        f"*[ 메인 운동 ]*\n"
        f"1. 스쿼트 — 3세트 × 15회\n"
        f"2. 푸시업 — 3세트 × 10회 (무릎 푸시업 가능)\n"
        f"3. 힙 브릿지 — 3세트 × 20회\n"
        f"4. 플랭크 — 3세트 × 30초\n\n"
        f"*[ 스트레칭 ]*\n"
        f"- 햄스트링 스트레칭 — 30초 × 2회\n"
        f"- 고양이-소 스트레칭 — 1분\n\n"
        f"💬 {name}님, 꾸준히 하면 분명 변화가 느껴질 거예요! 파이팅! 🔥"
    )
