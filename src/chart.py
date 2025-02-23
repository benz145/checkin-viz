import cairosvg
import svgwrite
import logging
import itertools
from typing import List, Dict, NamedTuple
from helpers import fetchall, fetchone
from datetime import datetime, timedelta, date
import os
from rule_sets import score


weekdays = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


class DataUnit(NamedTuple):
    x: str
    y: int
    checkedIn: bool
    time: datetime
    tier: str
    isMulligan: bool


class CheckinChartData(NamedTuple):
    name: str
    data: List[DataUnit]
    totalCheckins: int
    points: float
    hasMulliganed: bool
    tag: str

    def tostring(self) -> str:
        return json.dumps({"name": self.name, "data": self.data})


def knocked_out(challenge_id):
    return [
        r.name
        for r in fetchall(
            """
        SELECT name FROM challengers c
        JOIN challenger_challenges cc ON c.id = cc.challenger_id
        WHERE cc.challenge_id = %s AND cc.knocked_out = true
        """,
            [challenge_id],
        )
    ]


def get_challenger_info(challenge_id):
    return fetchall(
            """
        SELECT name, cc.tag FROM challengers c
        JOIN challenger_challenges cc ON c.id = cc.challenger_id
        WHERE cc.challenge_id = %s
        """,
            [challenge_id],
        )


def mulliganed_challengers(challenge_id):
    return [
        r.name
        for r in fetchall(
            """
        SELECT name FROM challengers c
        JOIN challenger_challenges cc ON c.id = cc.challenger_id
        WHERE cc.challenge_id = %s
        and cc.mulligan is not null
        """,
            [challenge_id],
        )
    ]


def checkin_chart(
    data: List[CheckinChartData],
    width: int,
    height: int,
    challenge_id,
    green,
    bye_week,
    total_points,
    achievements,
    total_checkins,
    total_possible_checkins,
    total_possible_checkins_so_far,
):
    if len(data) == 0:
        logging.warning("empty week + year selected")
        dwg = svgwrite.Drawing("empty.svg", size=(10, 10))
        return dwg.tostring()

    wGap = 0
    hGap = 20
    gutter = 85
    colors = ["#f7f7f7", "#cccccc", "#969696", "#636363", "#252525"]
    greens = [
        "#edf8e9",
        "#c7e9c0",
        "#a1d99b",
        "#74c476",
        "#41ab5d",
        "#238b45",
        "#005a32",
    ]
    green_mode = greens[4]
    base_color = green_mode if green else "white"

    columns = len(data)
    rows = len(data[0].data)
    rectW = (width - rows * wGap - gutter) / (rows + 3)
    rectH = (height - columns * hGap - gutter) / (columns)

    dwg = svgwrite.Drawing("checkin.svg", size=(width + 1, height), debug=False)
    dwg.add(
        dwg.rect(
            insert=(0, 0),
            size=("100%", "100%"),
            fill="white" if not green else green_mode,
        )
    )
    knocked_out_names = knocked_out(challenge_id)
    logging.info("knocked out: %s", knocked_out_names)
    logging.info("Achievements: %s", achievements)
    text_color = "black" if green else ""
    for column, chart in enumerate(data):
        yLabel = chart.name

        if chart.tag:
           yLabel += " " + chart.tag

        hasMulliganed = chart.hasMulliganed
        is_knocked_out = yLabel in knocked_out_names
        a = svgwrite.container.Hyperlink("/challenger/%s" % chart.name, target="_self")
        mulligan_circle = dwg.circle(
            center=(5, rectH * column + hGap * column + gutter + rectH / 4),
            r=5,
            stroke=greens[5],
            fill="transparent" if hasMulliganed else greens[5],
        )
        if hasMulliganed:
            mulligan_circle.fill = "transparent"
        text1 = dwg.text(
            yLabel,
            insert=(15, rectH * column + hGap * column + gutter + rectH / 2),
            font_size=14,
            text_decoration="line-through" if is_knocked_out else "",
            fill="currentcolor",
        )
        dwg.add(mulligan_circle)
        a.add(text1)
        dwg.add(a)
        for row, dataUnit in enumerate(chart.data):
            x = dataUnit.x
            checkedIn = dataUnit.checkedIn
            isMulligan = dataUnit.isMulligan
            fill_color = colors[2] if checkedIn and not is_knocked_out else base_color
            fill_color = colors[0] if is_knocked_out and checkedIn else fill_color
            stroke_color = colors[3] if not is_knocked_out else colors[1]

            if chart.totalCheckins >= 5 and dataUnit.y != 0:
                fill_color = greens[4] if not green else greens[6]
            if chart.totalCheckins >= 5:
                stroke_color = greens[6]
            # gold for 7!
            if chart.totalCheckins >= 7:
                fill_color = "#D4AF37"
            # lime for first to five
            if (
                achievements[2] is not None
                and chart.totalCheckins >= 5
                and chart.name == achievements[2][0]
                and dataUnit.time == achievements[2][1]
            ):
                fill_color = "#39FF14"
            # Mulligans are always grey
            if isMulligan:
                fill_color = colors[2]

            if column == 0:
                # add day of week
                text = dwg.text(x[:3], fill=text_color)
                text.translate(
                    rectW * row + wGap * row + gutter + rectW / 2 - 10, gutter - 10
                )
                # text.rotate(-90)
                dwg.add(text)

            rect = dwg.rect(
                insert=(
                    row * rectW + row * wGap + gutter,
                    column * rectH + column * hGap + gutter,
                ),
                size=(rectW, rectH),
                fill=fill_color,
                stroke=stroke_color,
                stroke_width=1,
                rx=2,
                ry=2,
            )
            group = dwg.g()
            text = dwg.text(dataUnit.tier)
            text.translate(
                row * rectW + row * wGap + gutter + rectW / 2 - 5,
                column * rectH + column * hGap + gutter + rectH / 2 + 5,
            )
            group.add(rect)
            if dataUnit.tier:
                group.add(text)
            if (
                dataUnit.time is not None
                and dataUnit.time.strftime("%H:%M") == achievements[1]
            ):
                text = dwg.text("🌚")
                text.translate(
                    row * rectW + row * wGap + gutter + rectW / 2 + 15,
                    column * rectH + column * hGap + gutter + rectH / 2 + 5,
                )
                group.add(text)
            if (
                dataUnit.time is not None
                and dataUnit.time.strftime("%H:%M") == achievements[0]
            ):
                text = dwg.text("🌞")
                text.translate(
                    row * rectW + row * wGap + gutter + rectW / 2 + 15,
                    column * rectH + column * hGap + gutter + rectH / 2 + 5,
                )
                group.add(text)
            if (
                dataUnit.time is not None
                and dataUnit.time.strftime("%H:%M") == achievements[3][1]
            ):
                text = dwg.text(" 🥇")
                text.translate(
                    row * rectW + row * wGap + gutter + rectW / 2 + 25,
                    column * rectH + column * hGap + gutter + rectH / 2 + 5,
                )
                group.add(text)
            if dataUnit.isMulligan:
                print(dataUnit)
                text = dwg.text("(M)")
                text.translate(
                    row * rectW + row * wGap + gutter + rectW / 2 + 15,
                    column * rectH + column * hGap + gutter + rectH / 2 + 5,
                )
                group.add(text)

            dwg.add(group)

        text = write_points(
            dwg,
            chart,
            total_points,
            rows * rectW + rows * wGap + gutter + rectW / 2 - 30,
            column * rectH + column * hGap + gutter + rectH / 2,
        )
        if column == 0:
            # add checkins heading
            text = dwg.text("Checkins", fill=text_color)
            text.translate(
                rectW * (rows + 1.1) + wGap * (rows + 1.1) + gutter + rectW / 2 - 10,
                gutter - 10,
            )
            # text.rotate(-90)
            dwg.add(text)
        if chart.name in total_checkins:
            rect = dwg.rect(
                insert=(
                    (rows + 1.5) * rectW + (rows + 1.5) * wGap + gutter,
                    column * rectH + column * hGap + gutter,
                ),
                size=(rectW, rectH),
                fill="none",
                stroke=stroke_color,
                stroke_width=1,
                rx=2,
                ry=2,
            )
            percent_checked_in = float(
                total_checkins[chart.name] / total_possible_checkins
            )
            rect_inner = dwg.rect(
                insert=(
                    (rows + 1.5) * rectW + (rows + 1.5) * wGap + gutter,
                    column * rectH + column * hGap + gutter,
                ),
                size=(rectW * percent_checked_in, rectH),
                fill=greens[5],
                stroke=stroke_color,
                stroke_width=1,
                rx=2,
                ry=2,
            )
            group = dwg.g()
            group.add(rect)
            group.add(rect_inner)
            if total_possible_checkins != total_possible_checkins_so_far:
                percent_complete = (
                    total_possible_checkins_so_far / total_possible_checkins
                )
                x = (
                    (rows + 1.5) * rectW
                    + (rows + 1.5) * wGap
                    + gutter
                    + (rectW * percent_complete)
                )
                top_y = column * rectH + column * hGap + gutter
                bottom_y = top_y + rectH
                line = dwg.line(
                    start=(x, top_y),
                    end=(x, bottom_y),
                    stroke_width=2,
                    stroke="black",
                )
                group.add(line)
            dwg.add(group)

    # Add Points Label
    text = dwg.text("Points", fill=text_color)
    text.translate(
        rectW * (rows) + wGap * (rows) + gutter + rectW / 2 - 30,
        gutter - 30,
    )
    dwg.add(text)
    text = dwg.text("(Total)", fill=text_color)
    text.translate(
        rectW * (rows) + wGap * (rows) + gutter + rectW / 2 - 30,
        gutter - 10,
    )
    dwg.add(text)

    if bye_week:
        text = dwg.text("BYE")
        text.translate(width / 4, height / 2)
        text["font-size"] = 200
        text.fill = text_color
        dwg.add(text)
        text = dwg.text("WEEK")
        text.translate(width / 4 - 50, height / 2 + 175)
        text["font-size"] = 200
        text.fill = text_color
        dwg.add(text)

    return dwg.tostring()


def write_points(dwg, chart, total_points, x, y):
    if chart.name in total_points:
        logging.debug(
            "adding points for %s total %s week %s",
            chart.name,
            total_points[chart.name],
            chart.points,
        )
        text = dwg.text(
            "%.1f (%.1f)" % (round(chart.points, 1), total_points[chart.name])
        )
        text.translate(
            x,
            y,
        )
        dwg.add(text)


def write_og_image(svg, week):
    try:
        output = "./static/preview-{week}.png".format(week=week)
        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=output)
    except:
        logging.error("Failed to write og image")


def sortCheckinByWeekday(data: List[str]) -> List[str]:
    return sorted(data, key=lambda x: weekdays.index(x.day_of_week))


def week_heat_map_from_checkins(checkins, challenge_id, rule_set):
    heatmap_data = []
    latest_date = None
    latest_date = fetchone(
        "select time at time zone 'America/New_York' from checkins order by time desc limit 1"
    )
    checkins.sort(key=lambda x: x.name)
    weeks_grouped_by_name = {
        name: list(value)
        for name, value in itertools.groupby(checkins, key=lambda x: x.name)
    }

    names_and_tags = get_challenger_info(challenge_id)
    logging.info("Challengers and tags: %s", names_and_tags)
    names = [x.name for x in names_and_tags]
    tags = {x.name: x.tag for x in names_and_tags}
    mulliganed = mulliganed_challengers(challenge_id)
    logging.info("Challengers: %s", names)
    logging.info("Tags: %s", tags)
    logging.info("Mulliganed Challengers: %s", mulliganed)
    for name in names:
        if name not in weeks_grouped_by_name:
            weeks_grouped_by_name[name] = []

    latest = "00:00"
    earliest = "23:59"
    first_to_five = None
    highest_tier = (1, "")
    if len(checkins) > 0:
        last_checkin = sorted(checkins, key=lambda x: x.time, reverse=True)[0]
        first_to_five = (last_checkin.name, last_checkin.time)
    for name in weeks_grouped_by_name:
        sorted_checkins = sortCheckinByWeekday(weeks_grouped_by_name[name])
        logging.info("checkins %s" % sorted_checkins)
        data = []
        total_checkins = 0
        point_checkins = []
        for i, weekday in enumerate(weekdays):
            checkinIndex = next(
                (
                    index
                    for index, checkin in enumerate(sorted_checkins)
                    if checkin.day_of_week == weekday
                ),
                -1,
            )
            tier = (
                sorted_checkins[checkinIndex].tier
                if len(sorted_checkins) > checkinIndex and checkinIndex >= 0
                else None
            )
            time = (
                sorted_checkins[checkinIndex].time
                if len(sorted_checkins) > checkinIndex and checkinIndex >= 0
                else None
            )
            isMulligan = (
                sorted_checkins[checkinIndex].ismulligan
                if len(sorted_checkins) > checkinIndex and checkinIndex >= 0
                else None
            )
            time_hour = time.strftime("%H:%M") if time else None
            checked_in = bool(checkinIndex + 1)
            if time_hour and time_hour > latest:
                latest = time_hour
            if time_hour and time_hour < earliest:
                logging.info(
                    "time hour %s earliest %s checkin %s", time_hour, earliest, name
                )
                earliest = time_hour
            total_checkins += 1 if checked_in else 0
            if (
                first_to_five is not None
                and total_checkins > 4
                and time is not None
                and time < first_to_five[1]
            ):
                logging.debug("new first to five %s %s", name, time)
                first_to_five = (name, time)
            if tier and not sorted_checkins[checkinIndex].bye_week:
                points = score(tier, rule_set)
                point_checkins.append(points)
                if points > highest_tier[0]:
                    highest_tier = (points, time.strftime("%H:%M"))
            data.append(
                DataUnit(weekday, checkinIndex + 1, checked_in, time, tier, isMulligan)
            )
        heatmap_data.append(
            CheckinChartData(
                name,
                data,
                total_checkins,
                sum(sorted(point_checkins, reverse=True)[:5]),
                name in mulliganed,
                tags[name]
            )
        )
    return heatmap_data, latest_date[0], (earliest, latest, first_to_five, highest_tier)
