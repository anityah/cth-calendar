import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import requests

def clean_ics_content(raw_ics_text: str) -> str:
    # 1. 统一换行符并还原 iCalendar 折行
    normalized = raw_ics_text.replace('\r\n', '\n').replace('\r', '\n')
    unfolded = re.sub(r'\n[ \t]', '', normalized)

    # 2. 匹配所有 VEVENT 区块
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
        # 提取基础字段
        uid_m = re.search(r'UID:([^\n]+)', ev_body)
        dtstart_m = re.search(r'DTSTART:([^\n]+)', ev_body)
        dtend_m = re.search(r'DTEND:([^\n]+)', ev_body)
        dtstamp_m = re.search(r'DTSTAMP:([^\n]+)', ev_body)
        url_m = re.search(r'URL:([^\n]+)', ev_body)
        loc_m = re.search(r'LOCATION:([\s\S]*?)(?=\n[A-Z\-]+:|$)', ev_body)

        if not dtstart_m or not dtend_m:
            continue

        uid = uid_m.group(1).strip() if uid_m else ""
        dtstart = dtstart_m.group(1).strip()
        dtend = dtend_m.group(1).strip()
        dtstamp = dtstamp_m.group(1).strip() if dtstamp_m else dtstart
        event_url = url_m.group(1).strip() if url_m else ""
        raw_location = loc_m.group(1).strip() if loc_m else ""

        # 解析 LOCATION
        loc_lines = [l.strip() for l in raw_location.replace(r'\n', '\n').split('\n') if l.strip()]

        course_code = ""
        activity = ""
        rooms = []
        building = ""
        campus = ""

        for line in loc_lines:
            if "Course code:" in line and not course_code:
                c_m = re.search(r'Course code:\s*([A-Za-z0-9_]+)', line)
                if c_m:
                    course_code = c_m.group(1).split('_')[0]

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

            if "Game Development Project" in line and not activity:
                activity = "Game Dev Project"

        # 拼接标题 (SUMMARY)
        title_parts = []
        if course_code:
            title_parts.append(course_code)
        if activity:
            title_parts.append(activity)

        summary = " ".join(title_parts) if title_parts else "Course Event"
        if rooms:
            summary += f" ({'/'.join(rooms)})"

        # 拼接地点 (LOCATION)
        loc_parts = [p for p in [campus, building, "/".join(rooms)] if p]
        clean_loc = ", ".join(loc_parts) if loc_parts else "Chalmers"

        # 拼接描述 (DESCRIPTION)
        desc_parts = []
        if campus:
            desc_parts.append(f"校区: {campus}")
        if building or rooms:
            desc_parts.append(f"教室: {building} {'/'.join(rooms)}")
        if event_url:
            desc_parts.append(f"导航: {event_url}")
        description = "\\n".join(desc_parts)

        # 组装事件
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
        if event_url:
            output_lines.append(f"URL:{event_url}")
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
