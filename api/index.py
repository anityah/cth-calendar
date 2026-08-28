import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import requests

# 课程代码到全称的映射字典（可按需补充）
COURSE_NAME_MAP = {
    "DAT400": "High-Performance Parallel Computing",
    "DAT385": "Game Development Project",
    "DIT431": "High-Performance Parallel Computing",
    "DIT248": "Game Development Project"
}

def clean_ics_content(raw_ics_text: str) -> str:
    normalized = raw_ics_text.replace('\r\n', '\n').replace('\r', '\n')
    unfolded = re.sub(r'\n[ \t]', '', normalized)

    raw_events = re.findall(r'BEGIN:VEVENT([\s\S]*?)END:VEVENT', unfolded)

    output_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Chalmers TimeEdit Cleaner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Chalmers 课表",
        "X-WR-TIMEZONE:Europe/Stockholm"
    ]

    for ev_body in raw_events:
        uid_m = re.search(r'UID:([^\n]+)', ev_body)
        dtstart_m = re.search(r'DTSTART:([^\n]+)', ev_body)
        dtend_m = re.search(r'DTEND:([^\n]+)', ev_body)
        dtstamp_m = re.search(r'DTSTAMP:([^\n]+)', ev_body)
        loc_m = re.search(r'LOCATION:([\s\S]*?)(?=\n[A-Z\-]+:|$)', ev_body)

        if not dtstart_m or not dtend_m:
            continue

        uid = uid_m.group(1).strip() if uid_m else ""
        dtstart = dtstart_m.group(1).strip()
        dtend = dtend_m.group(1).strip()
        dtstamp = dtstamp_m.group(1).strip() if dtstamp_m else dtstart
        raw_location = loc_m.group(1).strip() if loc_m else ""

        loc_lines = [l.strip() for l in raw_location.replace(r'\n', '\n').split('\n') if l.strip()]

        course_name = ""
        activity = ""
        rooms = []
        building = ""
        campus = ""

        for line in loc_lines:
            # 匹配课程代码并转换为课程全名
            if "Course code:" in line and not course_name:
                c_m = re.search(r'Course code:\s*([A-Za-z0-9_]+)', line)
                if c_m:
                    code_prefix = c_m.group(1).split('_')[0]
                    course_name = COURSE_NAME_MAP.get(code_prefix, "")

            elif "Activity:" in line and not activity:
                a_m = re.search(r'Activity:\s*([^.\n]+)', line)
                if a_m:
                    activity = a_m.group(1).strip()

            elif "Room name:" in line:
                r_matches = re.findall(r'Room name:\s*([^.\n,]+)', line)
                for r in r_matches:
                    rc = r.strip()
                    if rc and rc not in rooms:
                        rooms.append(rc)

            if "Building:" in line and not building:
                b_m = re.search(r'Building:\s*([^.\n,]+)', line)
                if b_m:
                    building = b_m.group(1).strip()

            if "Campus:" in line and not campus:
                c_m = re.search(r'Campus:\s*([^\n\r,]+)', line)
                if c_m:
                    campus = c_m.group(1).strip()

            # 文本中直接包含 Game Development Project 的兜底处理
            if "Game Development Project" in line:
                course_name = "Game Development Project"

        # 拼接标题（只含课程名称与活动，不含课程代码）
        title_parts = []
        if course_name:
            title_parts.append(course_name)
        if activity:
            title_parts.append(activity)

        summary = " ".join(title_parts) if title_parts else "Course"
        if rooms:
            summary += f" ({'/'.join(rooms)})"

        # 拼接地点（只保留校区、楼宇、教室）
        loc_parts = [p for p in [campus, building, "/".join(rooms)] if p]
        clean_loc = ", ".join(loc_parts) if loc_parts else "Chalmers"

        # 拼接描述（无链接）
        desc_parts = []
        if campus:
            desc_parts.append(f"校区: {campus}")
        if building or rooms:
            desc_parts.append(f"教室: {building} {'/'.join(rooms)}")
        description = "\\n".join(desc_parts)

        # 组装 VEVENT（不添加任何 URL 字段）
        output_lines.append("BEGIN:VEVENT")
        if uid:
            output_lines.append(f"UID:{uid}")
        output_lines.append(f"DTSTAMP:{dtstamp}")
        output_lines.append(f"DTSTART:{dtstart}")
        output_lines.append(f"DTEND:{dtend}")
        output_lines.append(f"SUMMARY:{summary}")
        output_lines.append(f"LOCATION:{clean_loc}")
        if description:
            output_lines.append(f"DESCRIPTION:{description}")
        output_lines.append("END:VEVENT")

    output_lines.append("END:VCALENDAR")
    return "\r\n".join(output_lines) + "\r\n"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        target_url = params.get('url', [None])[0]

        if not target_url:
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write("Service is running! Append ?url=<YOUR_TIMEEDIT_URL> to subscribe.".encode('utf-8'))
            return

        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.raise_for_status()

            cleaned_ics = clean_ics_content(resp.text)

            self.send_response(200)
            self.send_header('Content-Type', 'text/calendar; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(cleaned_ics.encode('utf-8'))

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"Error processing calendar: {str(e)}".encode('utf-8'))
