import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import requests

def clean_ics_content(raw_ics_text: str, filter_course: str = None) -> str:
    # 1. 统一换行符并还原 iCalendar 折行
    normalized = raw_ics_text.replace('\r\n', '\n').replace('\r', '\n')
    unfolded = re.sub(r'\n[ \t]', '', normalized)
    raw_events = re.findall(r'BEGIN:VEVENT([\s\S]*?)END:VEVENT', unfolded)

    # 2. 全局动态扫描 ICS：从文件本身提取课程代码与课程全名的映射关系
    known_course_names = {}
    known_keywords = {
        "Course code:", "Activity:", "Room name:", "Room type:",
        "Building:", "Campus:", "Class code:", "https://", "http://"
    }

    for ev in raw_events:
        loc_m = re.search(r'LOCATION:([\s\S]*?)(?=\n[A-Z\-]+:|$)', ev)
        if not loc_m:
            continue
        lines = [l.strip() for l in loc_m.group(1).replace(r'\n', '\n').split('\n') if l.strip()]
        
        current_codes = []
        inferred_name = ""
        
        for line in lines:
            if "Course code:" in line:
                m = re.search(r'Course code:\s*([A-Za-z0-9_]+)', line)
                if m:
                    code_prefix = m.group(1).split('_')[0]
                    current_codes.append(code_prefix)
            elif not any(kw in line for kw in known_keywords):
                if len(line) > 2:
                    inferred_name = line

        # 如果在某个事件中同时找到了代码与纯文本名称，建立全局映射
        if inferred_name and current_codes:
            for c in current_codes:
                known_course_names[c] = inferred_name

    # 3. 构建规范化的 iCalendar
    cal_name = "Chalmers 课表"
    if filter_course:
        cal_name = f"Chalmers - {filter_course.upper()}"

    output_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Chalmers TimeEdit Cleaner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{cal_name}",
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

        code_prefix = ""
        inline_name = ""
        activity = ""
        rooms = []
        building = ""
        campus = ""

        for line in loc_lines:
            if "Course code:" in line and not code_prefix:
                c_m = re.search(r'Course code:\s*([A-Za-z0-9_]+)', line)
                if c_m:
                    code_prefix = c_m.group(1).split('_')[0]

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

            if not any(kw in line for kw in known_keywords):
                if len(line) > 2:
                    inline_name = line

        # 确定展示的课程名称（优先本地提取，次优全局推断，兜底使用代码）
        final_course_name = inline_name or known_course_names.get(code_prefix, code_prefix)

        # 过滤功能（可选）
        if filter_course:
            target = filter_course.upper()
            if target not in code_prefix.upper() and target not in final_course_name.upper():
                continue

        # 拼接标题 (SUMMARY): 课程全名 + 活动类型 + (教室)
        title_parts = []
        if final_course_name:
            title_parts.append(final_course_name)
        if activity:
            title_parts.append(activity)

        summary = " ".join(title_parts) if title_parts else "Course"
        if rooms:
            summary += f" ({'/'.join(rooms)})"

        # 拼接地点 (LOCATION): 校区, 楼宇, 教室 (无链接)
        loc_parts = [p for p in [campus, building, "/".join(rooms)] if p]
        clean_loc = ", ".join(loc_parts) if loc_parts else "Chalmers"

        # 拼接描述 (DESCRIPTION): 结构化信息 (无链接)
        desc_parts = []
        if campus:
            desc_parts.append(f"校区: {campus}")
        if building or rooms:
            desc_parts.append(f"教室: {building} {'/'.join(rooms)}")
        description = "\\n".join(desc_parts)

        # 组装纯净 VEVENT
        output_lines.append("BEGIN:VEVENT")
        if uid: output_lines.append(f"UID:{uid}")
        output_lines.append(f"DTSTAMP:{dtstamp}")
        output_lines.append(f"DTSTART:{dtstart}")
        output_lines.append(f"DTEND:{dtend}")
        output_lines.append(f"SUMMARY:{summary}")
        output_lines.append(f"LOCATION:{clean_loc}")
        if description: output_lines.append(f"DESCRIPTION:{description}")
        output_lines.append("END:VEVENT")

    output_lines.append("END:VCALENDAR")
    return "\r\n".join(output_lines) + "\r\n"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        target_url = params.get('url', [None])[0]
        course_filter = params.get('course', [None])[0]

        if not target_url:
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write("Service online! Append ?url=<URL> to subscribe.".encode('utf-8'))
            return

        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.raise_for_status()

            cleaned_ics = clean_ics_content(resp.text, filter_course=course_filter)

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
