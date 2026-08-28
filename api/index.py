import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import requests

def clean_ics_content(raw_ics_text: str) -> str:
    # 拆分所有 VEVENT
    events = re.split(r'(BEGIN:VEVENT[\s\S]*?END:VEVENT)', raw_ics_text)
    
    cleaned_parts = []
    
    for part in events:
        if not part.startswith("BEGIN:VEVENT"):
            cleaned_parts.append(part)
            continue
            
        # 还原折行 (iCalendar 标准折行：换行 + 空格/制表符)
        unfolded_event = re.sub(r'\r?\n[ \t]', '', part)
        
        # 提取字段
        dtstart_m = re.search(r'DTSTART:[^\r\n]+', unfolded_event)
        dtend_m = re.search(r'DTEND:[^\r\n]+', unfolded_event)
        uid_m = re.search(r'UID:[^\r\n]+', unfolded_event)
        dtstamp_m = re.search(r'DTSTAMP:[^\r\n]+', unfolded_event)
        url_m = re.search(r'URL:([^\r\n]+)', unfolded_event)
        loc_m = re.search(r'LOCATION:([\s\S]*?)(?=\r?\n[A-Z\-]+:|\r?\nEND:VEVENT)', unfolded_event)
        
        dtstart = dtstart_m.group(0) if dtstart_m else ""
        dtend = dtend_m.group(0) if dtend_m else ""
        uid = uid_m.group(0) if uid_m else ""
        dtstamp = dtstamp_m.group(0) if dtstamp_m else ""
        event_url = url_m.group(1).strip() if url_m else ""
        raw_location = loc_m.group(1).strip() if loc_m else ""
        
        # 解析 LOCATION 内部结构
        # 把转义的 \n 拆成实际行
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
                    # 提取 DAT400 或 DAT385
                    course_code = c_m.group(1).split('_')[0]
                    
            elif "Activity:" in line:
                a_m = re.search(r'Activity:\s*([^.\n]+)', line)
                if a_m:
                    activity = a_m.group(1).strip()
                    
            elif "Room name:" in line:
                r_matches = re.findall(r'Room name:\s*([^.\n,]+)', line)
                for r in r_matches:
                    r_clean = r.strip()
                    if r_clean and r_clean not in rooms:
                        rooms.append(r_clean)
                        
            if "Building:" in line and not building:
                b_m = re.search(r'Building:\s*([^.\n,]+)', line)
                if b_m:
                    building = b_m.group(1).strip()
                    
            if "Campus:" in line and not campus:
                c_m = re.search(r'Campus:\s*([^\n\r,]+)', line)
                if c_m:
                    campus = c_m.group(1).strip()
                    
            # 兼容 Game Development Project 这种没有 Activity 前缀的项
            if "Game Development Project" in line:
                activity = "Game Dev Project"

        # 生成精简标题: [DAT400] Lecture (HC3) 或 [DAT385] (Jupiter243)
        title_items = []
        if course_code:
            title_items.append(course_code)
        if activity:
            title_items.append(activity)
            
        summary = " ".join(title_items) if title_items else "Course Event"
        if rooms:
            summary += f" ({'/'.join(rooms)})"
            
        # 生成精简地点: Lindholmen, Jupiter, Jupiter243
        loc_display_items = []
        if campus: loc_display_items.append(campus)
        if building: loc_display_items.append(building)
        if rooms: loc_display_items.append("/".join(rooms))
        clean_location_str = ", ".join(loc_display_items) if loc_display_items else raw_location
        
        # 描述与地图链接
        desc_items = []
        if campus: desc_items.append(f"校区: {campus}")
        if building or rooms: desc_items.append(f"位置: {building} {'/'.join(rooms)}")
        if event_url:
            desc_items.append(f"导航: {event_url}")
            
        description_str = "\\n".join(desc_items)
        
        # 重新组装极简 VEVENT
        new_event = [
            "BEGIN:VEVENT",
            uid,
            dtstamp,
            dtstart,
            dtend,
            f"SUMMARY:{summary}",
            f"LOCATION:{clean_location_str}",
            f"DESCRIPTION:{description_str}"
        ]
        if event_url:
            new_event.append(f"URL:{event_url}")
        new_event.append("END:VEVENT")
        
        cleaned_parts.append("\r\n".join([line for line in new_event if line]))

    return "".join(cleaned_parts)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        target_url = params.get('url', [None])[0]

        if not target_url:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write("Service is running! Append ?url=<YOUR_TIMEEDIT_URL> to subscribe.".encode('utf-8'))
            return

        try:
            # 伪造常见 User-Agent 避免被拦截
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(target_url, headers=headers, timeout=15)
            resp.raise_for_status()
            
            cleaned_ics = clean_ics_content(resp.text)

            self.send_response(200)
            self.send_header('Content-type', 'text/calendar; charset=utf-8')
            self.send_header('Content-Disposition', 'inline; filename=schedule.ics')
            self.end_headers()
            self.wfile.write(cleaned_ics.encode('utf-8'))

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"Error processing calendar: {str(e)}".encode('utf-8'))
