import re
from fastapi import FastAPI, Query, Response, HTTPException
import requests
from icalendar import Calendar, Event

app = FastAPI()

def parse_timeedit_location(raw_text: str):
    if not raw_text:
        return {}
    text = raw_text.replace(r'\n', '\n')
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    data = {
        "course_code": "", "activity": "", "room": "", 
        "building": "", "campus": "", "map_url": ""
    }
    for line in lines:
        if "Course code:" in line and not data["course_code"]:
            m = re.search(r"Course code:\s*([A-Za-z0-9_]+)", line)
            if m:
                data["course_code"] = m.group(1).split('_')[0]
        elif "Activity:" in line:
            m = re.search(r"Activity:\s*([^.]+)", line)
            if m:
                data["activity"] = m.group(1).strip()
        elif "Room name:" in line:
            room_m = re.search(r"Room name:\s*([^.]+)", line)
            if room_m and not data["room"]:
                data["room"] = room_m.group(1).strip()
        if "Building:" in line:
            b_m = re.search(r"Building:\s*([^.]+)", line)
            if b_m and not data["building"]:
                data["building"] = b_m.group(1).strip()
        if "Campus:" in line:
            c_m = re.search(r"Campus:\s*([^\n\r]+)", line)
            if c_m and not data["campus"]:
                data["campus"] = c_m.group(1).strip()
        if "https://maps.chalmers.se" in line and not data["map_url"]:
            url_m = re.search(r"(https://maps\.chalmers\.se/#?[a-zA-Z0-9\-_]*)", line)
            if url_m:
                data["map_url"] = url_m.group(1)
    if not data["activity"]:
        for line in lines:
            if "Game Development Project" in line:
                data["activity"] = "Game Dev Project"
                break
    return data

@app.get("/calendar.ics")
def get_clean_calendar(url: str = Query(..., description="TimeEdit ICS URL")):
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        upstream_cal = Calendar.from_ical(resp.content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error: {e}")

    clean_cal = Calendar()
    for prop in ['VERSION', 'PRODID', 'CALSCALE', 'X-WR-CALNAME']:
        if prop in upstream_cal:
            clean_cal.add(prop, upstream_cal[prop])
        else:
            clean_cal.add('X-WR-CALNAME', 'Chalmers 课表')

    for component in upstream_cal.walk():
        if component.name == "VEVENT":
            event = Event()
            event.add('uid', component.get('uid'))
            event.add('dtstart', component.get('dtstart').dt)
            event.add('dtend', component.get('dtend').dt)
            if component.get('dtstamp'):
                event.add('dtstamp', component.get('dtstamp').dt)

            meta = parse_timeedit_location(str(component.get('location', '')))

            title_parts = []
            if meta["course_code"]:
                title_parts.append(meta["course_code"])
            if meta["activity"]:
                title_parts.append(meta["activity"])
            title = " ".join(title_parts) if title_parts else "Course Event"
            if meta["room"]:
                title += f" ({meta['room']})"
            event.add('summary', title)

            loc_parts = [p for p in [meta["campus"], meta["building"], meta["room"]] if p]
            event.add('location', ", ".join(loc_parts) if loc_parts else str(component.get('location', '')))

            desc = []
            if meta["campus"]: desc.append(f"校区: {meta['campus']}")
            if meta["building"] or meta["room"]: desc.append(f"教室: {meta['building']} - {meta['room']}")
            map_url = str(component.get('url', '')) or meta["map_url"]
            if map_url:
                event.add('url', map_url)
                desc.append(f"地图导航: {map_url}")
            event.add('description', "\n".join(desc))

            clean_cal.add_component(event)

    return Response(
        content=clean_cal.to_ical(),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": "inline; filename=schedule.ics"}
    )